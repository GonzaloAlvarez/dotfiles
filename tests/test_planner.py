import json
import os

import pytest
import yaml

from seshatlib import state as state_mod
from tests.conftest import run_pipeline, run_remove


def write_bundle(repo, name, doc):
    if name == "default":
        path = repo / "bundles" / "default.yml"
    else:
        path = repo / "bundles" / name / "bundle.yml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc))


def build_repo(work_repo):
    (work_repo / "payload").mkdir()
    (work_repo / "payload" / "conf").write_text("base config\n")
    (work_repo / "frag").mkdir()
    (work_repo / "frag" / "010a").write_text("first\n")
    (work_repo / "frag" / "005b").write_text("second\n")
    (work_repo / "claude.json").write_text(json.dumps({"statusLine": {"command": "x", "padding": 2}}))
    write_bundle(
        work_repo,
        "default",
        {
            "schema": 1,
            "name": "default",
            "automatic": True,
            "targets": [
                {"id": "app.conf", "operation": "copy", "source": "payload/conf", "destination": "~/.conf"},
                {"id": "app.rc", "operation": "combine", "source": "frag", "destination": "~/.rc"},
                {"id": "app.profile", "operation": "link", "target": "~/.rc", "destination": "~/.rc_profile"},
                {
                    "id": "claude.settings.statusline",
                    "operation": "json_merge",
                    "source": "claude.json",
                    "destination": "~/.claude/settings.json",
                    "owns": ["/statusLine"],
                },
            ],
        },
    )


def state_of(work_repo):
    return state_mod.load_state(work_repo / ".seshat")


def test_fresh_install(work_repo, fake_home, facts):
    build_repo(work_repo)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    assert (fake_home / ".conf").read_text() == "base config\n"
    assert (fake_home / ".rc").read_text() == "second\n\nfirst\n\n"
    assert os.readlink(fake_home / ".rc_profile") == str(fake_home / ".rc")
    doc = json.loads((fake_home / ".claude" / "settings.json").read_text())
    assert doc["statusLine"]["padding"] == 2
    st = state_of(work_repo)
    assert st.target(str(fake_home / ".conf"))["owner"] == "default"
    assert st.target(str(fake_home / ".claude/settings.json"))["keys"]["statusLine"]["owner"] == "default"
    assert "default" in st.bundles


