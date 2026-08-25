import subprocess

from seshatlib import legacy
from tests.conftest import commit_change, make_git_origin


def make_history_repo(tmp_path):
    """A dotfiles-shaped repo: v1 payloads, then drifted v2 payloads at HEAD."""
    repo = make_git_origin(
        tmp_path / "dotrepo",
        {
            "bashrc/000Header.sh": "#!/bin/bash\n",
            "bashrc/300Variables.sh": "export V=1\n",
            "claude/statusline.sh": "#!/bin/bash\necho v1\n",
            "nvim/init.lua": "-- v1\n",
        },
    )
    commit_change(repo, "bashrc/300Variables.sh", "export V=2\n")
    commit_change(repo, "claude/statusline.sh", "#!/usr/bin/env bash\necho v2\n")
    commit_change(repo, "nvim/init.lua", "-- v2\n")
    return repo


def old_combine(*fragments):
    return "".join(f + "\n" for f in fragments)


V1_BASHRC = old_combine("#!/bin/bash\n", "export V=1\n")
V2_BASHRC = old_combine("#!/bin/bash\n", "export V=2\n")


def test_reaps_drifted_combine_output(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    (fake_home / ".bashrc").write_text(V1_BASHRC)
    removed = legacy.reap(repo, fake_home)
    assert removed == [fake_home / ".bashrc"]
    assert not (fake_home / ".bashrc").exists()


def test_leaves_combine_output_matching_head(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    (fake_home / ".bashrc").write_text(V2_BASHRC)
    assert legacy.reap(repo, fake_home) == []
    assert (fake_home / ".bashrc").exists()


def test_leaves_user_modified_file(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    (fake_home / ".bashrc").write_text(V1_BASHRC + "alias mine='ls'\n")
    assert legacy.reap(repo, fake_home) == []
    assert (fake_home / ".bashrc").exists()


def test_leaves_symlink(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    real = fake_home / "real_bashrc"
    real.write_text(V1_BASHRC)
    (fake_home / ".bashrc").symlink_to(real)
    assert legacy.reap(repo, fake_home) == []
    assert (fake_home / ".bashrc").is_symlink()


def test_reaps_drifted_copy_output(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    (fake_home / ".claude").mkdir()
    (fake_home / ".claude/statusline.sh").write_text("#!/bin/bash\necho v1\n")
    removed = legacy.reap(repo, fake_home)
    assert removed == [fake_home / ".claude/statusline.sh"]


def test_reaps_legacy_nvim_dir(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    nvim = fake_home / ".config/nvim"
    nvim.mkdir(parents=True)
    (nvim / "init.lua").write_text("-- v1\n")
    removed = legacy.reap(repo, fake_home)
    assert removed == [nvim]
    assert not nvim.exists()


def test_reaps_nvim_dir_even_at_current_content(tmp_path, fake_home):
    # a plain dir blocks git_tree regardless of content, so current also reaps
    repo = make_history_repo(tmp_path)
    nvim = fake_home / ".config/nvim"
    nvim.mkdir(parents=True)
    (nvim / "init.lua").write_text("-- v2\n")
    assert legacy.reap(repo, fake_home) == [nvim]


def test_leaves_nvim_dir_with_foreign_file(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    nvim = fake_home / ".config/nvim"
    nvim.mkdir(parents=True)
    (nvim / "init.lua").write_text("-- v1\n")
    (nvim / "notes.txt").write_text("mine\n")
    assert legacy.reap(repo, fake_home) == []
    assert (nvim / "init.lua").exists()


def test_leaves_nvim_dir_with_subdir(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    nvim = fake_home / ".config/nvim"
    (nvim / "lua").mkdir(parents=True)
    (nvim / "init.lua").write_text("-- v1\n")
    assert legacy.reap(repo, fake_home) == []


def test_leaves_nvim_git_repo(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    nvim = fake_home / ".config/nvim"
    nvim.mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(nvim)], check=True, capture_output=True)
    (nvim / "init.lua").write_text("-- v1\n")
    assert legacy.reap(repo, fake_home) == []
    assert nvim.exists()


def test_noop_when_repo_is_not_git(tmp_path, fake_home):
    repo = tmp_path / "plain"
    repo.mkdir()
    (fake_home / ".bashrc").write_text(V1_BASHRC)
    assert legacy.reap(repo, fake_home) == []
    assert (fake_home / ".bashrc").exists()


def test_noop_on_empty_home(tmp_path, fake_home):
    repo = make_history_repo(tmp_path)
    assert legacy.reap(repo, fake_home) == []


def test_main_prints_reaped_paths(tmp_path, fake_home, monkeypatch, capsys):
    repo = make_history_repo(tmp_path)
    (fake_home / ".bashrc").write_text(V1_BASHRC)
    monkeypatch.setenv("HOME", str(fake_home))
    assert legacy.main(["legacy.py", str(repo)]) == 0
    out = capsys.readouterr().out
    assert "reap-legacy" in out and ".bashrc" in out
    assert not (fake_home / ".bashrc").exists()
