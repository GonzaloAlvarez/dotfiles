import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import manifest as manifest_mod
from . import ownership, providers
from .installer import Action
from .ownership import Status, probe
from .state import canonical_value_hash


class PlanError(Exception):
    pass


@dataclass
class Blocked:
    bundle: str
    target_id: str
    dest: str
    reason: str
    key: str = None


@dataclass
class Skipped:
    bundle: str
    target_id: str
    dest: str
    reason: str


@dataclass
class Change:
    kind: str
    dest: str
    target_id: str
    bundle: str
    detail: str = ""


@dataclass
class Plan:
    actions: list = field(default_factory=list)
    blocked: list = field(default_factory=list)
    skipped: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    new_state: object = None


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _mode_str(mode):
    return f"{mode:04o}" if mode is not None else None


def _carry(old_record, new_record):
    if old_record and old_record.get("created_dirs"):
        new_record["created_dirs"] = old_record["created_dirs"]
    return new_record


def _file_record(bundle, st):
    return {
        "type": "file",
        "op": st.op,
        "owner": bundle,
        "target_id": st.target_id,
        "source": st.source,
        "installed_sha256": st.content_sha,
        "mode": _mode_str(st.mode if st.mode is not None else 0o644),
    }


def plan_install(
    repo,
    bundles,
    apply_names,
    staged,
    staged_order,
    state,
    facts,
    home,
    automatic,
    source_commit,
    variables_by_bundle,
):
    plan = Plan(new_state=state.copy())
    plan.new_state.data["repository"]["commit"] = source_commit
    json_ops = {}
    json_order = []
    staged_by_dest = {s.dest: s for s in staged.values()}
    for bname in apply_names:
        b = bundles[bname]
        for tid in staged_order.get(bname, []):
            st = staged[tid]
            if st.op in ("copy", "combine"):
                _plan_file(plan, b, st, state, staged_by_dest)
            elif st.op == "link":
                _plan_link(plan, b, st, state)
            elif st.op == "json_merge":
                _plan_json(plan, b, st, state, json_ops, json_order)
            elif st.op == "git_tree":
                _plan_git(plan, b, st, state)
        vals = variables_by_bundle.get(bname, {})
        plan.new_state.bundles[bname] = {
            "installed_commit": source_commit,
            "source_digest": manifest_mod.bundle_source_digest(b, repo, facts),
            "variables_digest": manifest_mod.variables_digest(vals),
            "variables": dict(vals),
            "installed_at": now_iso(),
        }
    _finalize_json(plan, json_ops, json_order)
    return plan


def _plan_file(plan, b, st, state, staged_by_dest):
    record = state.target(st.dest)
    fs = probe(st.dest)
    ns = plan.new_state
    status = ownership.classify_whole_file(b.name, st.content_sha, st.mode, record, fs)

    if status == Status.CONFLICT_OTHER_OWNER:
        owner = record.get("owner")
        if b.name == "default":
            plan.skipped.append(Skipped(b.name, st.target_id, st.dest, f"owned by {owner}"))
            return
        if st.replaces and owner == "default":
            if fs.kind == "file" and fs.sha == record.get("installed_sha256"):
                _emit_replace(plan, b, st, record, fs)
            else:
                plan.blocked.append(
                    Blocked(b.name, st.target_id, st.dest, "default-owned file is locally modified")
                )
            return
        plan.blocked.append(Blocked(b.name, st.target_id, st.dest, f"owned by {owner}"))
        return

    if status == Status.CONFLICT_UNMANAGED:
        if st.replaces and fs.kind == "file":
            default_staged = staged_by_dest.get(st.dest)
            if (
                default_staged is not None
                and default_staged.bundle_id == "default"
                and fs.sha == default_staged.content_sha
            ):
                _emit_replace(plan, b, st, _file_record("default", default_staged), fs)
                return
        plan.blocked.append(
            Blocked(b.name, st.target_id, st.dest, "existing unmanaged file differs from desired content")
        )
        return

    if status == Status.MODIFIED:
        plan.blocked.append(Blocked(b.name, st.target_id, st.dest, "locally modified since installation"))
        return

    new_record = _carry(record, _file_record(b.name, st))
    if record and record.get("replaced_default"):
        new_record["replaced_default"] = record["replaced_default"]

    if status in (Status.ABSENT, Status.MISSING):
        plan.actions.append(
            Action(
                kind="write_file",
                dest=st.dest,
                target_id=st.target_id,
                owner=b.name,
                op=st.op,
                pre_exists=False,
                data_path=st.content_path,
                content_sha=st.content_sha,
                mode=st.mode if st.mode is not None else 0o644,
            )
        )
        plan.changes.append(Change("install", st.dest, st.target_id, b.name))
        ns.targets[st.dest] = new_record
    elif status == Status.OUTDATED:
        plan.actions.append(
            Action(
                kind="write_file",
                dest=st.dest,
                target_id=st.target_id,
                owner=b.name,
                op=st.op,
                pre_exists=True,
                pre_sha=fs.sha,
                data_path=st.content_path,
                content_sha=st.content_sha,
                mode=st.mode if st.mode is not None else 0o644,
            )
        )
        plan.changes.append(Change("update", st.dest, st.target_id, b.name))
        ns.targets[st.dest] = new_record
    elif status == Status.ADOPTABLE:
        desired_mode = st.mode if st.mode is not None else 0o644
        if fs.mode != desired_mode:
            plan.actions.append(
                Action(
                    kind="chmod",
                    dest=st.dest,
                    target_id=st.target_id,
                    owner=b.name,
                    op=st.op,
                    pre_exists=True,
                    pre_sha=fs.sha,
                    content_sha=st.content_sha,
                    mode=desired_mode,
                )
            )
            plan.changes.append(Change("chmod", st.dest, st.target_id, b.name, _mode_str(desired_mode)))
        else:
            plan.actions.append(
                Action(kind="adopt", dest=st.dest, target_id=st.target_id, owner=b.name, op=st.op)
            )
            plan.changes.append(Change("adopt", st.dest, st.target_id, b.name))
        ns.targets[st.dest] = new_record
    elif status == Status.CURRENT:
        ns.targets[st.dest] = new_record


