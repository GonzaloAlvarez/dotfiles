import getpass
import os
import platform
import re
import socket
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .state import canonical_json, canonical_value_hash, sha256_bytes, sha256_file

MANIFEST_SCHEMA = 1
ID_RE = re.compile(r"^[a-z][a-z0-9_-]*(\.[a-z][a-z0-9_-]*)*$")
OWNS_RE = re.compile(r"^/[A-Za-z0-9_.-]+$")
FACT_NAMES = ("os", "arch", "user", "hostname", "flavor")
OPERATIONS = ("copy", "combine", "link", "json_merge", "git_tree")


class ManifestError(Exception):
    pass


@dataclass(frozen=True)
class Facts:
    os: str
    arch: str
    user: str
    hostname: str
    flavor: str = "standard"


def gather_facts():
    machine = platform.machine().lower()
    arch = {"x86_64": "amd64", "aarch64": "arm64"}.get(machine, machine)
    return Facts(
        os=platform.system().lower(),
        arch=arch,
        user=getpass.getuser(),
        hostname=socket.gethostname().split(".")[0],
        flavor="termux" if os.environ.get("TERMUX_VERSION") else "standard",
    )


@dataclass
class Variable:
    name: str
    type: str = "string"
    default: object = None
    environment: str = None


@dataclass
class Variant:
    source: str
    when: dict = None


@dataclass
class Target:
    id: str
    operation: str
    destination: str
    source: str = None
    mode: int = None
    owns: list = field(default_factory=list)
    validate: list = field(default_factory=list)
    when: dict = None
    variants: list = field(default_factory=list)
    replaces: list = field(default_factory=list)
    template: bool = False
    url: str = None
    ref: str = None
    link_target: str = None


@dataclass
class ResolvedTarget:
    id: str
    operation: str
    destination: str
    source: str = None
    mode: int = None
    owns: list = field(default_factory=list)
    validate: list = field(default_factory=list)
    replaces: list = field(default_factory=list)
    template: bool = False
    url: str = None
    ref: str = None
    link_target: str = None


@dataclass
class Bundle:
    name: str
    description: str = ""
    automatic: bool = False
    tags: list = field(default_factory=list)
    depends_on: list = field(default_factory=list)
    platforms: dict = field(default_factory=dict)
    requires_commands: list = field(default_factory=list)
    requires_kauket: list = field(default_factory=list)
    variables: dict = field(default_factory=dict)
    targets: list = field(default_factory=list)
    path: str = ""


def _check_keys(mapping, allowed, required, where):
    if not isinstance(mapping, dict):
        raise ManifestError(f"{where}: expected a mapping")
    unknown = set(mapping) - set(allowed)
    if unknown:
        raise ManifestError(f"{where}: unknown fields: {sorted(unknown)}")
    missing = set(required) - set(mapping)
    if missing:
        raise ManifestError(f"{where}: missing required fields: {sorted(missing)}")


def _str_list(value, where):
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ManifestError(f"{where}: expected a list of strings")
    return list(value)


def _parse_when(when, where):
    if when is None:
        return None
    if not isinstance(when, dict):
        raise ManifestError(f"{where}: when must be a mapping")
    out = {}
    for fact, want in when.items():
        if fact not in FACT_NAMES:
            raise ManifestError(f"{where}: unknown fact in when: {fact}")
        if isinstance(want, str):
            want = [want]
        out[fact] = _str_list(want, f"{where}.when.{fact}")
    return out


def _parse_mode(value, where):
    if value is None:
        return None
    if not isinstance(value, str) or not re.match(r"^0[0-7]{3}$", value):
        raise ManifestError(f"{where}: mode must be a four-digit octal string like \"0644\"")
    return int(value, 8)


