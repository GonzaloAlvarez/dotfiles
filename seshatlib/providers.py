import os
import shutil
import subprocess


class ProviderError(Exception):
    pass


class GitError(Exception):
    pass


def missing_commands(cmds):
    return [c for c in cmds or [] if shutil.which(c) is None]


def kauket_binary():
    return os.environ.get("SESHAT_KAUKET", "kauket")


def run_kauket(prereqs):
    for p in prereqs or []:
        action = p.get("action")
        if action != "install":
            raise ProviderError(f"unsupported kauket action: {action!r}")
        secret_id = p.get("id")
        binary = kauket_binary()
        if shutil.which(binary) is None:
            raise ProviderError(f"kauket command not found; required to install {secret_id}")
        result = subprocess.run(
            [binary, "get", secret_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        if result.returncode != 0:
            detail = result.stderr.decode("utf-8", "replace").strip()[:500]
            raise ProviderError(f"kauket get {secret_id} failed (exit {result.returncode}): {detail}")


def _git(args, check=True):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    result = subprocess.run(
        ["git"] + [str(a) for a in args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if check and result.returncode != 0:
        raise GitError(
            f"git {' '.join(str(a) for a in args)} failed: "
            f"{result.stderr.decode('utf-8', 'replace').strip()}"
        )
    return result


def git_clone(url, dest, ref=None):
    args = ["clone", "--quiet"]
    if ref:
        args += ["--branch", ref]
    args += ["--", url, dest]
    _git(args)


def git_is_repo(dest):
    return _git(["-C", dest, "rev-parse", "--git-dir"], check=False).returncode == 0


def git_origin_url(dest):
    result = _git(["-C", dest, "remote", "get-url", "origin"], check=False)
    if result.returncode != 0:
        return None
    return result.stdout.decode("utf-8").strip()


def git_is_dirty(dest):
    result = _git(["-C", dest, "status", "--porcelain", "-uno"])
    return bool(result.stdout.strip())


def git_head(dest):
    return _git(["-C", dest, "rev-parse", "HEAD"]).stdout.decode("utf-8").strip()


def git_fetch_head(dest, ref=None):
    _git(["-C", dest, "fetch", "--quiet", "origin", ref or "HEAD"])
    return _git(["-C", dest, "rev-parse", "FETCH_HEAD"]).stdout.decode("utf-8").strip()


def git_is_ancestor(dest, ancestor, descendant):
    result = _git(["-C", dest, "merge-base", "--is-ancestor", ancestor, descendant], check=False)
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise GitError(f"git merge-base failed in {dest}")


def git_ff_to(dest, commit):
    _git(["-C", dest, "merge", "--ff-only", "--quiet", commit])


def git_reset_hard(dest, commit):
    _git(["-C", dest, "reset", "--hard", "--quiet", commit])


def same_origin(a, b):
    def norm(u):
        u = (u or "").strip().rstrip("/")
        if u.endswith(".git"):
            u = u[:-4]
        return u.lower()

    return norm(a) == norm(b)


def repo_head_commit(repo):
    result = _git(["-C", repo, "rev-parse", "HEAD"], check=False)
    if result.returncode != 0:
        return "unknown"
    return result.stdout.decode("utf-8").strip()
