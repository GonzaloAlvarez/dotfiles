"""Pre-Seshat legacy reaper.

Machines bootstrapped before the Seshat migration carry outputs of the old
config.json-driven ``setup`` (copy/combine/git modes). When such an output has
drifted from the current payload, Seshat correctly blocks it as an unmanaged
file (exit 2). This module removes a legacy output ONLY when it is
byte-identical to a rendering reconstructed from this repo's own git history
(provably untouched by the user) AND differs from the current rendering (when
it matches, Seshat adopts it on its own — nothing to do). Anything else is
left alone and still blocks — Seshat's safety intact.

Same principle as amun's stock /etc/skel cleanup, extended to the repo's own
historical pristine sources.

Standalone by design: stdlib only (no venv needed), invoked by ``./setup``
before the Seshat launcher. Requires git, which is guaranteed on any machine
amun cloned this repo onto. Always exits 0 — a machine the reaper cannot help
just proceeds to Seshat and blocks there, visibly.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

# The union of every dest the pre-Seshat config.json ever managed with
# copy/combine, keyed by HOME-relative dest. Combine sources are payload
# directories; copy sources list every path that ever fed the dest.
LEGACY_FILES = {
    ".bashrc": ("combine", ["bashrc"]),
    ".screenrc": ("combine", ["screenrc"]),
    ".tmux.conf": ("combine", ["tmux.conf"]),
    ".zshenv": ("combine", ["zshenv"]),
    ".ideavimrc": ("combine", ["ideavimrc"]),
    ".aider.conf.yml": ("copy", ["aider/aider.conf.yml", "aider/aider.openai.conf.yml"]),
    ".claude/statusline.sh": ("copy", ["claude/statusline.sh"]),
    "Library/Application Support/Code/User/settings.json": ("copy", ["vscode/settings.json"]),
    "Library/Application Support/Code/User/keybindings.json": ("copy", ["vscode/keybindings.json"]),
    "Library/Application Support/Code - Insiders/User/settings.json": ("copy", ["vscode/settings.json"]),
    "Library/Application Support/Code - Insiders/User/keybindings.json": ("copy", ["vscode/keybindings.json"]),
}

# Dests that are git_tree targets today but were plain-file copies before
# Seshat (old config: nvim/init.lua -> ~/.config/nvim/init.lua). The dir is
# reaped only when it is not a git repo and every entry is a regular file
# byte-identical to a historical blob of <payload>/<name>. Matching the
# CURRENT payload also reaps: a plain dir blocks git_tree no matter what.
LEGACY_GIT_DIRS = {
    ".config/nvim": "nvim",
}


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True)


def _git_bytes(repo, *args):
    proc = _git(repo, *args)
    return proc.stdout if proc.returncode == 0 else None


def _revs(repo, path):
    out = _git_bytes(repo, "rev-list", "HEAD", "--", path)
    return out.decode().split() if out else []


def _tree_files(repo, rev, dirpath):
    out = _git_bytes(repo, "ls-tree", "-z", rev, f"{dirpath.rstrip('/')}/")
    if out is None:
        return None
    names = []
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, name = entry.split(b"\t", 1)
        if meta.split()[1] == b"blob":
            names.append(name.decode())
    return sorted(names)


def _render(repo, rev, op, source):
    """Reproduce the old setup's output for one source at one revision."""
    if op == "copy":
        return _git_bytes(repo, "show", f"{rev}:{source}")
    # combine: sorted regular files in the dir, each fragment followed by \n
    # (the algorithm every pre-Seshat setup version used, and Seshat still uses)
    names = _tree_files(repo, rev, source)
    if not names:
        return None
    chunks = []
    for name in names:
        blob = _git_bytes(repo, "show", f"{rev}:{name}")
        if blob is None:
            return None
        chunks.append(blob + b"\n")
    return b"".join(chunks)


def _confined(home, dest):
    return os.path.realpath(dest).startswith(os.path.realpath(home) + os.sep)


def _reap_file(repo, home, rel, op, sources):
    dest = home / rel
    if not os.path.lexists(dest) or os.path.islink(dest) or not dest.is_file():
        return False
    if not _confined(home, dest):
        return False
    current = dest.read_bytes()
    for source in sources:
        if _render(repo, "HEAD", op, source) == current:
            return False  # matches desired content: Seshat adopts it, hands off
    for source in sources:
        for rev in _revs(repo, source):
            if _render(repo, rev, op, source) == current:
                dest.unlink()
                return True
    return False


def _reap_git_dir(repo, home, rel, payload):
    dest = home / rel
    if not os.path.lexists(dest) or os.path.islink(dest) or not dest.is_dir():
        return False
    if not _confined(home, dest):
        return False
    if os.path.lexists(dest / ".git"):
        return False  # a git repo (even a broken one) is Seshat's to judge
    entries = list(os.scandir(dest))
    for entry in entries:
        if not entry.is_file(follow_symlinks=False):
            return False  # subdir/symlink: not the old copy layout, keep it
    for entry in entries:
        path = f"{payload}/{entry.name}"
        content = Path(entry.path).read_bytes()
        if not any(_git_bytes(repo, "show", f"{rev}:{path}") == content for rev in _revs(repo, path)):
            return False
    shutil.rmtree(dest)
    return True


def reap(repo, home):
    """Remove provably-untouched pre-Seshat outputs under home. Returns them."""
    repo, home = Path(repo), Path(home)
    if _git(repo, "rev-parse", "--git-dir").returncode != 0:
        return []
    removed = []
    for rel, (op, sources) in LEGACY_FILES.items():
        try:
            if _reap_file(repo, home, rel, op, sources):
                removed.append(home / rel)
        except OSError as exc:
            print(f"seshat: legacy reaper skipped {home / rel}: {exc}", file=sys.stderr)
    for rel, payload in LEGACY_GIT_DIRS.items():
        try:
            if _reap_git_dir(repo, home, rel, payload):
                removed.append(home / rel)
        except OSError as exc:
            print(f"seshat: legacy reaper skipped {home / rel}: {exc}", file=sys.stderr)
    return removed


def main(argv):
    repo = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parents[1]
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    for path in reap(repo, home):
        print(f"  reap-legacy        {path}  (untouched pre-seshat output)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