def _parse_target(raw, bundle_name):
    where = f"bundle {bundle_name} target"
    _check_keys(
        raw,
        (
            "id", "operation", "source", "destination", "mode", "owns", "validate",
            "when", "variants", "replaces", "template", "url", "ref", "target",
        ),
        ("id", "operation", "destination"),
        where,
    )
    tid = raw["id"]
    if not isinstance(tid, str) or not ID_RE.match(tid):
        raise ManifestError(f"{where}: invalid target id: {tid!r}")
    where = f"bundle {bundle_name} target {tid}"
    op = raw["operation"]
    if op not in OPERATIONS:
        raise ManifestError(f"{where}: unsupported operation: {op!r}")
    dest = raw["destination"]
    if not isinstance(dest, str) or not dest:
        raise ManifestError(f"{where}: destination must be a non-empty string")

    variants = []
    for v in raw.get("variants") or []:
        _check_keys(v, ("when", "source"), ("source",), f"{where} variant")
        variants.append(Variant(source=v["source"], when=_parse_when(v.get("when"), f"{where} variant")))

    template = False
    if "template" in raw:
        if raw["template"] != "jinja2":
            raise ManifestError(f"{where}: template must be \"jinja2\"")
        template = True

    owns = []
    for o in raw.get("owns") or []:
        if not isinstance(o, str) or not OWNS_RE.match(o):
            raise ManifestError(f"{where}: invalid owns pointer: {o!r} (top-level keys only)")
        if o in owns:
            raise ManifestError(f"{where}: duplicate owns pointer: {o}")
        owns.append(o)

    replaces = _str_list(raw.get("replaces") or [], f"{where}.replaces")
    if replaces and replaces != ["default"]:
        raise ManifestError(f"{where}: replaces may only be [default]")

    t = Target(
        id=tid,
        operation=op,
        destination=dest,
        source=raw.get("source"),
        mode=_parse_mode(raw.get("mode"), where),
        owns=owns,
        validate=_str_list(raw.get("validate") or [], f"{where}.validate"),
        when=_parse_when(raw.get("when"), where),
        variants=variants,
        replaces=replaces,
        template=template,
        url=raw.get("url"),
        ref=raw.get("ref"),
        link_target=raw.get("target"),
    )

    if op in ("copy", "json_merge"):
        if bool(t.source) == bool(t.variants):
            raise ManifestError(f"{where}: exactly one of source or variants is required")
        if t.url or t.ref or t.link_target:
            raise ManifestError(f"{where}: url/ref/target not allowed for {op}")
    if op == "combine":
        if not t.source or t.variants:
            raise ManifestError(f"{where}: combine requires source and does not support variants")
        if t.template or t.url or t.ref or t.link_target or t.owns:
            raise ManifestError(f"{where}: combine supports only source/destination/mode/validate/when")
    if op == "link":
        if not t.link_target:
            raise ManifestError(f"{where}: link requires target")
        if t.source or t.variants or t.template or t.url or t.ref or t.owns or t.mode is not None:
            raise ManifestError(f"{where}: link supports only target/destination/when/replaces")
    if op == "json_merge":
        if not t.owns:
            raise ManifestError(f"{where}: json_merge requires owns")
        if t.replaces:
            raise ManifestError(f"{where}: replaces is not supported for json_merge")
    else:
        if t.owns and op != "json_merge":
            raise ManifestError(f"{where}: owns is only valid for json_merge")
    if op == "git_tree":
        if not t.url:
            raise ManifestError(f"{where}: git_tree requires url")
        if t.source or t.variants or t.template or t.link_target or t.mode is not None or t.replaces:
            raise ManifestError(f"{where}: git_tree supports only url/ref/destination/when")
    if op != "json_merge" and t.template and op != "copy":
        raise ManifestError(f"{where}: template is only valid for copy and json_merge")

    return t


