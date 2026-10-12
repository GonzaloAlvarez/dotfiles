from seshatlib import manifest
from seshatlib.manifest import Facts

from tests.conftest import REPO

DARWIN = Facts(os="darwin", arch="arm64", user="galvarez", hostname="mac")
LINUX = Facts(os="linux", arch="amd64", user="gonzalo", hostname="pi")


def test_real_bundles_load_and_validate():
    bundles = manifest.load_bundles(REPO)
    assert set(bundles) == {"default", "llm.claude.bedrock", "llm.qwen.local", "localllm.server"}
    assert bundles["default"].automatic is True
    assert bundles["llm.claude.bedrock"].automatic is False
    assert bundles["llm.claude.bedrock"].depends_on == ["default"]
    assert bundles["llm.qwen.local"].automatic is False
    assert bundles["llm.qwen.local"].depends_on == ["default"]
    assert bundles["localllm.server"].automatic is False
    assert bundles["localllm.server"].depends_on == ["default"]


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
        "herdr.config",
        "herdr.move_pane",
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
    assert darwin_targets["herdr.move_pane"].mode == 0o755
    assert darwin_targets["herdr.config"].validate == ["toml"]

    dests = [t.destination for t in darwin_targets.values()]
    assert "~/.config/nvim/init.lua" not in dests
    assert not any("obsidian" in (t.source or "") for t in darwin_targets.values())
    assert not any("conky" in (t.source or "") for t in darwin_targets.values())


def test_real_qwen_local_bundle_shape():
    bundles = manifest.load_bundles(REPO)
    b = bundles["llm.qwen.local"]
    # client-only: the server side is the separate localllm.server bundle
    assert b.requires_commands == ["qwen"]
    assert b.requires_kauket == []
    assert b.variables["server_host"].default == "127.0.0.1"
    assert b.variables["model_alias"].default == "qwen3.8-27b-local"
    assert b.variables["port"].default == "8080"
    # optional second model id (router-mode servers); empty = one entry
    assert b.variables["model2_alias"].default == ""

    darwin_targets = {t.id: t for t in manifest.resolve_targets(b, DARWIN)}
    assert set(darwin_targets) == {"qwen.settings.local", "qwen.env"}
    assert darwin_targets["qwen.settings.local"].owns == [
        "/modelProviders", "/primaryModel", "/model", "/security",
    ]
    assert darwin_targets["qwen.settings.local"].template is True
    assert darwin_targets["qwen.env"].mode == 0o600

    # client runs on linux too (remote server topology)
    linux_targets = {t.id: t for t in manifest.resolve_targets(b, LINUX)}
    assert set(linux_targets) == {"qwen.settings.local", "qwen.env"}


def test_real_localllm_server_bundle_shape():
    bundles = manifest.load_bundles(REPO)
    b = bundles["localllm.server"]
    assert b.requires_commands == ["localllm"]
    assert b.requires_kauket == []
    assert b.variables["model_file"].default == "Qwen3.8-27B-UD-Q6_K.gguf"
    assert b.variables["bind"].default == "127.0.0.1"
    assert b.variables["kv_quant"].default == "q8_0"
    assert b.variables["spec_type"].default == "none"
    assert b.variables["port"].default == "8080"
    # router mode is opt-in; defaults keep every existing machine in single mode
    assert b.variables["ngl"].default == "all"
    assert b.variables["model2_alias"].default == ""
    assert b.variables["model2_file"].default == ""
    assert b.variables["models_max"].default == "1"
    assert b.variables["sleep_idle"].default == "-1"

    darwin_targets = {t.id: t for t in manifest.resolve_targets(b, DARWIN)}
    assert set(darwin_targets) == {"localllm.config"}
    assert darwin_targets["localllm.config"].template is True

    # linux since gear com/localllm 1.3.0 (setup-debian/setup-linux); the
    # systemd --user unit is linux-only
    linux_targets = {t.id: t for t in manifest.resolve_targets(b, LINUX)}
    assert set(linux_targets) == {"localllm.config", "localllm.service"}
    assert linux_targets["localllm.config"].template is True
    assert linux_targets["localllm.service"].template is False


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


def _render_real(bundle_name, rel_source, overrides, facts, home):
    """Render a real bundle template with its declared defaults plus overrides."""
    from seshatlib import templates

    b = manifest.load_bundles(REPO)[bundle_name]
    values = {name: var.default for name, var in b.variables.items()}
    values.update(overrides)
    ctx = templates.build_context(values, facts, b, home, "test")
    return templates.render((REPO / rel_source).read_bytes(), ctx)


def test_real_qwen_local_template_one_or_two_models(tmp_path):
    import json

    src = "bundles/llm.qwen.local/files/qwen-settings.json.j2"
    one = json.loads(_render_real("llm.qwen.local", src, {}, LINUX, tmp_path))
    assert [m["id"] for m in one["modelProviders"]["openai"]] == ["qwen3.8-27b-local"]
    assert one["primaryModel"] == "qwen3.8-27b-local"

    two = json.loads(_render_real(
        "llm.qwen.local", src,
        {"server_host": "travelblock.local", "model_alias": "code", "model2_alias": "think"},
        LINUX, tmp_path,
    ))
    entries = two["modelProviders"]["openai"]
    assert [m["id"] for m in entries] == ["code", "think"]
    assert {m["baseUrl"] for m in entries} == {"http://travelblock.local:8080/v1"}
    assert entries[1]["generationConfig"]["samplingParams"]["temperature"] == 1.0
    assert two["primaryModel"] == "code"
    assert two["model"]["name"] == "code"


def test_real_localllm_config_template_router_keys(tmp_path):
    src = "bundles/localllm.server/files/localllm-config.j2"
    single = _render_real("localllm.server", src, {}, DARWIN, tmp_path).decode()
    assert "NGL=all\n" in single
    assert "MODEL2_ALIAS=\n" in single
    assert "MODEL_ARGS=''\n" in single

    router = _render_real(
        "localllm.server", src,
        {"model2_alias": "qwen3.8-27b-think", "ngl": "0",
         "model_args": 'chat-template-kwargs={"enable_thinking":false} temp=0.7'},
        LINUX, tmp_path,
    ).decode()
    assert "NGL=0\n" in router
    assert "MODEL2_ALIAS=qwen3.8-27b-think\n" in router
    # JSON values keep their double quotes: the line is single-quoted for bash
    assert "MODEL_ARGS='chat-template-kwargs={\"enable_thinking\":false} temp=0.7'\n" in router
