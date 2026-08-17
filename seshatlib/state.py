import hashlib
import json
import os
import shutil
from pathlib import Path

import yaml

STATE_SCHEMA = 1


class StateError(Exception):
    pass


class LockError(Exception):
    pass


def sha256_bytes(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_value_hash(obj):
    return sha256_bytes(canonical_json(obj))


class State:
    def __init__(self, data=None):
        if data is None:
            data = {"schema": STATE_SCHEMA, "repository": {"commit": None}, "bundles": {}, "targets": {}}
        if not isinstance(data, dict):
            raise StateError("state root must be a mapping")
        if data.get("schema") != STATE_SCHEMA:
            raise StateError(f"unsupported state schema: {data.get('schema')!r}")
        for key in ("bundles", "targets"):
            data.setdefault(key, {})
            if not isinstance(data[key], dict):
                raise StateError(f"state {key} must be a mapping")
        data.setdefault("repository", {"commit": None})
        self.data = data

    @property
    def bundles(self):
        return self.data["bundles"]

    @property
    def targets(self):
        return self.data["targets"]

    def target(self, path):
        return self.targets.get(str(path))

    def targets_owned_by(self, bundle_id):
        owned = {}
        for path, rec in self.targets.items():
            if rec.get("type") == "json":
                keys = {k: v for k, v in rec.get("keys", {}).items() if v.get("owner") == bundle_id}
                if keys:
                    owned[path] = {"type": "json", "keys": keys}
            elif rec.get("owner") == bundle_id:
                owned[path] = rec
        return owned

    def copy(self):
        return State(json.loads(json.dumps(self.data)))


def ensure_seshat_dir(seshat_dir):
    seshat_dir = Path(seshat_dir)
    seshat_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(seshat_dir, 0o700)
    for sub in ("transactions", "staging"):
        (seshat_dir / sub).mkdir(mode=0o700, exist_ok=True)
    return seshat_dir


def load_state(seshat_dir):
    seshat_dir = Path(seshat_dir)
    path = seshat_dir / "state.yml"
    bak = seshat_dir / "state.yml.bak"
    if not path.exists():
        return State()
    try:
        with open(path, "r", encoding="utf-8") as f:
            return State(yaml.safe_load(f))
    except (yaml.YAMLError, StateError) as primary_err:
        if bak.exists():
            try:
                with open(bak, "r", encoding="utf-8") as f:
                    return State(yaml.safe_load(f))
            except (yaml.YAMLError, StateError):
                pass
        raise StateError(
            f"state file {path} is unreadable ({primary_err}); inspect it manually before retrying"
        )


def _atomic_write(path, data, mode):
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    os.chmod(tmp, mode)
    os.replace(tmp, path)
    dfd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(dfd)
    finally:
        os.close(dfd)


def write_state(state, seshat_dir):
    seshat_dir = ensure_seshat_dir(seshat_dir)
    path = seshat_dir / "state.yml"
    bak = seshat_dir / "state.yml.bak"
    if path.exists():
        shutil.copy2(path, bak)
        os.chmod(bak, 0o600)
    payload = yaml.safe_dump(state.data, default_flow_style=False, sort_keys=True)
    _atomic_write(path, payload.encode("utf-8"), 0o600)


def restore_state_backup(seshat_dir):
    seshat_dir = Path(seshat_dir)
    bak = seshat_dir / "state.yml.bak"
    path = seshat_dir / "state.yml"
    if bak.exists():
        shutil.copy2(bak, path)
        os.chmod(path, 0o600)
        return True
    return False


class Lock:
    def __init__(self, seshat_dir):
        self.path = Path(seshat_dir) / "lock"
        self.acquired = False

    def acquire(self):
        for attempt in (0, 1):
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as f:
                    f.write(str(os.getpid()))
                self.acquired = True
                return self
            except FileExistsError:
                if attempt == 1:
                    break
                try:
                    pid = int(self.path.read_text().strip() or "0")
                except (OSError, ValueError):
                    pid = 0
                if pid and _pid_alive(pid):
                    raise LockError(f"another seshat process (pid {pid}) holds {self.path}")
                self.path.unlink(missing_ok=True)
        raise LockError(f"could not acquire lock {self.path}")

    def release(self):
        if self.acquired:
            self.path.unlink(missing_ok=True)
            self.acquired = False

    def __enter__(self):
        return self.acquire()

    def __exit__(self, *exc):
        self.release()


def _pid_alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
