import os
import subprocess

import pytest

from seshatlib import providers
from seshatlib.installer import TransactionError
from tests.conftest import commit_change, make_git_origin, run_pipeline
from tests.test_planner import state_of, write_bundle


@pytest.fixture
def origin(tmp_path):
    return make_git_origin(tmp_path / "origin-vim", {"vimrc": "set nu\n"})


def git_bundle(work_repo, origin):
    write_bundle(
        work_repo,
        "default",
        {
            "schema": 1,
            "name": "default",
            "automatic": True,
            "targets": [
                {"id": "vim.tree", "operation": "git_tree", "url": str(origin), "destination": "~/.vim"}
            ],
        },
    )


def test_clone_and_record(work_repo, fake_home, facts, origin):
    git_bundle(work_repo, origin)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    assert (fake_home / ".vim" / "vimrc").read_text() == "set nu\n"
    rec = state_of(work_repo).target(str(fake_home / ".vim"))
    assert rec["type"] == "git_tree"
    assert rec["installed_commit"] == providers.git_head(fake_home / ".vim")


def test_fast_forward_update(work_repo, fake_home, facts, origin):
    git_bundle(work_repo, origin)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    old_head = providers.git_head(fake_home / ".vim")
    commit_change(origin, "vimrc", "set nu\nset ai\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    new_head = providers.git_head(fake_home / ".vim")
    assert new_head != old_head
    assert (fake_home / ".vim" / "vimrc").read_text() == "set nu\nset ai\n"
    assert state_of(work_repo).target(str(fake_home / ".vim"))["installed_commit"] == new_head


def test_dirty_repo_blocked(work_repo, fake_home, facts, origin):
    git_bundle(work_repo, origin)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    (fake_home / ".vim" / "vimrc").write_text("local hack\n")
    commit_change(origin, "vimrc", "upstream change\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert any("uncommitted changes" in b.reason for b in plan.blocked)
    assert (fake_home / ".vim" / "vimrc").read_text() == "local hack\n"


def test_untracked_files_do_not_block(work_repo, fake_home, facts, origin):
    git_bundle(work_repo, origin)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    (fake_home / ".vim" / "lazy-lock.json").write_text("{}\n")
    commit_change(origin, "vimrc", "upstream change\n")
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    assert (fake_home / ".vim" / "vimrc").read_text() == "upstream change\n"
    assert (fake_home / ".vim" / "lazy-lock.json").exists()


def test_diverged_repo_fails_and_keeps_local(work_repo, fake_home, facts, origin):
    git_bundle(work_repo, origin)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    commit_change(fake_home / ".vim", "vimrc", "local commit\n")
    local_head = providers.git_head(fake_home / ".vim")
    commit_change(origin, "vimrc", "upstream commit\n")
    with pytest.raises(TransactionError, match="diverge"):
        run_pipeline(work_repo, fake_home, ["default"], facts)
    assert providers.git_head(fake_home / ".vim") == local_head
    assert (fake_home / ".vim" / "vimrc").read_text() == "local commit\n"


def test_wrong_origin_blocked(work_repo, fake_home, facts, origin, tmp_path):
    other = make_git_origin(tmp_path / "origin-other", {"x": "y\n"})
    subprocess.run(["git", "clone", "-q", str(other), str(fake_home / ".vim")], check=True)
    git_bundle(work_repo, origin)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert any("does not match" in b.reason for b in plan.blocked)


def test_non_git_directory_blocked(work_repo, fake_home, facts, origin):
    (fake_home / ".vim").mkdir()
    (fake_home / ".vim" / "junk").write_text("x")
    git_bundle(work_repo, origin)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert any("not a git repository" in b.reason for b in plan.blocked)
    assert (fake_home / ".vim" / "junk").exists()


def test_adopt_existing_clone(work_repo, fake_home, facts, origin):
    subprocess.run(["git", "clone", "-q", str(origin), str(fake_home / ".vim")], check=True)
    head = providers.git_head(fake_home / ".vim")
    git_bundle(work_repo, origin)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    rec = state_of(work_repo).target(str(fake_home / ".vim"))
    assert rec["owner"] == "default"
    assert rec["installed_commit"] == head


def test_fetch_failure_is_warning_not_error(work_repo, fake_home, facts, origin, tmp_path):
    import shutil

    git_bundle(work_repo, origin)
    run_pipeline(work_repo, fake_home, ["default"], facts)
    head = providers.git_head(fake_home / ".vim")
    shutil.rmtree(origin)
    plan = run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not plan.blocked
    assert providers.git_head(fake_home / ".vim") == head
    assert state_of(work_repo).target(str(fake_home / ".vim"))["installed_commit"] == head


def test_clone_rollback_removes_tree(work_repo, fake_home, facts, origin, monkeypatch):
    from seshatlib import installer

    git_bundle(work_repo, origin)

    def boom(cp):
        if cp == "pre_state_write":
            raise RuntimeError("injected")

    monkeypatch.setattr(installer, "fault_hook", boom)
    with pytest.raises(RuntimeError):
        run_pipeline(work_repo, fake_home, ["default"], facts)
    assert not (fake_home / ".vim").exists()
