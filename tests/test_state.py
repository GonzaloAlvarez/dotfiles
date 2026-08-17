import os

import pytest

from seshatlib import state as state_mod
from seshatlib.state import Lock, LockError, State, StateError


def test_empty_state_roundtrip(seshat_dir):
    st = state_mod.load_state(seshat_dir)
    assert st.bundles == {}
    assert st.targets == {}
    state_mod.write_state(st, seshat_dir)
    again = state_mod.load_state(seshat_dir)
    assert again.data == st.data


def test_state_persists_records(seshat_dir):
    st = State()
    st.bundles["default"] = {"installed_commit": "abc", "source_digest": "sha256:x"}
    st.targets["/home/x/.bashrc"] = {"type": "file", "owner": "default", "target_id": "shell.bashrc"}
    state_mod.write_state(st, seshat_dir)
    again = state_mod.load_state(seshat_dir)
    assert again.bundles["default"]["installed_commit"] == "abc"
    assert again.target("/home/x/.bashrc")["owner"] == "default"
    assert oct(os.stat(seshat_dir / "state.yml").st_mode & 0o777) == "0o600"


def test_state_backup_used_when_corrupt(seshat_dir):
    st = State()
    st.bundles["default"] = {"installed_commit": "abc"}
    state_mod.write_state(st, seshat_dir)
    st.bundles["default"]["installed_commit"] = "def"
    state_mod.write_state(st, seshat_dir)
    (seshat_dir / "state.yml").write_text("{ not: valid: yaml: [")
    recovered = state_mod.load_state(seshat_dir)
    assert recovered.bundles["default"]["installed_commit"] == "abc"


def test_state_error_when_both_corrupt(seshat_dir):
    (seshat_dir / "state.yml").write_text("{ not: valid: yaml: [")
    (seshat_dir / "state.yml.bak").write_text("{ also: bad: [")
    with pytest.raises(StateError):
        state_mod.load_state(seshat_dir)


def test_bad_schema_rejected(seshat_dir):
    (seshat_dir / "state.yml").write_text("schema: 99\nbundles: {}\ntargets: {}\n")
    with pytest.raises(StateError):
        state_mod.load_state(seshat_dir)


def test_lock_excludes_second_holder(seshat_dir):
    with Lock(seshat_dir):
        with pytest.raises(LockError):
            Lock(seshat_dir).acquire()
    Lock(seshat_dir).acquire().release()


def test_stale_lock_recovered(seshat_dir):
    (seshat_dir / "lock").write_text("999999")
    lock = Lock(seshat_dir).acquire()
    assert lock.acquired
    lock.release()


def test_targets_owned_by(seshat_dir):
    st = State()
    st.targets["/h/.bashrc"] = {"type": "file", "owner": "default", "target_id": "a"}
    st.targets["/h/.claude/settings.json"] = {
        "type": "json",
        "keys": {
            "statusLine": {"owner": "default", "target_id": "b"},
            "env": {"owner": "llm.claude.bedrock", "target_id": "c"},
        },
    }
    owned = st.targets_owned_by("llm.claude.bedrock")
    assert list(owned) == ["/h/.claude/settings.json"]
    assert list(owned["/h/.claude/settings.json"]["keys"]) == ["env"]
    owned_default = st.targets_owned_by("default")
    assert set(owned_default) == {"/h/.bashrc", "/h/.claude/settings.json"}
