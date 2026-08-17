import json

import pytest
import yaml

from tests.test_planner import build_repo, state_of, write_bundle


def run_cli(argv, repo, home, monkeypatch, facts_obj, capsys=None):
    from seshatlib import cli, manifest

    monkeypatch.setenv("SESHAT_REPO", str(repo))
    monkeypatch.setenv("SESHAT_HOME", str(home))
    monkeypatch.setattr(manifest, "gather_facts", lambda: facts_obj)
    return cli.main(argv)


def add_bedrock_bundle(work_repo):
    bdir = work_repo / "bundles" / "llm.claude.bedrock"
    (bdir / "files").mkdir(parents=True, exist_ok=True)
    (bdir / "files" / "bedrock-env.json.j2").write_text(
        '{\n'
        '  "env": {\n'
        '    "CLAUDE_CODE_USE_BEDROCK": "1",\n'
        '    "AWS_PROFILE": {{ vars.aws_profile | tojson }},\n'
        '    "AWS_REGION": {{ vars.aws_region | tojson }}\n'
        '  }\n'
        '}\n'
    )
    (bdir / "bundle.yml").write_text(
        yaml.safe_dump(
            {
                "schema": 1,
                "name": "llm.claude.bedrock",
                "description": "Claude via Bedrock",
                "automatic": False,
                "depends_on": ["default"],
                "requires": {
                    "commands": ["claude", "kauket"],
                    "kauket": [{"id": "aws.profile.bedrock", "action": "install"}],
                },
                "variables": {
                    "aws_profile": {"type": "string", "default": "bedrock"},
                    "aws_region": {"type": "string", "default": "us-east-2"},
                },
                "targets": [
                    {
                        "id": "claude.settings.bedrock",
                        "operation": "json_merge",
                        "source": "bundles/llm.claude.bedrock/files/bedrock-env.json.j2",
                        "destination": "~/.claude/settings.json",
                        "template": "jinja2",
                        "owns": ["/env"],
                    }
                ],
            }
        )
    )


