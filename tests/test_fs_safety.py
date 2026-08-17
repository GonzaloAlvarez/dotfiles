import os

import pytest

from seshatlib.installer import SafetyError, resolve_link_target, safe_dest_path
from seshatlib.manifest import ManifestError, repo_source_path


def test_traversal_rejected(fake_home):
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~/../evil", "copy")


def test_outside_home_rejected(fake_home):
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "/etc/passwd", "copy")


def test_home_itself_rejected(fake_home):
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~", "copy")


def test_nul_rejected(fake_home):
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~/.x\0y", "copy")


def test_relative_rejected(fake_home):
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, ".bashrc", "copy")


def test_symlink_ancestor_rejected(fake_home, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    os.symlink(outside, fake_home / ".config")
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~/.config/nvim/init.lua", "copy")


def test_symlink_dest_rejected_for_copy(fake_home):
    os.symlink(fake_home / "real", fake_home / ".rc")
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~/.rc", "copy")


def test_symlink_dest_allowed_for_link(fake_home):
    os.symlink(fake_home / "real", fake_home / ".bash_profile")
    p = safe_dest_path(fake_home, "~/.bash_profile", "link")
    assert p == fake_home / ".bash_profile"


def test_directory_dest_rejected_for_copy(fake_home):
    (fake_home / ".vim").mkdir()
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~/.vim", "copy")


def test_directory_dest_allowed_for_git_tree(fake_home):
    (fake_home / ".vim").mkdir()
    assert safe_dest_path(fake_home, "~/.vim", "git_tree") == fake_home / ".vim"


def test_fifo_dest_rejected(fake_home):
    os.mkfifo(fake_home / ".pipe")
    with pytest.raises(SafetyError):
        safe_dest_path(fake_home, "~/.pipe", "copy")


def test_valid_paths_accepted(fake_home):
    p = safe_dest_path(fake_home, "~/.config/nvim/init.lua", "copy")
    assert p == fake_home / ".config" / "nvim" / "init.lua"
    p = safe_dest_path(fake_home, "~/Library/Application Support/Code/User/settings.json", "copy")
    assert str(p).endswith("settings.json")


def test_source_escape_rejected(work_repo):
    with pytest.raises(ManifestError):
        repo_source_path(work_repo, "../outside")
    with pytest.raises(ManifestError):
        repo_source_path(work_repo, "/etc/passwd")
    with pytest.raises(ManifestError):
        repo_source_path(work_repo, "~/x")


def test_source_valid(work_repo):
    p = repo_source_path(work_repo, "bashrc")
    assert str(p).endswith("bashrc")


def test_link_target_resolution(fake_home, work_repo):
    assert resolve_link_target("~/.bashrc", fake_home, work_repo) == str(fake_home / ".bashrc")
    assert resolve_link_target("repo:seshat", fake_home, work_repo) == str(
        (work_repo / "seshat").resolve()
    )
    with pytest.raises(Exception):
        resolve_link_target("relative/path", fake_home, work_repo)
    with pytest.raises(Exception):
        resolve_link_target("repo:../escape", fake_home, work_repo)
