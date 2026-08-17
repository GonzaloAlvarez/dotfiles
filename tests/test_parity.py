import json
import os
import shutil

import pytest
import yaml

from seshatlib.manifest import Facts

from tests.conftest import REPO, make_git_origin
from tests.helpers.legacy import legacy_combine, legacy_copy
from tests.test_cli import run_cli

PAYLOAD_DIRS = [
    "bashrc",
    "screenrc",
    "tmux.conf",
    "zshenv",
    "ideavimrc",
    "aider",
    "vscode",
    "claude",
    "iterm",
    "nvim",
    "bundles",
]

GALVAREZ_MAC = Facts(os="darwin", arch="arm64", user="galvarez", hostname="mac")
OTHER_LINUX = Facts(os="linux", arch="amd64", user="gonzalo", hostname="pi")


@pytest.fixture
def dotfiles_repo(tmp_path):
    repo = tmp_path / "dotfiles"
    repo.mkdir()
    for d in PAYLOAD_DIRS:
        shutil.copytree(REPO / d, repo / d)
    (repo / "seshat").write_text((REPO / "seshat").read_text())
    os.chmod(repo / "seshat", 0o755)

    vim_origin = make_git_origin(tmp_path / "origin-vim", {"vimrc": "set nu\n"})
    nvim_origin = make_git_origin(
        tmp_path / "origin-nvim", {"init.lua": "-- authoritative nvim config\n"}
    )
    manifest_path = repo / "bundles" / "default.yml"
    doc = yaml.safe_load(manifest_path.read_text())
    for t in doc["targets"]:
        if t["id"] == "vim.tree":
            t["url"] = str(vim_origin)
        if t["id"] == "nvim.tree":
            t["url"] = str(nvim_origin)
    manifest_path.write_text(yaml.safe_dump(doc))
    return repo


def install(repo, home, monkeypatch, facts=GALVAREZ_MAC):
    return run_cli(["install", "default", "--automatic"], repo, home, monkeypatch, facts)


def test_parity_with_legacy_outputs(dotfiles_repo, fake_home, monkeypatch):
    assert install(dotfiles_repo, fake_home, monkeypatch) == 0

    for src_dir, dest in [
        ("bashrc", ".bashrc"),
        ("screenrc", ".screenrc"),
        ("tmux.conf", ".tmux.conf"),
        ("zshenv", ".zshenv"),
        ("ideavimrc", ".ideavimrc"),
    ]:
        assert (fake_home / dest).read_bytes() == legacy_combine(dotfiles_repo / src_dir), dest
        assert oct(os.stat(fake_home / dest).st_mode & 0o7777) == "0o644", dest

    assert os.readlink(fake_home / ".bash_profile") == str(fake_home / ".bashrc")

    assert (fake_home / ".aider.conf.yml").read_bytes() == legacy_copy(
        dotfiles_repo / "aider" / "aider.openai.conf.yml"
    )

    for app in ("Code", "Code - Insiders"):
        base = fake_home / "Library" / "Application Support" / app / "User"
        assert (base / "settings.json").read_bytes() == legacy_copy(
            dotfiles_repo / "vscode" / "settings.json"
        )
        assert (base / "keybindings.json").read_bytes() == legacy_copy(
            dotfiles_repo / "vscode" / "keybindings.json"
        )

    statusline = fake_home / ".claude" / "statusline.sh"
    assert statusline.read_bytes() == legacy_copy(dotfiles_repo / "claude" / "statusline.sh")
    assert oct(os.stat(statusline).st_mode & 0o7777) == "0o755"

    settings = fake_home / ".claude" / "settings.json"
    expected_statusline = json.loads((dotfiles_repo / "claude" / "settings.json").read_text())[
        "statusLine"
    ]
    doc = json.loads(settings.read_text())
    assert doc["statusLine"] == expected_statusline
    raw = settings.read_text()
    assert raw.endswith("\n")
    assert '  "statusLine"' in raw

    iterm = (
        fake_home / "Library" / "Application Support" / "iTerm2" / "DynamicProfiles" / "BlackBeast.json"
    )
    assert iterm.read_bytes() == legacy_copy(dotfiles_repo / "iterm" / "Profiles.json")

    assert (fake_home / ".vim" / "vimrc").read_text() == "set nu\n"
    assert (fake_home / ".config" / "nvim" / "init.lua").read_text() == "-- authoritative nvim config\n"
    assert (fake_home / ".config" / "nvim" / "init.lua").read_bytes() != (
        dotfiles_repo / "nvim" / "init.lua"
    ).read_bytes()

    assert os.readlink(fake_home / "bin" / "seshat") == str(dotfiles_repo / "seshat")

    assert not (fake_home / ".conky").exists()
    assert not (fake_home / ".config" / "conky").exists()
    entries = {p.name for p in fake_home.iterdir()}
    assert "obsidian" not in entries


def test_parity_idempotent_second_run(dotfiles_repo, fake_home, monkeypatch, capsys):
    assert install(dotfiles_repo, fake_home, monkeypatch) == 0
    tracked = [
        fake_home / ".bashrc",
        fake_home / ".screenrc",
        fake_home / ".tmux.conf",
        fake_home / ".zshenv",
        fake_home / ".ideavimrc",
        fake_home / ".aider.conf.yml",
        fake_home / ".claude" / "statusline.sh",
        fake_home / ".claude" / "settings.json",
    ]
    before = {p: (p.read_bytes(), os.lstat(p).st_mtime_ns) for p in tracked}
    capsys.readouterr()
    assert install(dotfiles_repo, fake_home, monkeypatch) == 0
    for p, (data, mtime) in before.items():
        assert p.read_bytes() == data, p
        assert os.lstat(p).st_mtime_ns == mtime, p


def test_parity_linux_other_user(dotfiles_repo, fake_home, monkeypatch):
    assert install(dotfiles_repo, fake_home, monkeypatch, facts=OTHER_LINUX) == 0
    assert (fake_home / ".aider.conf.yml").read_bytes() == legacy_copy(
        dotfiles_repo / "aider" / "aider.conf.yml"
    )
    assert not (fake_home / "Library").exists()
    assert (fake_home / ".bashrc").read_bytes() == legacy_combine(dotfiles_repo / "bashrc")
    assert os.readlink(fake_home / ".bash_profile") == str(fake_home / ".bashrc")


def test_parity_existing_machine_adoption(dotfiles_repo, fake_home, monkeypatch):
    assert install(dotfiles_repo, fake_home, monkeypatch) == 0
    seshat_dir = dotfiles_repo / ".seshat"
    (seshat_dir / "state.yml").unlink()
    (seshat_dir / "state.yml.bak").unlink(missing_ok=True)
    tracked = [fake_home / ".bashrc", fake_home / ".claude" / "statusline.sh"]
    before = {p: os.lstat(p).st_mtime_ns for p in tracked}
    assert install(dotfiles_repo, fake_home, monkeypatch) == 0
    for p, mtime in before.items():
        assert os.lstat(p).st_mtime_ns == mtime, p
