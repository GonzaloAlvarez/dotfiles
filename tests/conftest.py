import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


@pytest.fixture
def fake_home(tmp_path):
    home = tmp_path / "home"
    home.mkdir()
    return Path(os.path.realpath(home))


@pytest.fixture
def work_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


@pytest.fixture
def seshat_dir(work_repo):
    from seshatlib import state as state_mod

    return state_mod.ensure_seshat_dir(work_repo / ".seshat")


@pytest.fixture
def facts():
    from seshatlib.manifest import Facts

    return Facts(os="darwin", arch="arm64", user="galvarez", hostname="testbox")


@pytest.fixture
def fake_kauket(tmp_path, monkeypatch):
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    log = bindir / "kauket.log"
    fail_flag = bindir / "kauket.fail"
    script = bindir / "kauket"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{log}"\n'
        f'if [ -e "{fail_flag}" ]; then echo "boom" >&2; exit 3; fi\n'
        "exit 0\n"
    )
    script.chmod(0o755)
    monkeypatch.setenv("SESHAT_KAUKET", str(script))
    claude_stub = bindir / "claude"
    claude_stub.write_text("#!/bin/sh\nexit 0\n")
    claude_stub.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")
    return {"script": script, "log": log, "fail_flag": fail_flag, "bindir": bindir}


def run_pipeline(work_repo, fake_home, bundle_names, facts, variables=None, automatic=False):
    from seshatlib import installer, manifest, planner
    from seshatlib import state as state_mod

    bundles = manifest.load_bundles(work_repo)
    manifest.check_overlaps(bundles, facts)
    seshat_dir = state_mod.ensure_seshat_dir(work_repo / ".seshat")
    st = state_mod.load_state(seshat_dir)
    order = []
    for name in bundle_names:
        for dep in manifest.resolve_order(bundles, name):
            if dep not in order and (dep in bundle_names or dep not in st.bundles):
                order.append(dep)
    staged, staged_order = installer.stage(
        work_repo,
        [bundles[n] for n in order],
        facts,
        variables or {},
        seshat_dir / "staging" / "current",
        fake_home,
        "commit0",
    )
    plan = planner.plan_install(
        work_repo, bundles, order, staged, staged_order, st, facts, fake_home,
        automatic, "commit0", variables or {},
    )
    if plan.actions or plan.new_state.data != st.data:
        installer.Transaction(seshat_dir, fake_home).apply(plan.actions, plan.new_state)
    return plan


def run_remove(work_repo, fake_home, bundle_name, facts, variables=None):
    from seshatlib import installer, manifest, planner
    from seshatlib import state as state_mod

    bundles = manifest.load_bundles(work_repo)
    seshat_dir = state_mod.ensure_seshat_dir(work_repo / ".seshat")
    st = state_mod.load_state(seshat_dir)
    staged_default = {}
    if "default" in bundles:
        staged_default, _ = installer.stage(
            work_repo,
            [bundles["default"]],
            facts,
            variables or {},
            seshat_dir / "staging" / "remove",
            fake_home,
            "commit0",
        )
    plan = planner.plan_remove(work_repo, bundles, bundle_name, st, staged_default, facts, fake_home)
    if not plan.blocked and (plan.actions or plan.new_state.data != st.data):
        installer.Transaction(seshat_dir, fake_home).apply(plan.actions, plan.new_state)
    return plan


def make_git_origin(path, files, branch="master"):
    path = Path(path)
    path.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )

    def git(*args):
        subprocess.run(["git", "-C", str(path)] + list(args), check=True, env=env, capture_output=True)

    subprocess.run(["git", "init", "-q", "-b", branch, str(path)], check=True, env=env, capture_output=True)
    for rel, content in files.items():
        f = path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(content)
    git("add", "-A")
    git("commit", "-q", "-m", "init")
    return path


def commit_change(origin, rel, content, message="update"):
    origin = Path(origin)
    (origin / rel).write_text(content)
    env = dict(os.environ)
    env.update(
        {
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }
    )
    subprocess.run(["git", "-C", str(origin), "add", "-A"], check=True, env=env, capture_output=True)
    subprocess.run(
        ["git", "-C", str(origin), "commit", "-q", "-m", message],
        check=True,
        env=env,
        capture_output=True,
    )
