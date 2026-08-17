import json
import os
import shutil
import stat
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from . import manifest as manifest_mod
from . import providers
from . import state as state_mod
from . import templates
from .manifest import repo_source_path
from .state import canonical_value_hash, sha256_bytes, sha256_file


class InstallerError(Exception):
    pass


class SafetyError(InstallerError):
    pass


class ValidationError(InstallerError):
    pass


class TransactionError(InstallerError):
    pass


class RecoveryError(InstallerError):
    pass


_replace = os.replace
_fsync = os.fsync


def fault_hook(checkpoint):
    pass


def _lstat(path):
    try:
        return os.lstat(path)
    except (FileNotFoundError, NotADirectoryError):
        return None


def safe_dest_path(home, raw, op):
    if "\0" in raw:
        raise SafetyError("destination contains NUL byte")
    home = Path(os.path.realpath(str(home)))
    if raw == "~":
        p = home
    elif raw.startswith("~/"):
        p = home / raw[2:]
    elif raw.startswith("/"):
        p = Path(raw)
    else:
        raise SafetyError(f"destination must be absolute or ~-relative: {raw}")
    p = Path(os.path.normpath(str(p)))
    try:
        rel = p.relative_to(home)
    except ValueError:
        raise SafetyError(f"destination {raw} resolves outside the home directory")
    if p == home:
        raise SafetyError("destination may not be the home directory itself")
    _check_ancestors(home, p)
    st = _lstat(p)
    if st is not None:
        if stat.S_ISLNK(st.st_mode):
            if op != "link":
                raise SafetyError(f"destination {p} is a symlink")
        elif stat.S_ISDIR(st.st_mode):
            if op != "git_tree":
                raise SafetyError(f"destination {p} is a directory")
        elif not stat.S_ISREG(st.st_mode):
            raise SafetyError(f"destination {p} is a special file")
    return p


def _check_ancestors(home, p):
    cur = home
    for part in p.parent.relative_to(home).parts:
        cur = cur / part
        st = _lstat(cur)
        if st is None:
            break
        if stat.S_ISLNK(st.st_mode):
            raise SafetyError(f"ancestor {cur} is a symlink")
        if not stat.S_ISDIR(st.st_mode):
            raise SafetyError(f"ancestor {cur} is not a directory")


def _fsync_dir(path):
    fd = os.open(path, os.O_RDONLY)
    try:
        _fsync(fd)
    finally:
        os.close(fd)


def safe_write_bytes(dest, data, mode):
    dest = Path(dest)
    fd, tmpname = tempfile.mkstemp(prefix=".seshat-", dir=str(dest.parent))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            _fsync(f.fileno())
            os.fchmod(f.fileno(), mode)
        _replace(tmpname, dest)
    except BaseException:
        try:
            os.unlink(tmpname)
        except OSError:
            pass
        raise
    _fsync_dir(dest.parent)
    verify_file(dest, sha256_bytes(data), mode)


def verify_file(dest, expected_sha, expected_mode):
    actual_sha = sha256_file(dest)
    if actual_sha != expected_sha:
        raise TransactionError(f"post-write verification failed for {dest}: hash mismatch")
    if expected_mode is not None:
        actual_mode = os.stat(dest).st_mode & 0o7777
        if actual_mode != expected_mode:
            raise TransactionError(
                f"post-write verification failed for {dest}: mode {oct(actual_mode)} != {oct(expected_mode)}"
            )


def make_parents(dest):
    dest = Path(dest)
    missing = []
    cur = dest.parent
    while not cur.exists():
        missing.append(cur)
        cur = cur.parent
    created = []
    for d in reversed(missing):
        d.mkdir(mode=0o755)
        created.append(str(d))
    return created


def _v_json(data, staged):
    doc = json.loads(data.decode("utf-8"))
    return doc


def _v_yaml(data, staged):
    yaml.safe_load(data.decode("utf-8"))


def _v_toml(data, staged):
    try:
        import tomllib
    except ImportError:
        raise ValidationError("toml validation requires Python 3.11+")
    tomllib.loads(data.decode("utf-8"))


def _v_utf8(data, staged):
    data.decode("utf-8")


def _v_nonempty(data, staged):
    if not data.strip():
        raise ValidationError("rendered content is empty")


def _v_executable(data, staged):
    if staged.mode is None or not (staged.mode & 0o111):
        raise ValidationError("target declares executable validation but mode is not executable")