def _emit_replace(plan, b, st, default_record, fs):
    new_record = _file_record(b.name, st)
    new_record["replaced_default"] = {
        "target_id": default_record.get("target_id"),
        "source": default_record.get("source"),
        "installed_sha256": default_record.get("installed_sha256"),
        "mode": default_record.get("mode"),
    }
    plan.actions.append(
        Action(
            kind="write_file",
            dest=st.dest,
            target_id=st.target_id,
            owner=b.name,
            op=st.op,
            pre_exists=True,
            pre_sha=fs.sha,
            data_path=st.content_path,
            content_sha=st.content_sha,
            mode=st.mode if st.mode is not None else 0o644,
        )
    )
    plan.changes.append(Change("replace", st.dest, st.target_id, b.name, "replaces default"))
    plan.new_state.targets[st.dest] = new_record


def _plan_link(plan, b, st, state):
    record = state.target(st.dest)
    fs = probe(st.dest)
    ns = plan.new_state
    status = ownership.classify_link(b.name, st.link_target, record, fs)
    if status == Status.CONFLICT_OTHER_OWNER:
        owner = record.get("owner")
        if b.name == "default":
            plan.skipped.append(Skipped(b.name, st.target_id, st.dest, f"owned by {owner}"))
        else:
            plan.blocked.append(Blocked(b.name, st.target_id, st.dest, f"owned by {owner}"))
        return
    if status == Status.CONFLICT_UNMANAGED:
        plan.blocked.append(
            Blocked(b.name, st.target_id, st.dest, "existing file is not a seshat-managed symlink")
        )
        return
    if status == Status.MODIFIED:
        plan.blocked.append(Blocked(b.name, st.target_id, st.dest, "symlink was changed locally"))
        return
    new_record = _carry(
        record,
        {"type": "link", "owner": b.name, "target_id": st.target_id, "link_target": st.link_target},
    )
    if status in (Status.ABSENT, Status.MISSING):
        plan.actions.append(
            Action(
                kind="symlink",
                dest=st.dest,
                target_id=st.target_id,
                owner=b.name,
                op="link",
                pre_exists=False,
                link_target=st.link_target,
            )
        )
        plan.changes.append(Change("link", st.dest, st.target_id, b.name, st.link_target))
        ns.targets[st.dest] = new_record
    elif status == Status.OUTDATED:
        plan.actions.append(
            Action(
                kind="symlink",
                dest=st.dest,
                target_id=st.target_id,
                owner=b.name,
                op="link",
                pre_exists=True,
                pre_link_target=fs.link_target,
                link_target=st.link_target,
            )
        )
        plan.changes.append(Change("relink", st.dest, st.target_id, b.name, st.link_target))
        ns.targets[st.dest] = new_record
    elif status == Status.ADOPTABLE:
        plan.actions.append(
            Action(kind="adopt", dest=st.dest, target_id=st.target_id, owner=b.name, op="link")
        )
        plan.changes.append(Change("adopt", st.dest, st.target_id, b.name))
        ns.targets[st.dest] = new_record
    elif status == Status.CURRENT:
        ns.targets[st.dest] = new_record


