import json
import os

from seshatlib import state as state_mod
from tests.conftest import run_pipeline
from tests.test_planner import build_repo, state_of, write_bundle


def test_state_loss_full_adoption(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    mtimes = {
        p: os.lstat(p).st_mtime_ns
        for p in [fake_home / ".conf", fake_home / ".rc", fake_home / ".claude" / "settings.json"]
    }
    (work_repo / ".seshat" / "state.yml").unlink()
    (work_repo / ".seshat" / "state.yml.bak").unlink(missing_ok=True)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts, automatic=True)
    assert not plan.blocked
    assert all(a.kind in ("adopt", "noop") for a in plan.actions)
    for p, mtime in mtimes.items():
        assert os.lstat(p).st_mtime_ns == mtime
    st = state_of(work_repo)
    assert st.target(str(fake_home / ".conf"))["owner"] == "default"
    assert st.target(str(fake_home / ".rc_profile"))["type"] == "link"
    assert st.target(str(fake_home / ".claude/settings.json"))["keys"]["statusLine"]["owner"] == "default"


def test_state_loss_differing_file_blocked(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    (work_repo / ".seshat" / "state.yml").unlink()
    (work_repo / ".seshat" / "state.yml.bak").unlink(missing_ok=True)
    (fake_home / ".conf").write_text("drifted while unmanaged\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts, automatic=True)
    assert any(b.dest == str(fake_home / ".conf") for b in plan.blocked)
    assert (fake_home / ".conf").read_text() == "drifted while unmanaged\n"
    st = state_of(work_repo)
    assert st.target(str(fake_home / ".conf")) is None
    assert st.target(str(fake_home / ".rc"))["owner"] == "default"


def test_state_loss_json_keys_adopted_independently(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    settings = fake_home / ".claude" / "settings.json"
    doc = json.loads(settings.read_text())
    doc["userkey"] = "mine"
    settings.write_text(json.dumps(doc, indent=2) + "\n")
    (work_repo / ".seshat" / "state.yml").unlink()
    (work_repo / ".seshat" / "state.yml.bak").unlink(missing_ok=True)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts, automatic=True)
    assert not plan.blocked
    st = state_of(work_repo)
    keys = st.target(str(settings))["keys"]
    assert keys["statusLine"]["owner"] == "default"
    assert "userkey" not in keys
    assert json.loads(settings.read_text())["userkey"] == "mine"


def test_state_loss_optional_ownership_not_guessed(work_repo, fake_home, facts):
    build_repo(work_repo)
    (work_repo / "bedrock.json").write_text(json.dumps({"env": {"X": "1"}}))
    write_bundle(
        work_repo,
        "llm.bedrock",
        {
            "schema": 1,
            "name": "llm.bedrock",
            "depends_on": ["default"],
            "targets": [
                {
                    "id": "claude.settings.bedrock",
                    "operation": "json_merge",
                    "source": "bedrock.json",
                    "destination": "~/.claude/settings.json",
                    "owns": ["/env"],
                }
            ],
        },
    )
    run_pipeline(work_repo, fake_home, ["default"], facts)
    run_pipeline(work_repo, fake_home, ["llm.bedrock"], facts)
    (work_repo / ".seshat" / "state.yml").unlink()
    (work_repo / ".seshat" / "state.yml.bak").unlink(missing_ok=True)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts, automatic=True)
    assert not plan.blocked
    st = state_of(work_repo)
    keys = st.target(str(fake_home / ".claude/settings.json"))["keys"]
    assert keys["statusLine"]["owner"] == "default"
    assert "env" not in keys
    assert "llm.bedrock" not in st.bundles
    assert json.loads((fake_home / ".claude" / "settings.json").read_text())["env"] == {"X": "1"}


def test_adopted_symlink(work_repo, fake_home, facts):
    build_repo(work_repo)
    os.symlink(str(fake_home / ".rc"), fake_home / ".rc_profile")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    st = state_of(work_repo)
    assert st.target(str(fake_home / ".rc_profile"))["link_target"] == str(fake_home / ".rc")


def test_foreign_symlink_blocked(work_repo, fake_home, facts):
    build_repo(work_repo)
    os.symlink("/somewhere/else", fake_home / ".rc_profile")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert any(b.dest == str(fake_home / ".rc_profile") for b in plan.blocked)
    assert os.readlink(fake_home / ".rc_profile") == "/somewhere/else"