def _parse_bundle(raw, path, expected_name):
    where = f"manifest {path}"
    _check_keys(
        raw,
        (
            "schema", "name", "description", "automatic", "tags", "depends_on",
            "platforms", "requires", "variables", "targets",
        ),
        ("schema", "name"),
        where,
    )
    if raw["schema"] != MANIFEST_SCHEMA:
        raise ManifestError(f"{where}: unsupported schema: {raw['schema']!r}")
    name = raw["name"]
    if not isinstance(name, str) or not ID_RE.match(name):
        raise ManifestError(f"{where}: invalid bundle name: {name!r}")
    if expected_name and name != expected_name:
        raise ManifestError(f"{where}: bundle name {name!r} does not match its location ({expected_name})")

    platforms = {}
    rawp = raw.get("platforms") or {}
    if not isinstance(rawp, dict):
        raise ManifestError(f"{where}: platforms must be a mapping")
    for key in rawp:
        if key not in ("os", "arch", "flavor"):
            raise ManifestError(f"{where}: unknown platforms key: {key}")
        platforms[key] = _str_list(rawp[key], f"{where}.platforms.{key}")

    requires = raw.get("requires") or {}
    _check_keys(requires, ("commands", "kauket"), (), f"{where}.requires")
    requires_commands = _str_list(requires.get("commands") or [], f"{where}.requires.commands")
    requires_kauket = []
    for k in requires.get("kauket") or []:
        _check_keys(k, ("id", "action"), ("id", "action"), f"{where}.requires.kauket")
        if k["action"] != "install":
            raise ManifestError(f"{where}: unsupported kauket action: {k['action']!r}")
        if not isinstance(k["id"], str) or not k["id"]:
            raise ManifestError(f"{where}: kauket id must be a non-empty string")
        requires_kauket.append({"id": k["id"], "action": k["action"]})

    variables = {}
    rawv = raw.get("variables") or {}
    if not isinstance(rawv, dict):
        raise ManifestError(f"{where}: variables must be a mapping")
    for vname, vdef in rawv.items():
        if not re.match(r"^[a-z][a-z0-9_]*$", vname or ""):
            raise ManifestError(f"{where}: invalid variable name: {vname!r}")
        _check_keys(vdef or {}, ("type", "default", "environment"), ("type",), f"{where}.variables.{vname}")
        if vdef["type"] != "string":
            raise ManifestError(f"{where}: variable {vname}: only type string is supported")
        default = vdef.get("default")
        if default is not None and not isinstance(default, str):
            raise ManifestError(f"{where}: variable {vname}: default must be a string")
        environment = vdef.get("environment")
        if environment is not None and not isinstance(environment, str):
            raise ManifestError(f"{where}: variable {vname}: environment must be a string")
        variables[vname] = Variable(name=vname, type="string", default=default, environment=environment)

    targets = [_parse_target(t, name) for t in raw.get("targets") or []]
    seen = set()
    for t in targets:
        if t.id in seen:
            raise ManifestError(f"{where}: duplicate target id: {t.id}")
        seen.add(t.id)

    automatic = raw.get("automatic", False)
    if not isinstance(automatic, bool):
        raise ManifestError(f"{where}: automatic must be a boolean")

    return Bundle(
        name=name,
        description=raw.get("description") or "",
        automatic=automatic,
        tags=_str_list(raw.get("tags") or [], f"{where}.tags"),
        depends_on=_str_list(raw.get("depends_on") or [], f"{where}.depends_on"),
        platforms=platforms,
        requires_commands=requires_commands,
        requires_kauket=requires_kauket,
        variables=variables,
        targets=targets,
        path=str(path),
    )


