from seshatlib import manifest
from seshatlib.manifest import Facts

from tests.conftest import REPO

DARWIN = Facts(os="darwin", arch="arm64", user="galvarez", hostname="mac")
LINUX = Facts(os="linux", arch="amd64", user="gonzalo", hostname="pi")


def test_real_bundles_load_and_validate():
    bundles = manifest.load_bundles(REPO)
    assert set(bundles) == {"default", "llm.claude.bedrock"}
    assert bundles["default"].automatic is True
    assert bundles["llm.claude.bedrock"].automatic is False
    assert bundles["llm.claude.bedrock"].depends_on == ["default"]


def test_real_bundles_no_overlaps():
    bundles = manifest.load_bundles(REPO)
    manifest.check_overlaps(bundles, DARWIN)
    manifest.check_overlaps(bundles, LINUX)


def test_real_default_digest_computes_on_both_platforms():
    bundles = manifest.load_bundles(REPO)
    d_mac = manifest.bundle_source_digest(bundles["default"], REPO, DARWIN)
    d_linux = manifest.bundle_source_digest(bundles["default"], REPO, LINUX)
    assert d_mac != d_linux
    assert d_mac == manifest.bundle_source_digest(bundles["default"], REPO, DARWIN)


def test_real_default_target_coverage():
    bundles = manifest.load_bundles(REPO)
    darwin_targets = {t.id: t for t in manifest.resolve_targets(bundles["default"], DARWIN)}
    linux_targets = {t.id: t for t in manifest.resolve_targets(bundles["default"], LINUX)}

    for tid in (
        "shell.bashrc",
        "shell.bash_profile",
        "screen.screenrc",
        "tmux.conf",
        "shell.zshenv",
        "ideavim.rc",
        "aider.conf",
        "claude.statusline",
        "claude.settings.statusline",
        "vim.tree",
        "nvim.tree",
        "seshat.bin",
    ):
        assert tid in darwin_targets, tid
        assert tid in linux_targets, tid

    for tid in (
        "vscode.settings",
        "vscode.keybindings",
        "vscode.insiders.settings",
        "vscode.insiders.keybindings",
        "iterm.blackbeast",
    ):
        assert tid in darwin_targets, tid
        assert tid not in linux_targets, tid

    assert darwin_targets["aider.conf"].source == "aider/aider.openai.conf.yml"
    assert linux_targets["aider.conf"].source == "aider/aider.conf.yml"
    assert darwin_targets["claude.statusline"].mode == 0o755

    dests = [t.destination for t in darwin_targets.values()]
    assert "~/.config/nvim/init.lua" not in dests
    assert not any("obsidian" in (t.source or "") for t in darwin_targets.values())
    assert not any("conky" in (t.source or "") for t in darwin_targets.values())


def test_real_bedrock_bundle_shape():
    bundles = manifest.load_bundles(REPO)
    b = bundles["llm.claude.bedrock"]
    assert b.requires_commands == ["claude", "kauket"]
    assert b.requires_kauket == [{"id": "aws.profile.bedrock", "action": "install"}]
    assert b.variables["aws_profile"].default == "bedrock"
    assert b.variables["aws_region"].default == "us-east-2"
    targets = manifest.resolve_targets(b, DARWIN)
    assert len(targets) == 1
    assert targets[0].owns == ["/env"]
    assert targets[0].template is True
