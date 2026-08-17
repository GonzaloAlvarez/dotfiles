import json
import os
import shutil
from pathlib import Path

import pytest
import yaml

from seshatlib import installer, state as state_mod
from seshatlib.installer import (
    Action,
    RecoveryError,
    Transaction,
    TransactionError,
    recover,
)
from seshatlib.state import State, canonical_value_hash, sha256_bytes, sha256_file


def _payload(tmp_path, data=b"hello\n", name="p1"):
    p = tmp_path / name
    p.write_bytes(data)
    return p


def _write_action(tmp_path, dest, data=b"hello\n", mode=0o644, pre_exists=False, pre_sha=None, name="p1"):
    p = _payload(tmp_path, data, name)
    return Action(
        kind="write_file",
        dest=str(dest),
        target_id="t.x",
        owner="default",
        pre_exists=pre_exists,
        pre_sha=pre_sha,
        data_path=str(p),
        content_sha=sha256_bytes(data),
        mode=mode,
    )


def test_write_file_creates_and_commits_state(tmp_path, fake_home, seshat_dir):
    dest = fake_home / ".config" / "app" / "conf"
    a = _write_action(tmp_path, dest)
    st = State()
    st.targets[str(dest)] = {"type": "file", "owner": "default", "target_id": "t.x"}
    Transaction(seshat_dir, fake_home).apply([a], st)
    assert dest.read_bytes() == b"hello\n"
    assert oct(os.stat(dest).st_mode & 0o7777) == "0o644"
    reloaded = state_mod.load_state(seshat_dir)
    rec = reloaded.target(str(dest))
    assert rec["owner"] == "default"
    assert rec["created_dirs"] == [str(fake_home / ".config"), str(fake_home / ".config" / "app")]
    assert not list((seshat_dir / "transactions").iterdir())


def test_update_backs_up_and_rolls_back(tmp_path, fake_home, seshat_dir, monkeypatch):
    dest = fake_home / ".rc"
    dest.write_bytes(b"old\n")
    os.chmod(dest, 0o600)
    old_sha = sha256_file(dest)
    a = _write_action(tmp_path, dest, data=b"new\n", pre_exists=True, pre_sha=old_sha)

    def boom(checkpoint):
        if checkpoint.startswith("post_action:0"):
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    with pytest.raises(RuntimeError):
        Transaction(seshat_dir, fake_home).apply([a], State())
    assert dest.read_bytes() == b"old\n"
    assert oct(os.stat(dest).st_mode & 0o7777) == "0o600"
    assert state_mod.load_state(seshat_dir).targets == {}


@pytest.mark.parametrize(
    "checkpoint",
    ["pre_action:0", "post_action:0", "pre_action:1", "pre_state_write", "post_state_write"],
)
def test_fault_injection_full_rollback(tmp_path, fake_home, seshat_dir, monkeypatch, checkpoint):
    d1 = fake_home / ".one"
    d2 = fake_home / ".sub" / "two"
    a1 = _write_action(tmp_path, d1, data=b"one\n", name="p1")
    a2 = _write_action(tmp_path, d2, data=b"two\n", name="p2")

    def boom(cp):
        if cp.startswith(checkpoint):
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    with pytest.raises(RuntimeError):
        Transaction(seshat_dir, fake_home).apply([a1, a2], State())
    if checkpoint == "post_state_write":
        return
    assert not d1.exists()
    assert not d2.exists()
    assert not (fake_home / ".sub").exists()
    assert state_mod.load_state(seshat_dir).targets == {}


def test_state_write_rolled_back(tmp_path, fake_home, seshat_dir, monkeypatch):
    original = State()
    original.bundles["default"] = {"installed_commit": "orig"}
    state_mod.write_state(original, seshat_dir)
    dest = fake_home / ".one"
    a = _write_action(tmp_path, dest)
    new_state = State()
    new_state.bundles["default"] = {"installed_commit": "new"}

    def boom(cp):
        if cp == "post_state_write":
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    with pytest.raises(RuntimeError):
        Transaction(seshat_dir, fake_home).apply([a], new_state)
    assert state_mod.load_state(seshat_dir).bundles["default"]["installed_commit"] == "orig"
    assert not dest.exists()