VALIDATORS = {
    "json": _v_json,
    "yaml": _v_yaml,
    "toml": _v_toml,
    "utf8": _v_utf8,
    "nonempty": _v_nonempty,
    "executable": _v_executable,
}


def run_validators(names, data, staged):
    for name in names or []:
        fn = VALIDATORS.get(name)
        if fn is None:
            raise ValidationError(f"unknown validator: {name}")
        try:
            fn(data, staged)
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(f"validator {name} failed for {staged.target_id}: {e}")


@dataclass
class StagedTarget:
    bundle_id: str
    target_id: str
    op: str
    dest_raw: str
    dest: str
    content_path: str = None
    content_sha: str = None
    mode: int = None
    json_doc: dict = None
    key_hashes: dict = None
    owns: list = None
    link_target: str = None
    url: str = None
    ref: str = None
    replaces: list = None
    source: str = None


@dataclass
class Action:
    kind: str
    dest: str = None
    target_id: str = ""
    owner: str = ""
    op: str = ""
    pre_exists: bool = False
    pre_sha: str = None
    pre_link_target: str = None
    data_path: str = None
    content_sha: str = None
    mode: int = None
    link_target: str = None
    json_set: dict = None
    json_remove: list = None
    key_hashes: dict = None
    url: str = None
    ref: str = None
    created_dirs: list = None
    note: str = ""


def resolve_link_target(raw, home, repo):
    if raw is None:
        raise ValidationError("link target missing")
    if raw.startswith("repo:"):
        return str(repo_source_path(repo, raw[len("repo:"):]))
    home = Path(os.path.realpath(str(home)))
    if raw == "~":
        raise ValidationError("link target may not be the home directory")
    if raw.startswith("~/"):
        return str(Path(os.path.normpath(str(home / raw[2:]))))
    if raw.startswith("/"):
        return str(Path(os.path.normpath(raw)))
    raise ValidationError(f"link target must be absolute, ~-relative, or repo:-prefixed: {raw}")


def _read_combine(src_dir):
    if not src_dir.is_dir():
        raise ValidationError(f"combine source {src_dir} is not a directory")
    parts = []
    for name in sorted(os.listdir(src_dir)):
        path = src_dir / name
        st = os.lstat(path)
        if stat.S_ISDIR(st.st_mode):
            continue
        if stat.S_ISLNK(st.st_mode):
            raise ValidationError(f"combine source contains symlink: {path}")
        if not stat.S_ISREG(st.st_mode):
            raise ValidationError(f"combine source contains special file: {path}")
        parts.append(path.read_bytes() + b"\n")
    if not parts:
        raise ValidationError(f"combine source {src_dir} has no files")
    return b"".join(parts)