def test_idempotent_second_run(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    before = {p: (os.lstat(p).st_mtime_ns) for p in [fake_home / ".conf", fake_home / ".rc"]}
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert plan.actions == []
    assert plan.changes == []
    assert not plan.blocked
    for p, mtime in before.items():
        assert os.lstat(p).st_mtime_ns == mtime


def test_source_change_updates(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    (work_repo / "payload" / "conf").write_text("v2 config\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert [c.kind for c in plan.changes] == ["update"]
    assert (fake_home / ".conf").read_text() == "v2 config\n"


def test_modified_file_blocked(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    (fake_home / ".conf").write_text("my local tweak\n")
    (work_repo / "payload" / "conf").write_text("v2 config\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert any(b.reason.startswith("locally modified") for b in plan.blocked)
    assert (fake_home / ".conf").read_text() == "my local tweak\n"


def test_unmanaged_conflict_blocked(work_repo, fake_home, facts):
    build_repo(work_repo)
    (fake_home / ".conf").write_text("someone else's file\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert any("unmanaged" in b.reason for b in plan.blocked)
    assert (fake_home / ".conf").read_text() == "someone else's file\n"
    st = state_of(work_repo)
    assert st.target(str(fake_home / ".conf")) is None
    assert (fake_home / ".rc").exists()


def test_adoption_of_exact_match(work_repo, fake_home, facts):
    build_repo(work_repo)
    (fake_home / ".conf").write_text("base config\n")
    mtime = os.lstat(fake_home / ".conf").st_mtime_ns
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    adopt = [c for c in plan.changes if c.kind == "adopt" and c.dest == str(fake_home / ".conf")]
    assert adopt
    assert os.lstat(fake_home / ".conf").st_mtime_ns == mtime
    assert state_of(work_repo).target(str(fake_home / ".conf"))["owner"] == "default"


def test_json_preserves_unmanaged_and_other_owner(work_repo, fake_home, facts):
    build_repo(work_repo)
    (work_repo / "bedrock.json").write_text(
        json.dumps({"env": {"CLAUDE_CODE_USE_BEDROCK": "1", "AWS_PROFILE": "bedrock"}})
    )
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
    settings = fake_home / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"allow": ["Bash"]}}, indent=2))

    run_pipeline(work_repo, fake_home, ["default"], facts)
    run_pipeline(work_repo, fake_home, ["llm.bedrock"], facts)
    doc = json.loads(settings.read_text())
    assert doc["permissions"] == {"allow": ["Bash"]}
    assert doc["env"]["AWS_PROFILE"] == "bedrock"
    assert doc["statusLine"]["padding"] == 2

    (work_repo / "claude.json").write_text(
        json.dumps({"statusLine": {"command": "x", "padding": 4}})
    )
    env_before = doc["env"]
    plan = run_pipeline(work_repo, fake_home, ["default"], facts, automatic=True)
    assert not plan.blocked
    doc = json.loads(settings.read_text())
    assert doc["statusLine"]["padding"] == 4
    assert doc["env"] == env_before
    assert doc["permissions"] == {"allow": ["Bash"]}
    st = state_of(work_repo)
    keys = st.target(str(settings))["keys"]
    assert keys["statusLine"]["owner"] == "default"
    assert keys["env"]["owner"] == "llm.bedrock"


def test_optional_cannot_steal_without_replaces(work_repo, fake_home, facts):
    from seshatlib.manifest import ManifestError

    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    (work_repo / "alt").mkdir()
    (work_repo / "alt" / "conf").write_text("optional version\n")
    write_bundle(
        work_repo,
        "opt",
        {
            "schema": 1,
            "name": "opt",
            "depends_on": ["default"],
            "targets": [
                {"id": "opt.conf", "operation": "copy", "source": "alt/conf", "destination": "~/.conf"}
            ],
        },
    )
    with pytest.raises(ManifestError, match="claimed by both"):
        run_pipeline(work_repo, fake_home, ["opt"], facts)
    assert (fake_home / ".conf").read_text() == "base config\n"


def test_replace_default_lifecycle(work_repo, fake_home, facts):
    build_repo(work_repo)
    (work_repo / "alt").mkdir()
    (work_repo / "alt" / "conf").write_text("optional version\n")
    write_bundle(
        work_repo,
        "opt",
        {
            "schema": 1,
            "name": "opt",
            "depends_on": ["default"],
            "targets": [
                {
                    "id": "opt.conf",
                    "operation": "copy",
                    "source": "alt/conf",
                    "destination": "~/.conf",
                    "replaces": ["default"],
                }
            ],
        },
    )
    run_pipeline(work_repo, fake_home, ["default"], facts)
    plan = run_pipeline(work_repo, fake_home, ["opt"], facts)
    assert not plan.blocked
    assert (fake_home / ".conf").read_text() == "optional version\n"
    st = state_of(work_repo)
    rec = st.target(str(fake_home / ".conf"))
    assert rec["owner"] == "opt"
    assert rec["replaced_default"]["target_id"] == "app.conf"

    (work_repo / "payload" / "conf").write_text("default v2\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts, automatic=True)
    assert not plan.blocked
    skipped = [s for s in plan.skipped if s.dest == str(fake_home / ".conf")]
    assert skipped and "owned by opt" in skipped[0].reason
    assert (fake_home / ".conf").read_text() == "optional version\n"

    plan = run_remove(work_repo, fake_home, "opt", facts)
    assert not plan.blocked
    assert (fake_home / ".conf").read_text() == "default v2\n"
    st = state_of(work_repo)
    rec = st.target(str(fake_home / ".conf"))
    assert rec["owner"] == "default"
    assert "opt" not in st.bundles


def test_remove_refuses_modified(work_repo, fake_home, facts):
    build_repo(work_repo)
    (work_repo / "extra.json").write_text(json.dumps({"mykey": "value"}))
    write_bundle(
        work_repo,
        "opt",
        {
            "schema": 1,
            "name": "opt",
            "depends_on": ["default"],
            "targets": [
                {
                    "id": "opt.settings",
                    "operation": "json_merge",
                    "source": "extra.json",
                    "destination": "~/.claude/settings.json",
                    "owns": ["/mykey"],
                }
            ],
        },
    )
    run_pipeline(work_repo, fake_home, ["default"], facts)
    run_pipeline(work_repo, fake_home, ["opt"], facts)
    settings = fake_home / ".claude" / "settings.json"
    doc = json.loads(settings.read_text())
    doc["mykey"] = "user changed this"
    settings.write_text(json.dumps(doc, indent=2))
    plan = run_remove(work_repo, fake_home, "opt", facts)
    assert plan.blocked
    doc = json.loads(settings.read_text())
    assert doc["mykey"] == "user changed this"
    assert "opt" in state_of(work_repo).bundles


def test_remove_json_key_preserves_others(work_repo, fake_home, facts):
    build_repo(work_repo)
    (work_repo / "extra.json").write_text(json.dumps({"mykey": {"a": 1}}))
    write_bundle(
        work_repo,
        "opt",
        {
            "schema": 1,
            "name": "opt",
            "depends_on": ["default"],
            "targets": [
                {
                    "id": "opt.settings",
                    "operation": "json_merge",
                    "source": "extra.json",
                    "destination": "~/.claude/settings.json",
                    "owns": ["/mykey"],
                }
            ],
        },
    )
    settings = fake_home / ".claude" / "settings.json"
    settings.parent.mkdir()
    settings.write_text(json.dumps({"permissions": {"deny": []}}, indent=2))
    run_pipeline(work_repo, fake_home, ["default"], facts)
    run_pipeline(work_repo, fake_home, ["opt"], facts)
    plan = run_remove(work_repo, fake_home, "opt", facts)
    assert not plan.blocked
    doc = json.loads(settings.read_text())
    assert "mykey" not in doc
    assert doc["permissions"] == {"deny": []}
    assert doc["statusLine"]["padding"] == 2
    st = state_of(work_repo)
    assert "opt" not in st.bundles
    assert "mykey" not in st.target(str(settings))["keys"]


def test_remove_default_refused(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    from seshatlib.planner import PlanError

    with pytest.raises(PlanError):
        run_remove(work_repo, fake_home, "default", facts)


def test_remove_not_installed_refused(work_repo, fake_home, facts):
    build_repo(work_repo)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    from seshatlib.planner import PlanError

    with pytest.raises(PlanError):
        run_remove(work_repo, fake_home, "ghost", facts)


def test_remove_deletes_optional_file_and_created_dirs(work_repo, fake_home, facts):
    build_repo(work_repo)
    (work_repo / "opt-payload").mkdir()
    (work_repo / "opt-payload" / "cfg").write_text("optional only\n")
    write_bundle(
        work_repo,
        "opt",
        {
            "schema": 1,
            "name": "opt",
            "depends_on": ["default"],
            "targets": [
                {
                    "id": "opt.cfg",
                    "operation": "copy",
                    "source": "opt-payload/cfg",
                    "destination": "~/.optapp/deep/cfg",
                }
            ],
        },
    )
    run_pipeline(work_repo, fake_home, ["default"], facts)
    run_pipeline(work_repo, fake_home, ["opt"], facts)
    assert (fake_home / ".optapp" / "deep" / "cfg").exists()
    plan = run_remove(work_repo, fake_home, "opt", facts)
    assert not plan.blocked
    assert not (fake_home / ".optapp").exists()


def test_mode_change_only_chmods(work_repo, fake_home, facts):
    build_repo(work_repo)
    (fake_home / ".conf").write_text("base config\n")
    os.chmod(fake_home / ".conf", 0o600)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    assert oct(os.stat(fake_home / ".conf").st_mode & 0o7777) == "0o644"
    chmods = [c for c in plan.changes if c.kind == "chmod"]
    assert chmods