def test_replace_failure_mid_transaction(tmp_path, fake_home, seshat_dir, monkeypatch):
    d1 = fake_home / ".one"
    d2 = fake_home / ".two"
    d2.write_bytes(b"keep\n")
    a1 = _write_action(tmp_path, d1, data=b"one\n", name="p1")
    a2 = _write_action(tmp_path, d2, data=b"changed\n", name="p2", pre_exists=True, pre_sha=sha256_file(d2))
    calls = {"n": 0}
    real_replace = os.replace

    def flaky(src, dst):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("disk exploded")
        return real_replace(src, dst)

    monkeypatch.setattr(installer, "_replace", flaky)
    with pytest.raises(OSError):
        Transaction(seshat_dir, fake_home).apply([a1, a2], State())
    monkeypatch.setattr(installer, "_replace", real_replace)
    assert not d1.exists()
    assert d2.read_bytes() == b"keep\n"


def test_toctou_mutation_detected(tmp_path, fake_home, seshat_dir, monkeypatch):
    dest = fake_home / ".rc"
    dest.write_bytes(b"planned\n")
    a = _write_action(tmp_path, dest, data=b"new\n", pre_exists=True, pre_sha=sha256_file(dest))
    dest.write_bytes(b"mutated after planning\n")
    with pytest.raises(TransactionError):
        Transaction(seshat_dir, fake_home).apply([a], State())
    assert dest.read_bytes() == b"mutated after planning\n"


def test_toctou_appearance_detected(tmp_path, fake_home, seshat_dir):
    dest = fake_home / ".rc"
    a = _write_action(tmp_path, dest, data=b"new\n", pre_exists=False)
    dest.write_bytes(b"surprise\n")
    with pytest.raises(TransactionError):
        Transaction(seshat_dir, fake_home).apply([a], State())
    assert dest.read_bytes() == b"surprise\n"


def test_crash_recovery_completes_rollback(tmp_path, fake_home, seshat_dir, monkeypatch):
    dest = fake_home / ".one"
    a = _write_action(tmp_path, dest)

    class Crash(BaseException):
        pass

    def boom(cp):
        if cp.startswith("post_action:0"):
            raise Crash()

    monkeypatch.setattr(installer, "fault_hook", boom)
    real_rollback = installer._rollback_from_dir
    monkeypatch.setattr(installer, "_rollback_from_dir", lambda tdir: (_ for _ in ()).throw(Crash()))
    txn = Transaction(seshat_dir, fake_home)
    with pytest.raises(Crash):
        txn.apply([a], State())
    monkeypatch.setattr(installer, "_rollback_from_dir", real_rollback)
    monkeypatch.setattr(installer, "fault_hook", lambda cp: None)
    assert dest.exists()
    journal = yaml.safe_load((txn.dir / "journal.yml").read_text())
    assert journal["status"] in ("running", "rolling_back")
    recovered = recover(seshat_dir)
    assert recovered == [txn.id]
    assert not dest.exists()
    assert not txn.dir.exists()


def test_incomplete_rollback_blocks_and_recovers(tmp_path, fake_home, seshat_dir, monkeypatch):
    dest = fake_home / ".rc"
    dest.write_bytes(b"old\n")
    a = _write_action(tmp_path, dest, data=b"new\n", pre_exists=True, pre_sha=sha256_file(dest))

    def boom(cp):
        if cp == "pre_state_write":
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    real_undo = installer._undo_entry

    def failing_undo(tdir, entry):
        raise OSError("undo broken")

    monkeypatch.setattr(installer, "_undo_entry", failing_undo)
    txn = Transaction(seshat_dir, fake_home)
    with pytest.raises(RecoveryError):
        txn.apply([a], State())
    journal = yaml.safe_load((txn.dir / "journal.yml").read_text())
    assert journal["status"] == "rollback_incomplete"
    monkeypatch.setattr(installer, "fault_hook", lambda cp: None)
    with pytest.raises(RecoveryError):
        recover(seshat_dir)
    monkeypatch.setattr(installer, "_undo_entry", real_undo)
    recover(seshat_dir)
    assert dest.read_bytes() == b"old\n"
    assert not txn.dir.exists()