def _plan_json(plan, b, st, state, json_ops, json_order):
    record = state.target(st.dest)
    if record is not None and record.get("type") != "json":
        plan.blocked.append(
            Blocked(b.name, st.target_id, st.dest, "destination is managed as a whole file")
        )
        return
    fs = probe(st.dest)
    if fs.kind not in ("absent", "file"):
        plan.blocked.append(Blocked(b.name, st.target_id, st.dest, f"destination is a {fs.kind}"))
        return
    doc = {}
    if fs.kind == "file":
        try:
            doc = json.loads(Path(st.dest).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            plan.blocked.append(Blocked(b.name, st.target_id, st.dest, "destination is not valid JSON"))
            return
        if not isinstance(doc, dict):
            plan.blocked.append(
                Blocked(b.name, st.target_id, st.dest, "destination is not a JSON object")
            )
            return
    if st.dest not in json_ops:
        json_ops[st.dest] = {
            "set": {},
            "key_hashes": {},
            "records": {},
            "changes": [],
            "pre_exists": fs.kind == "file",
            "pre_sha": fs.sha,
            "targets": [],
        }
        json_order.append(st.dest)
    ops = json_ops[st.dest]
    ops["targets"].append((b.name, st.target_id))
    krecs = (record or {}).get("keys", {})
    for key, value in st.json_doc.items():
        krec = krecs.get(key)
        present = key in doc
        cur_hash = canonical_value_hash(doc[key]) if present else None
        status = ownership.classify_json_key(b.name, st.key_hashes[key], krec, present, cur_hash)
        if status == Status.CONFLICT_OTHER_OWNER:
            owner = krec.get("owner")
            if b.name == "default":
                plan.skipped.append(
                    Skipped(b.name, st.target_id, st.dest, f"key /{key} owned by {owner}")
                )
            else:
                plan.blocked.append(
                    Blocked(b.name, st.target_id, st.dest, f"owned by {owner}", key=f"/{key}")
                )
            continue
        if status == Status.CONFLICT_UNMANAGED:
            plan.blocked.append(
                Blocked(
                    b.name,
                    st.target_id,
                    st.dest,
                    "existing unmanaged key differs from desired value",
                    key=f"/{key}",
                )
            )
            continue
        if status == Status.MODIFIED:
            plan.blocked.append(
                Blocked(b.name, st.target_id, st.dest, "locally modified since installation", key=f"/{key}")
            )
            continue
        if status in (Status.ABSENT, Status.MISSING, Status.OUTDATED):
            ops["set"][key] = value
            ops["key_hashes"][key] = st.key_hashes[key]
            kind = "update" if status == Status.OUTDATED else "install"
            plan.changes.append(Change(kind, st.dest, st.target_id, b.name, f"/{key}"))
        elif status == Status.ADOPTABLE:
            plan.changes.append(Change("adopt", st.dest, st.target_id, b.name, f"/{key}"))
        ops["records"][key] = {
            "owner": b.name,
            "target_id": st.target_id,
            "installed_sha256": st.key_hashes[key],
        }


def _finalize_json(plan, json_ops, json_order):
    ns = plan.new_state
    for dest in json_order:
        ops = json_ops[dest]
        if not ops["records"] and not ops["set"]:
            continue
        rec = ns.targets.get(dest)
        if rec is None or rec.get("type") != "json":
            rec = {"type": "json", "keys": {}}
            ns.targets[dest] = rec
        rec["keys"].update(ops["records"])
        if ops["set"]:
            bundle_names = ",".join(sorted({b for b, _ in ops["targets"]}))
            target_ids = ",".join(t for _, t in ops["targets"])
            plan.actions.append(
                Action(
                    kind="write_json",
                    dest=dest,
                    target_id=target_ids,
                    owner=bundle_names,
                    op="json_merge",
                    pre_exists=ops["pre_exists"],
                    pre_sha=ops["pre_sha"],
                    json_set=ops["set"],
                    key_hashes=ops["key_hashes"],
                )
            )


def _plan_git(plan, b, st, state):
    record = state.target(st.dest)
    ns = plan.new_state
    if record is not None and record.get("owner") != b.name:
        owner = record.get("owner")
        if b.name == "default":
            plan.skipped.append(Skipped(b.name, st.target_id, st.dest, f"owned by {owner}"))
        else:
            plan.blocked.append(Blocked(b.name, st.target_id, st.dest, f"owned by {owner}"))
        return
    new_record = _carry(
        record,
        {
            "type": "git_tree",
            "owner": b.name,
            "target_id": st.target_id,
            "origin": st.url,
            "installed_commit": (record or {}).get("installed_commit"),
        },
    )
    dest = Path(st.dest)
    if not os.path.lexists(dest):
        plan.actions.append(
            Action(
                kind="git_clone",
                dest=st.dest,
                target_id=st.target_id,
                owner=b.name,
                op="git_tree",
                url=st.url,
                ref=st.ref,
            )
        )
        plan.changes.append(Change("clone", st.dest, st.target_id, b.name, st.url))
        ns.targets[st.dest] = new_record
        return
    if os.path.islink(dest) or not dest.is_dir():
        plan.blocked.append(Blocked(b.name, st.target_id, st.dest, "destination is not a directory"))
        return
    if not providers.git_is_repo(dest):
        plan.blocked.append(
            Blocked(b.name, st.target_id, st.dest, "existing directory is not a git repository")
        )
        return
    origin = providers.git_origin_url(dest)
    if not providers.same_origin(origin, st.url):
        plan.blocked.append(
            Blocked(b.name, st.target_id, st.dest, f"origin {origin} does not match {st.url}")
        )
        return
    if providers.git_is_dirty(dest):
        plan.blocked.append(
            Blocked(b.name, st.target_id, st.dest, "repository has uncommitted changes")
        )
        return
    plan.actions.append(
        Action(
            kind="git_ff",
            dest=st.dest,
            target_id=st.target_id,
            owner=b.name,
            op="git_tree",
            url=st.url,
            ref=st.ref,
        )
    )
    detail = "fast-forward" if record is not None else "adopt existing clone"
    plan.changes.append(Change("git-update", st.dest, st.target_id, b.name, detail))
    ns.targets[st.dest] = new_record


def plan_remove(repo, bundles, bundle_name, state, staged_default, facts, home):
    if bundle_name == "default":
        raise PlanError("the default bundle cannot be removed")
    if bundle_name not in state.bundles:
        raise PlanError(f"bundle {bundle_name} is not installed")
    plan = Plan(new_state=state.copy())
    ns = plan.new_state
    staged_default_by_dest = {s.dest: s for s in (staged_default or {}).values()}
    owned = state.targets_owned_by(bundle_name)
    json_removals = {}
    for path, rec in owned.items():
        rtype = rec.get("type")
        fs = probe(path)
        if rtype == "json":
            full_rec = state.target(path)
            doc = {}
            if fs.kind == "file":
                try:
                    doc = json.loads(Path(path).read_text(encoding="utf-8"))
                except (json.JSONDecodeError, UnicodeDecodeError):
                    plan.blocked.append(
                        Blocked(bundle_name, "", path, "destination is not valid JSON")
                    )
                    continue
            elif fs.kind != "absent":
                plan.blocked.append(Blocked(bundle_name, "", path, f"destination is a {fs.kind}"))
                continue
            for key, krec in rec["keys"].items():
                if fs.kind == "absent" or key not in doc:
                    _drop_json_key(ns, path, key)
                    continue
                drift = ownership.json_key_drift(krec, True, canonical_value_hash(doc[key]))
                if drift == "modified":
                    plan.blocked.append(
                        Blocked(
                            bundle_name,
                            krec.get("target_id", ""),
                            path,
                            "locally modified since installation",
                            key=f"/{key}",
                        )
                    )
                    continue
                json_removals.setdefault(path, {"keys": [], "pre_sha": fs.sha})["keys"].append(key)
                plan.changes.append(
                    Change("remove-key", path, krec.get("target_id", ""), bundle_name, f"/{key}")
                )
                _drop_json_key(ns, path, key)
        elif rtype == "file":
            if fs.kind == "absent":
                ns.targets.pop(path, None)
                continue
            if fs.kind != "file" or fs.sha != rec.get("installed_sha256"):
                plan.blocked.append(
                    Blocked(
                        bundle_name,
                        rec.get("target_id", ""),
                        path,
                        "locally modified since installation",
                    )
                )
                continue
            restored = staged_default_by_dest.get(path) if rec.get("replaced_default") else None
            if restored is not None:
                plan.actions.append(
                    Action(
                        kind="restore_default",
                        dest=path,
                        target_id=restored.target_id,
                        owner="default",
                        op=restored.op,
                        pre_exists=True,
                        pre_sha=fs.sha,
                        data_path=restored.content_path,
                        content_sha=restored.content_sha,
                        mode=restored.mode if restored.mode is not None else 0o644,
                    )
                )
                plan.changes.append(
                    Change("restore", path, restored.target_id, "default", "restore default content")
                )
                ns.targets[path] = _carry(rec, _file_record("default", restored))
            else:
                plan.actions.append(
                    Action(
                        kind="remove_file",
                        dest=path,
                        target_id=rec.get("target_id", ""),
                        owner=bundle_name,
                        op="remove",
                        pre_exists=True,
                        pre_sha=fs.sha,
                        created_dirs=rec.get("created_dirs"),
                    )
                )
                plan.changes.append(Change("remove", path, rec.get("target_id", ""), bundle_name))
                ns.targets.pop(path, None)
        elif rtype == "link":
            if fs.kind == "absent":
                ns.targets.pop(path, None)
                continue
            if fs.kind != "link" or fs.link_target != rec.get("link_target"):
                plan.blocked.append(
                    Blocked(bundle_name, rec.get("target_id", ""), path, "symlink was changed locally")
                )
                continue
            plan.actions.append(
                Action(
                    kind="remove_file",
                    dest=path,
                    target_id=rec.get("target_id", ""),
                    owner=bundle_name,
                    op="remove",
                    pre_exists=True,
                    pre_link_target=fs.link_target,
                    created_dirs=rec.get("created_dirs"),
                )
            )
            plan.changes.append(Change("remove", path, rec.get("target_id", ""), bundle_name))
            ns.targets.pop(path, None)
        elif rtype == "git_tree":
            plan.blocked.append(
                Blocked(
                    bundle_name,
                    rec.get("target_id", ""),
                    path,
                    "git_tree targets are not removed automatically; delete the directory manually first",
                )
            )
    for path, info in json_removals.items():
        plan.actions.append(
            Action(
                kind="remove_json_keys",
                dest=path,
                target_id="",
                owner=bundle_name,
                op="json_merge",
                pre_exists=True,
                pre_sha=info["pre_sha"],
                json_remove=info["keys"],
            )
        )
    if not plan.blocked:
        ns.bundles.pop(bundle_name, None)
    return plan


def _drop_json_key(ns, path, key):
    rec = ns.targets.get(path)
    if rec and rec.get("type") == "json":
        rec.get("keys", {}).pop(key, None)
        if not rec.get("keys"):
            ns.targets.pop(path, None)


def has_pending_txn(seshat_dir):
    root = Path(seshat_dir) / "transactions"
    if not root.is_dir():
        return False
    for tdir in root.iterdir():
        if not tdir.is_dir():
            continue
        jp = tdir / "journal.yml"
        if not jp.exists():
            continue
        try:
            j = yaml.safe_load(jp.read_text())
        except yaml.YAMLError:
            return True
        if j.get("status") not in ("committed", "rolled_back"):
            return True
    return False


def _git_drift(record, path):
    if not os.path.lexists(path):
        return "missing"
    p = Path(path)
    if os.path.islink(p) or not p.is_dir() or not providers.git_is_repo(p):
        return "modified"
    if not providers.same_origin(providers.git_origin_url(p), record.get("origin")):
        return "modified"
    if providers.git_is_dirty(p):
        return "modified"
    installed = record.get("installed_commit")
    if installed and providers.git_head(p) != installed:
        return "modified"
    return None


def bundle_report(repo, bundles, state, name, facts, home, pending_txn):
    report = {
        "name": name,
        "state": "current",
        "installed_commit": None,
        "available": name in bundles,
        "automatic": bundles[name].automatic if name in bundles else False,
        "description": bundles[name].description if name in bundles else "",
        "targets": [],
        "problems": [],
    }
    installed = name in state.bundles
    if installed:
        report["installed_commit"] = state.bundles[name].get("installed_commit")
    if name not in bundles:
        report["state"] = "orphaned"
        report["problems"].append("bundle no longer exists in the repository")
        for path, rec in state.targets_owned_by(name).items():
            report["targets"].append({"dest": path, "state": "orphaned", "target_id": ""})
        return report
    if not installed:
        report["state"] = "not-installed"
        return report

    b = bundles[name]
    declared_ids = {t.id for t in b.targets}
    active = manifest_mod.resolve_targets(b, facts)
    flags = set()
    if pending_txn:
        flags.add("blocked")
        report["problems"].append("an incomplete transaction needs recovery")

    owned = state.targets_owned_by(name)
    seen_dests = {}
    for path, rec in owned.items():
        fs = probe(path)
        if rec.get("type") == "json":
            full = state.target(path)
            doc = None
            if fs.kind == "file":
                try:
                    doc = json.loads(Path(path).read_text(encoding="utf-8"))
                    if not isinstance(doc, dict):
                        doc = None
                except (json.JSONDecodeError, UnicodeDecodeError):
                    doc = None
            keys_detail = []
            for key, krec in rec["keys"].items():
                if krec.get("target_id") not in declared_ids:
                    flags.add("orphaned")
                    keys_detail.append({"key": f"/{key}", "state": "orphaned", "owner": name})
                    continue
                if doc is None:
                    drift = "missing" if fs.kind == "absent" else "modified"
                else:
                    present = key in doc
                    drift = ownership.json_key_drift(
                        krec, present, canonical_value_hash(doc[key]) if present else None
                    )
                if drift:
                    flags.add(drift)
                keys_detail.append({"key": f"/{key}", "state": drift or "current", "owner": name})
            if doc is not None:
                full_keys = (state.target(path) or {}).get("keys", {})
                for key in doc:
                    if key not in full_keys:
                        keys_detail.append({"key": f"/{key}", "state": "unmanaged", "owner": "unmanaged"})
                for key, krec in full_keys.items():
                    if krec.get("owner") != name:
                        keys_detail.append(
                            {"key": f"/{key}", "state": "other", "owner": krec.get("owner")}
                        )
            seen_dests[path] = True
            report["targets"].append({"dest": path, "state": None, "keys": keys_detail})
        else:
            tid = rec.get("target_id")
            if tid not in declared_ids:
                flags.add("orphaned")
                report["targets"].append({"dest": path, "state": "orphaned", "target_id": tid})
                continue
            if rec.get("type") == "file":
                drift = ownership.file_drift(rec, fs)
            elif rec.get("type") == "link":
                drift = ownership.link_drift(rec, fs)
            elif rec.get("type") == "git_tree":
                drift = _git_drift(rec, path)
            else:
                drift = "modified"
            if drift:
                flags.add(drift)
            seen_dests[path] = True
            report["targets"].append({"dest": path, "state": drift or "current", "target_id": tid})

    unclaimed = _unclaimed_active_targets(state, active, home, name)
    for dest, tid, reason in unclaimed:
        flags.add("blocked")
        report["problems"].append(f"{dest}: {reason}")
        report["targets"].append({"dest": dest, "state": "blocked", "target_id": tid})

    outdated = False
    brec = state.bundles[name]
    try:
        digest = manifest_mod.bundle_source_digest(b, repo, facts)
        if digest != brec.get("source_digest"):
            outdated = True
    except manifest_mod.ManifestError:
        flags.add("orphaned")
        report["problems"].append("a declared source no longer exists in the repository")
    if manifest_mod.variables_digest(brec.get("variables") or {}) != brec.get(
        "variables_digest", manifest_mod.variables_digest({})
    ):
        outdated = True

    for level in ("orphaned", "blocked", "missing", "modified"):
        if level in flags:
            report["state"] = level
            return report
    report["state"] = "outdated" if outdated else "current"
    return report


def _unclaimed_active_targets(state, active, home, bundle_name):
    from .installer import SafetyError, safe_dest_path

    out = []
    for rt in active:
        try:
            dest = str(safe_dest_path(home, rt.destination, rt.operation))
        except SafetyError as e:
            out.append((rt.destination, rt.id, str(e)))
            continue
        rec = state.target(dest)
        if rt.operation == "json_merge":
            keys = (rec or {}).get("keys", {}) if rec and rec.get("type") == "json" else {}
            for o in rt.owns:
                key = o.lstrip("/")
                if key not in keys:
                    out.append((dest, rt.id, f"key {o} is not claimed in state"))
        else:
            if rec is None:
                out.append((dest, rt.id, "target has no state entry"))
            elif rec.get("owner") != bundle_name and not _replaced_elsewhere(rec):
                out.append((dest, rt.id, f"state entry is owned by {rec.get('owner')}"))
    return out


def _replaced_elsewhere(rec):
    return bool(rec.get("replaced_default"))