def stage(repo, bundles, facts, variables_by_bundle, staging_dir, home, source_commit):
    staging_dir = Path(staging_dir)
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    staging_dir.mkdir(mode=0o700, parents=True)
    staged = {}
    order = {}
    for b in bundles:
        order[b.name] = []
        variables = variables_by_bundle.get(b.name, {})
        for rt in manifest_mod.resolve_targets(b, facts):
            dest = safe_dest_path(home, rt.destination, rt.operation)
            st = StagedTarget(
                bundle_id=b.name,
                target_id=rt.id,
                op=rt.operation,
                dest_raw=rt.destination,
                dest=str(dest),
                mode=rt.mode,
                owns=rt.owns,
                url=rt.url,
                ref=rt.ref,
                replaces=rt.replaces,
                source=rt.source,
            )
            if rt.operation in ("copy", "combine", "json_merge"):
                if rt.operation == "combine":
                    data = _read_combine(repo_source_path(repo, rt.source))
                else:
                    data = repo_source_path(repo, rt.source).read_bytes()
                    if rt.template:
                        context = templates.build_context(variables, facts, b, home, source_commit)
                        data = templates.render(data, context, where=f"{b.name}:{rt.id}")
                if st.mode is None:
                    st.mode = 0o644
                run_validators(rt.validate, data, st)
                if rt.operation == "json_merge":
                    try:
                        doc = json.loads(data.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as e:
                        raise ValidationError(f"{b.name}:{rt.id}: rendered source is not valid JSON: {e}")
                    if not isinstance(doc, dict):
                        raise ValidationError(f"{b.name}:{rt.id}: json_merge source must be a JSON object")
                    owned = {k.lstrip("/") for k in rt.owns}
                    extra = set(doc) - owned
                    if extra:
                        raise ValidationError(
                            f"{b.name}:{rt.id}: source keys not declared under owns: {sorted(extra)}"
                        )
                    missing = owned - set(doc)
                    if missing:
                        raise ValidationError(
                            f"{b.name}:{rt.id}: owned keys missing from rendered source: {sorted(missing)}"
                        )
                    st.json_doc = doc
                    st.key_hashes = {k: canonical_value_hash(v) for k, v in doc.items()}
                else:
                    payload = staging_dir / rt.id
                    payload.write_bytes(data)
                    os.chmod(payload, 0o600)
                    st.content_path = str(payload)
                    st.content_sha = sha256_bytes(data)
            elif rt.operation == "link":
                st.link_target = resolve_link_target(rt.link_target, home, repo)
            elif rt.operation == "git_tree":
                pass
            else:
                raise ValidationError(f"unsupported operation: {rt.operation}")
            staged[rt.id] = st
            order[b.name].append(rt.id)
    return staged, order


def new_transaction_id():
    return time.strftime("%Y%m%dT%H%M%S") + f"-{os.getpid()}"


def _write_journal_file(tdir, journal):
    tmp = tdir / "journal.yml.tmp"
    data = yaml.safe_dump(journal, sort_keys=False).encode("utf-8")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, tdir / "journal.yml")
    dfd = os.open(tdir, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


class Transaction:
    def __init__(self, seshat_dir, home):
        self.seshat_dir = Path(seshat_dir)
        self.home = home
        self.id = new_transaction_id()
        self.dir = self.seshat_dir / "transactions" / self.id
        self.backups = self.dir / "backups"
        self.journal = {"id": self.id, "status": "running", "entries": []}

    def _save(self):
        _write_journal_file(self.dir, self.journal)

    def apply(self, actions, new_state):
        self.dir.mkdir(mode=0o700, parents=True)
        self.backups.mkdir(mode=0o700)
        self._save()
        try:
            for idx, a in enumerate(actions):
                fault_hook(f"pre_action:{idx}:{a.kind}")
                entry = self._begin(idx, a)
                self._execute(a, entry, new_state)
                entry["status"] = "done"
                self._save()
                fault_hook(f"post_action:{idx}:{a.kind}")
            fault_hook("pre_state_write")
            entry = {"idx": len(actions), "kind": "state_write", "dest": None, "status": "started"}
            self.journal["entries"].append(entry)
            self._save()
            state_mod.write_state(new_state, self.seshat_dir)
            entry["status"] = "done"
            self._save()
            fault_hook("post_state_write")
            self.journal["status"] = "committed"
            self._save()
        except BaseException:
            self.journal["status"] = "rolling_back"
            self._save()
            ok = _rollback_from_dir(self.dir)
            journal = yaml.safe_load((self.dir / "journal.yml").read_text())
            journal["status"] = "rolled_back" if ok else "rollback_incomplete"
            _write_journal_file(self.dir, journal)
            if not ok:
                raise RecoveryError(
                    f"rollback incomplete for transaction {self.id}; inspect {self.dir} before retrying"
                )
            raise
        shutil.rmtree(self.dir, ignore_errors=True)

    def _begin(self, idx, a):
        entry = {
            "idx": idx,
            "kind": a.kind,
            "dest": a.dest,
            "pre_exists": False,
            "backup": None,
            "pre_mode": None,
            "pre_link": None,
            "old_head": None,
            "created_git": False,
            "created_dirs": [],
            "removed_dirs": [],
            "status": "started",
        }
        if a.dest is not None and a.kind not in ("adopt", "noop"):
            dest = Path(a.dest)
            home = Path(os.path.realpath(str(self.home)))
            try:
                dest.relative_to(home)
            except ValueError:
                raise SafetyError(f"destination {dest} escapes home")
            _check_ancestors(home, dest)
            st = _lstat(dest)
            if a.kind in ("git_clone", "git_ff"):
                pass
            elif st is None:
                if a.pre_exists:
                    raise TransactionError(f"{dest} vanished between planning and apply")
            else:
                if not a.pre_exists:
                    raise TransactionError(f"{dest} appeared between planning and apply")
                if stat.S_ISLNK(st.st_mode):
                    actual = os.readlink(dest)
                    if a.pre_link_target is not None and actual != a.pre_link_target:
                        raise TransactionError(f"{dest} link target changed between planning and apply")
                    entry["pre_exists"] = True
                    entry["pre_link"] = actual
                elif stat.S_ISREG(st.st_mode):
                    if a.pre_sha is not None and sha256_file(dest) != a.pre_sha:
                        raise TransactionError(f"{dest} changed between planning and apply")
                    entry["pre_exists"] = True
                    entry["pre_mode"] = st.st_mode & 0o7777
                    backup_name = str(idx)
                    shutil.copy2(dest, self.backups / backup_name)
                    entry["backup"] = backup_name
                else:
                    raise SafetyError(f"{dest} is not a regular file or symlink")
        self.journal["entries"].append(entry)
        self._save()
        return entry

    def _execute(self, a, entry, new_state):
        dest = Path(a.dest) if a.dest else None
        if a.kind in ("write_file", "restore_default"):
            entry["created_dirs"] = make_parents(dest)
            self._save()
            data = Path(a.data_path).read_bytes()
            safe_write_bytes(dest, data, a.mode)
            self._note_created_dirs(new_state, a, entry)
        elif a.kind in ("write_json", "remove_json_keys"):
            entry["created_dirs"] = make_parents(dest)
            self._save()
            existing = {}
            if entry["pre_exists"]:
                existing = json.loads(dest.read_text(encoding="utf-8"))
                if not isinstance(existing, dict):
                    raise TransactionError(f"{dest} is not a JSON object")
            doc = dict(existing)
            for k, v in (a.json_set or {}).items():
                doc[k] = v
            for k in a.json_remove or []:
                doc.pop(k, None)
            out = (json.dumps(doc, indent=2) + "\n").encode("utf-8")
            safe_write_bytes(dest, out, a.mode if a.mode is not None else 0o644)
            reread = json.loads(dest.read_text(encoding="utf-8"))
            for k, h in (a.key_hashes or {}).items():
                if k not in reread or canonical_value_hash(reread[k]) != h:
                    raise TransactionError(f"post-write verification failed for {dest} key /{k}")
            for k in a.json_remove or []:
                if k in reread:
                    raise TransactionError(f"post-write verification failed for {dest}: key /{k} not removed")
            self._note_created_dirs(new_state, a, entry)
        elif a.kind == "symlink":
            entry["created_dirs"] = make_parents(dest)
            self._save()
            tmp = dest.parent / f".seshat-lnk-{os.getpid()}"
            if os.path.lexists(tmp):
                os.unlink(tmp)
            os.symlink(a.link_target, tmp)
            _replace(tmp, dest)
            if os.readlink(dest) != a.link_target:
                raise TransactionError(f"post-write verification failed for symlink {dest}")
            self._note_created_dirs(new_state, a, entry)
        elif a.kind == "chmod":
            os.chmod(dest, a.mode)
            if a.content_sha:
                verify_file(dest, a.content_sha, a.mode)
        elif a.kind == "git_clone":
            entry["created_dirs"] = make_parents(dest)
            self._save()
            tmpdest = Path(str(dest) + ".seshat-new")
            if tmpdest.exists():
                shutil.rmtree(tmpdest)
            providers.git_clone(a.url, tmpdest, a.ref)
            os.rename(tmpdest, dest)
            entry["created_git"] = True
            self._save()
            head = providers.git_head(dest)
            rec = new_state.targets.get(str(dest))
            if rec is not None:
                rec["installed_commit"] = head
            self._note_created_dirs(new_state, a, entry)
        elif a.kind == "git_ff":
            old_head = providers.git_head(dest)
            entry["old_head"] = old_head
            self._save()
            try:
                fetched = providers.git_fetch_head(dest, a.ref)
            except providers.GitError:
                rec = new_state.targets.get(str(dest))
                if rec is not None:
                    rec["installed_commit"] = old_head
                entry["fetch_failed"] = True
                return
            if fetched != old_head:
                if not providers.git_is_ancestor(dest, old_head, fetched):
                    raise TransactionError(
                        f"{dest} has local commits that diverge from origin; refusing non-fast-forward update"
                    )
                providers.git_ff_to(dest, fetched)
            rec = new_state.targets.get(str(dest))
            if rec is not None:
                rec["installed_commit"] = providers.git_head(dest)
        elif a.kind == "remove_file":
            os.unlink(dest)
            removed = []
            for d in reversed(a.created_dirs or []):
                try:
                    os.rmdir(d)
                    removed.append(d)
                except OSError:
                    break
            entry["removed_dirs"] = removed
        elif a.kind in ("adopt", "noop"):
            pass
        else:
            raise TransactionError(f"unknown action kind: {a.kind}")

    def _note_created_dirs(self, new_state, a, entry):
        if entry["created_dirs"]:
            rec = new_state.targets.get(a.dest)
            if rec is not None:
                rec["created_dirs"] = entry["created_dirs"]


def _undo_entry(tdir, entry):
    kind = entry["kind"]
    seshat_dir = tdir.parent.parent
    if kind == "state_write":
        if entry["status"] in ("started", "done"):
            state_mod.restore_state_backup(seshat_dir)
        return
    dest = Path(entry["dest"]) if entry.get("dest") else None
    if kind == "git_clone":
        if entry.get("created_git") and dest is not None and dest.exists():
            shutil.rmtree(dest)
        _rmdirs(entry.get("created_dirs"))
        return
    if kind == "git_ff":
        if entry.get("old_head") and dest is not None and dest.exists() and not entry.get("fetch_failed"):
            providers.git_reset_hard(dest, entry["old_head"])
        return
    if kind in ("adopt", "noop"):
        return
    if dest is None:
        return
    if entry.get("backup"):
        data = (tdir / "backups" / entry["backup"]).read_bytes()
        os.makedirs(dest.parent, exist_ok=True)
        if os.path.lexists(dest) and os.path.islink(dest):
            os.unlink(dest)
        mode = entry.get("pre_mode") if entry.get("pre_mode") is not None else 0o644
        safe_write_bytes(dest, data, mode)
        for d in entry.get("removed_dirs") or []:
            os.makedirs(d, exist_ok=True)
    elif entry.get("pre_link"):
        if os.path.lexists(dest):
            os.unlink(dest)
        os.symlink(entry["pre_link"], dest)
    elif not entry.get("pre_exists"):
        if os.path.lexists(dest):
            if os.path.isdir(dest) and not os.path.islink(dest):
                shutil.rmtree(dest)
            else:
                os.unlink(dest)
        _rmdirs(entry.get("created_dirs"))
    elif kind == "chmod" and entry.get("pre_mode") is not None:
        os.chmod(dest, entry["pre_mode"])


def _rmdirs(dirs):
    for d in reversed(dirs or []):
        try:
            os.rmdir(d)
        except OSError:
            pass


def _rollback_from_dir(tdir):
    tdir = Path(tdir)
    journal = yaml.safe_load((tdir / "journal.yml").read_text())
    entries = journal.get("entries", [])
    ok = True
    for entry in reversed(entries):
        if entry.get("status") == "rolled_back":
            continue
        try:
            _undo_entry(tdir, entry)
            entry["status"] = "rolled_back"
        except Exception:
            ok = False
            break
        _write_journal_file(tdir, journal)
    _write_journal_file(tdir, journal)
    return ok


def recover(seshat_dir):
    tx_root = Path(seshat_dir) / "transactions"
    if not tx_root.is_dir():
        return []
    recovered = []
    for tdir in sorted(tx_root.iterdir()):
        if not tdir.is_dir():
            continue
        journal_path = tdir / "journal.yml"
        if not journal_path.exists():
            shutil.rmtree(tdir, ignore_errors=True)
            continue
        try:
            journal = yaml.safe_load(journal_path.read_text())
        except yaml.YAMLError:
            raise RecoveryError(f"transaction journal {journal_path} is unreadable; inspect it manually")
        status = journal.get("status")
        if status in ("committed", "rolled_back"):
            shutil.rmtree(tdir, ignore_errors=True)
            continue
        ok = _rollback_from_dir(tdir)
        journal = yaml.safe_load(journal_path.read_text())
        journal["status"] = "rolled_back" if ok else "rollback_incomplete"
        _write_journal_file(tdir, journal)
        if not ok:
            raise RecoveryError(
                f"transaction {tdir.name} could not be rolled back; inspect {tdir} before retrying"
            )
        recovered.append(tdir.name)
        shutil.rmtree(tdir, ignore_errors=True)
    return recovered