def test_install_default_and_rerun(work_repo, fake_home, facts, monkeypatch, capsys):
    build_repo(work_repo)
    assert run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 0
    assert (fake_home / ".conf").exists()
    assert run_cli(["install", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 0
    out = capsys.readouterr().out
    assert "nothing to do" in out


def test_install_unknown_bundle(work_repo, fake_home, facts, monkeypatch):
    build_repo(work_repo)
    assert run_cli(["install", "ghost"], work_repo, fake_home, monkeypatch, facts) == 1


def test_install_bedrock_full_flow(work_repo, fake_home, facts, monkeypatch, fake_kauket, capsys):
    build_repo(work_repo)
    add_bedrock_bundle(work_repo)
    assert run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 0
    assert (
        run_cli(
            ["install", "llm.claude.bedrock", "--yes", "--set", "aws_region=eu-west-1"],
            work_repo,
            fake_home,
            monkeypatch,
            facts,
        )
        == 0
    )
    assert fake_kauket["log"].read_text().strip() == "get aws.profile.bedrock"
    doc = json.loads((fake_home / ".claude" / "settings.json").read_text())
    assert doc["env"]["AWS_REGION"] == "eu-west-1"
    assert doc["env"]["AWS_PROFILE"] == "bedrock"
    assert doc["statusLine"]["padding"] == 2
    st = state_of(work_repo)
    assert st.bundles["llm.claude.bedrock"]["variables"]["aws_region"] == "eu-west-1"

    (work_repo / "claude.json").write_text(
        json.dumps({"statusLine": {"command": "x", "padding": 9}})
    )
    assert run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 0
    doc = json.loads((fake_home / ".claude" / "settings.json").read_text())
    assert doc["statusLine"]["padding"] == 9
    assert doc["env"]["AWS_REGION"] == "eu-west-1"
    assert fake_kauket["log"].read_text().strip() == "get aws.profile.bedrock"


def test_install_bedrock_missing_command(work_repo, fake_home, facts, monkeypatch):
    build_repo(work_repo)
    add_bedrock_bundle(work_repo)
    monkeypatch.setenv("PATH", "/usr/bin:/bin")
    monkeypatch.delenv("SESHAT_KAUKET", raising=False)
    assert run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 0
    assert run_cli(["install", "llm.claude.bedrock", "--yes"], work_repo, fake_home, monkeypatch, facts) == 1
    assert "env" not in json.loads((fake_home / ".claude" / "settings.json").read_text())


def test_automatic_blocked_exit_code(work_repo, fake_home, facts, monkeypatch):
    build_repo(work_repo)
    assert run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 0
    (fake_home / ".conf").write_text("local change\n")
    (work_repo / "payload" / "conf").write_text("upstream change\n")
    assert run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts) == 2
    assert (fake_home / ".conf").read_text() == "local change\n"
    assert (fake_home / ".rc").exists()


def test_list_states(work_repo, fake_home, facts, monkeypatch, capsys):
    build_repo(work_repo)
    add_bedrock_bundle(work_repo)
    assert run_cli(["list"], work_repo, fake_home, monkeypatch, facts) == 0
    out = capsys.readouterr().out
    assert "not-installed" in out

    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    assert run_cli(["list"], work_repo, fake_home, monkeypatch, facts) == 0
    out = capsys.readouterr().out
    assert "current" in out

    (work_repo / "payload" / "conf").write_text("changed upstream\n")
    run_cli(["list"], work_repo, fake_home, monkeypatch, facts)
    out = capsys.readouterr().out
    assert "outdated" in out
    (work_repo / "payload" / "conf").write_text("base config\n")

    (fake_home / ".conf").write_text("local edit\n")
    run_cli(["list"], work_repo, fake_home, monkeypatch, facts)
    out = capsys.readouterr().out
    assert "modified" in out

    (fake_home / ".conf").unlink()
    run_cli(["list"], work_repo, fake_home, monkeypatch, facts)
    out = capsys.readouterr().out
    assert "missing" in out


def test_list_json_and_detail(work_repo, fake_home, facts, monkeypatch, capsys):
    build_repo(work_repo)
    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    capsys.readouterr()
    assert run_cli(["list", "--json"], work_repo, fake_home, monkeypatch, facts) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["result"]["ok"] is True
    default = [b for b in doc["result"]["bundles"] if b["name"] == "default"][0]
    assert default["state"] == "current"

    assert run_cli(["list", "default"], work_repo, fake_home, monkeypatch, facts) == 0
    out = capsys.readouterr().out
    assert "statusLine" in out
    assert str(fake_home / ".conf") in out


def test_list_shows_unmanaged_keys(work_repo, fake_home, facts, monkeypatch, capsys):
    build_repo(work_repo)
    settings = fake_home / ".claude"
    settings.mkdir()
    (settings / "settings.json").write_text(json.dumps({"permissions": {"allow": []}}))
    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    capsys.readouterr()
    run_cli(["list", "default"], work_repo, fake_home, monkeypatch, facts)
    out = capsys.readouterr().out
    assert "unmanaged" in out
    assert "permissions" in out


def test_list_orphaned_bundle(work_repo, fake_home, facts, monkeypatch, capsys):
    import shutil

    build_repo(work_repo)
    add_bedrock_bundle(work_repo)
    (work_repo / "bundles" / "llm.claude.bedrock" / "bundle.yml").exists()
    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    st_dir = work_repo / ".seshat"
    st = yaml.safe_load((st_dir / "state.yml").read_text())
    st["bundles"]["ghost.bundle"] = {"installed_commit": "x", "source_digest": "y"}
    (st_dir / "state.yml").write_text(yaml.safe_dump(st))
    run_cli(["list"], work_repo, fake_home, monkeypatch, facts)
    out = capsys.readouterr().out
    assert "orphaned" in out


def test_remove_bedrock(work_repo, fake_home, facts, monkeypatch, fake_kauket):
    build_repo(work_repo)
    add_bedrock_bundle(work_repo)
    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    run_cli(["install", "llm.claude.bedrock", "--yes"], work_repo, fake_home, monkeypatch, facts)
    settings = fake_home / ".claude" / "settings.json"
    assert "env" in json.loads(settings.read_text())
    assert run_cli(["remove", "llm.claude.bedrock", "--yes"], work_repo, fake_home, monkeypatch, facts) == 0
    doc = json.loads(settings.read_text())
    assert "env" not in doc
    assert "statusLine" in doc
    st = state_of(work_repo)
    assert "llm.claude.bedrock" not in st.bundles


def test_remove_default_refused(work_repo, fake_home, facts, monkeypatch):
    build_repo(work_repo)
    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    assert run_cli(["remove", "default", "--yes"], work_repo, fake_home, monkeypatch, facts) == 1


def test_remove_modified_key_exit_2(work_repo, fake_home, facts, monkeypatch, fake_kauket):
    build_repo(work_repo)
    add_bedrock_bundle(work_repo)
    run_cli(["install", "default", "--automatic"], work_repo, fake_home, monkeypatch, facts)
    run_cli(["install", "llm.claude.bedrock", "--yes"], work_repo, fake_home, monkeypatch, facts)
    settings = fake_home / ".claude" / "settings.json"
    doc = json.loads(settings.read_text())
    doc["env"]["AWS_REGION"] = "manually-changed"
    settings.write_text(json.dumps(doc, indent=2))
    assert run_cli(["remove", "llm.claude.bedrock", "--yes"], work_repo, fake_home, monkeypatch, facts) == 2
    assert json.loads(settings.read_text())["env"]["AWS_REGION"] == "manually-changed"


def test_set_unknown_variable_rejected(work_repo, fake_home, facts, monkeypatch):
    build_repo(work_repo)
    assert (
        run_cli(
            ["install", "default", "--yes", "--set", "nonexistent=1"],
            work_repo,
            fake_home,
            monkeypatch,
            facts,
        )
        == 1
    )


def test_version(capsys):
    from seshatlib import cli

    with pytest.raises(SystemExit) as exc:
        cli.main(["--version"])
    assert exc.value.code == 0
    assert "seshat" in capsys.readouterr().out


def test_no_command_shows_help(capsys):
    from seshatlib import cli

    assert cli.main([]) == 1
    assert "install" in capsys.readouterr().out