def _load_yaml(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ManifestError(f"manifest {path} is not valid YAML: {e}")
    if not isinstance(data, dict):
        raise ManifestError(f"manifest {path} must be a YAML mapping")
    return data


def load_bundles(repo):
    repo = Path(repo)
    bundles_dir = repo / "bundles"
    if not bundles_dir.is_dir():
        raise ManifestError(f"no bundles directory at {bundles_dir}")
    bundles = {}
    default_path = bundles_dir / "default.yml"
    if not default_path.exists():
        raise ManifestError(f"missing default bundle manifest: {default_path}")
    default = _parse_bundle(_load_yaml(default_path), default_path, "default")
    bundles[default.name] = default
    for entry in sorted(bundles_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "bundle.yml"
        if not manifest_path.exists():
            raise ManifestError(f"bundle directory {entry} has no bundle.yml")
        b = _parse_bundle(_load_yaml(manifest_path), manifest_path, entry.name)
        if b.name in bundles:
            raise ManifestError(f"duplicate bundle name: {b.name}")
        bundles[b.name] = b

    all_targets = {}
    for b in bundles.values():
        for t in b.targets:
            if t.id in all_targets:
                raise ManifestError(
                    f"target id {t.id} declared by both {all_targets[t.id]} and {b.name}"
                )
            all_targets[t.id] = b.name
        for dep in b.depends_on:
            if dep not in bundles:
                raise ManifestError(f"bundle {b.name} depends on unknown bundle: {dep}")
    for name in bundles:
        resolve_order(bundles, name)
    return bundles


def repo_source_path(repo, rel):
    if rel is None:
        raise ManifestError("missing source path")
    if "\0" in rel or rel.startswith("/") or rel.startswith("~"):
        raise ManifestError(f"source must be repo-relative: {rel}")
    repo = Path(os.path.realpath(str(repo)))
    p = Path(os.path.normpath(str(repo / rel)))
    try:
        p.relative_to(repo)
    except ValueError:
        raise ManifestError(f"source {rel} escapes the repository")
    return p


def evaluate_when(when, facts):
    if not when:
        return True
    for fact, want in when.items():
        if getattr(facts, fact) not in want:
            return False
    return True


def bundle_active(bundle, facts):
    for key, want in (bundle.platforms or {}).items():
        if getattr(facts, key) not in want:
            return False
    return True


def resolve_targets(bundle, facts):
    if not bundle_active(bundle, facts):
        return []
    out = []
    for t in bundle.targets:
        if not evaluate_when(t.when, facts):
            continue
        source = t.source
        if t.variants:
            source = None
            for v in t.variants:
                if evaluate_when(v.when, facts):
                    source = v.source
                    break
            if source is None:
                continue
        out.append(
            ResolvedTarget(
                id=t.id,
                operation=t.operation,
                destination=t.destination,
                source=source,
                mode=t.mode,
                owns=list(t.owns),
                validate=list(t.validate),
                replaces=list(t.replaces),
                template=t.template,
                url=t.url,
                ref=t.ref,
                link_target=t.link_target,
            )
        )
    return out


def resolve_order(bundles, root):
    seen = {}
    out = []

    def visit(name, chain):
        if name not in bundles:
            raise ManifestError(f"unknown bundle in dependency chain: {name}")
        if seen.get(name) == 1:
            return
        if seen.get(name) == 0:
            raise ManifestError(f"dependency cycle: {' -> '.join(chain + [name])}")
        seen[name] = 0
        for dep in bundles[name].depends_on:
            visit(dep, chain + [name])
        seen[name] = 1
        out.append(name)

    visit(root, [])
    return out


def check_overlaps(bundles, facts, home_str="~"):
    dests = {}
    dirs = {}
    for b in bundles.values():
        for rt in resolve_targets(b, facts):
            key = os.path.normpath(rt.destination)
            if rt.operation == "json_merge":
                claimed = dests.setdefault(key, {"type": "json", "keys": {}, "by": []})
                if claimed.get("type") != "json":
                    raise ManifestError(
                        f"{rt.destination} is claimed both as a whole target and for JSON keys"
                    )
                for o in rt.owns:
                    if o in claimed["keys"]:
                        raise ManifestError(
                            f"JSON key {o} of {rt.destination} is owned by both "
                            f"{claimed['keys'][o]} and {b.name}:{rt.id}"
                        )
                    claimed["keys"][o] = f"{b.name}:{rt.id}"
            else:
                prev = dests.get(key)
                if prev is not None and not _replacement_pair(prev, b, rt):
                    raise ManifestError(
                        f"{rt.destination} is claimed by both {prev['by'][0]} and {b.name}:{rt.id}"
                    )
                dests.setdefault(key, {"type": "file", "by": []})["by"].append(f"{b.name}:{rt.id}")
                if rt.operation == "git_tree":
                    dirs[key] = f"{b.name}:{rt.id}"
    for d, owner in dirs.items():
        for other, info in dests.items():
            if other == d:
                continue
            if other.startswith(d + "/") or d.startswith(other + "/"):
                raise ManifestError(
                    f"target {other} overlaps directory {d} wholly owned by {owner}"
                )
    return True


def _replacement_pair(prev, bundle, rt):
    return bool(rt.replaces) and prev.get("type") == "file"


def bundle_source_digest(bundle, repo, facts):
    norm_targets = []
    for rt in resolve_targets(bundle, facts):
        t = {
            "id": rt.id,
            "op": rt.operation,
            "dest": rt.destination,
            "mode": rt.mode,
            "owns": sorted(rt.owns or []),
            "validate": list(rt.validate or []),
            "template": bool(rt.template),
            "replaces": list(rt.replaces or []),
        }
        if rt.operation in ("copy", "json_merge"):
            p = repo_source_path(repo, rt.source)
            if not p.is_file():
                raise ManifestError(f"bundle {bundle.name} target {rt.id}: source not found: {rt.source}")
            t["payload"] = {"file": rt.source, "sha256": sha256_file(p)}
        elif rt.operation == "combine":
            src = repo_source_path(repo, rt.source)
            if not src.is_dir():
                raise ManifestError(f"bundle {bundle.name} target {rt.id}: source not found: {rt.source}")
            frags = []
            for name in sorted(os.listdir(src)):
                fp = src / name
                if fp.is_file() and not fp.is_symlink():
                    frags.append({"name": name, "sha256": sha256_file(fp)})
            t["payload"] = {"fragments": frags}
        elif rt.operation == "link":
            t["payload"] = {"link_target": rt.link_target}
        elif rt.operation == "git_tree":
            t["payload"] = {"url": rt.url, "ref": rt.ref}
        norm_targets.append(t)
    norm = {
        "v": 1,
        "bundle": bundle.name,
        "depends_on": sorted(bundle.depends_on),
        "requires": {
            "commands": sorted(bundle.requires_commands),
            "kauket": sorted(bundle.requires_kauket, key=lambda k: k["id"]),
        },
        "variables": {
            n: {"type": v.type, "default": v.default, "environment": v.environment}
            for n, v in bundle.variables.items()
        },
        "targets": sorted(norm_targets, key=lambda t: t["id"]),
    }
    return sha256_bytes(canonical_json(norm))


def variables_digest(values):
    return canonical_value_hash(values or {})