def test_write_json_preserves_unmanaged_keys(fake_home, seshat_dir):
    dest = fake_home / ".claude" / "settings.json"
    dest.parent.mkdir()
    dest.write_text(json.dumps({"permissions": {"allow": ["x"]}, "statusLine": "old"}, indent=2))
    value = {"type": "command", "command": "~/.claude/statusline.sh"}
    a = Action(
        kind="write_json",
        dest=str(dest),
        target_id="claude.settings.statusline",
        owner="default",
        pre_exists=True,
        pre_sha=sha256_file(dest),
        json_set={"statusLine": value},
        key_hashes={"statusLine": canonical_value_hash(value)},
    )
    Transaction(seshat_dir, fake_home).apply([a], State())
    doc = json.loads(dest.read_text())
    assert doc["permissions"] == {"allow": ["x"]}
    assert doc["statusLine"] == value
    assert dest.read_text().endswith("\n")


def test_write_json_rollback_restores_original(fake_home, seshat_dir, monkeypatch):
    dest = fake_home / "settings.json"
    original = json.dumps({"keep": 1, "mine": "old"}, indent=2)
    dest.write_text(original)
    a = Action(
        kind="write_json",
        dest=str(dest),
        target_id="x",
        owner="b",
        pre_exists=True,
        pre_sha=sha256_file(dest),
        json_set={"mine": "new"},
        key_hashes={"mine": canonical_value_hash("new")},
    )

    def boom(cp):
        if cp == "pre_state_write":
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    with pytest.raises(RuntimeError):
        Transaction(seshat_dir, fake_home).apply([a], State())
    assert dest.read_text() == original


def test_symlink_create_and_rollback(fake_home, seshat_dir, monkeypatch):
    dest = fake_home / ".bash_profile"
    old_target = str(fake_home / ".other")
    os.symlink(old_target, dest)
    a = Action(
        kind="symlink",
        dest=str(dest),
        target_id="shell.bash_profile",
        owner="default",
        pre_exists=True,
        pre_link_target=old_target,
        link_target=str(fake_home / ".bashrc"),
    )
    Transaction(seshat_dir, fake_home).apply([a], State())
    assert os.readlink(dest) == str(fake_home / ".bashrc")

    a2 = Action(
        kind="symlink",
        dest=str(dest),
        target_id="shell.bash_profile",
        owner="default",
        pre_exists=True,
        pre_link_target=str(fake_home / ".bashrc"),
        link_target=old_target,
    )

    def boom(cp):
        if cp == "pre_state_write":
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    with pytest.raises(RuntimeError):
        Transaction(seshat_dir, fake_home).apply([a2], State())
    assert os.readlink(dest) == str(fake_home / ".bashrc")


def test_remove_file_and_created_dirs(fake_home, seshat_dir):
    sub = fake_home / ".app" / "deep"
    sub.mkdir(parents=True)
    dest = sub / "conf"
    dest.write_bytes(b"bye\n")
    a = Action(
        kind="remove_file",
        dest=str(dest),
        target_id="x",
        owner="opt",
        pre_exists=True,
        pre_sha=sha256_file(dest),
        created_dirs=[str(fake_home / ".app"), str(sub)],
    )
    Transaction(seshat_dir, fake_home).apply([a], State())
    assert not dest.exists()
    assert not (fake_home / ".app").exists()


def test_remove_file_keeps_nonempty_dirs(fake_home, seshat_dir):
    sub = fake_home / ".app"
    sub.mkdir()
    dest = sub / "conf"
    dest.write_bytes(b"bye\n")
    (sub / "unrelated").write_bytes(b"stay\n")
    a = Action(
        kind="remove_file",
        dest=str(dest),
        target_id="x",
        owner="opt",
        pre_exists=True,
        pre_sha=sha256_file(dest),
        created_dirs=[str(sub)],
    )
    Transaction(seshat_dir, fake_home).apply([a], State())
    assert not dest.exists()
    assert (sub / "unrelated").exists()


def test_concurrent_lock(seshat_dir):
    from seshatlib.state import Lock, LockError

    l1 = Lock(seshat_dir).acquire()
    with pytest.raises(LockError):
        Lock(seshat_dir).acquire()
    l1.release()
