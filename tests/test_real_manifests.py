from seshatlib import manifest
from seshatlib.manifest import Facts

from tests.conftest import REPO

DARWIN = Facts(os="darwin", arch="arm64", user="galvarez", hostname="mac")
LINUX = Facts(os="linux", arch="amd64", user="gonzalo", hostname="pi")


def test_real_bundles_load_and_validate():
    bundles = manifest.load_bundles(REPO)
    assert set(bundles) == {"default", "llm.client", "localllm.server"}
    assert bundles["default"].automatic is True
    assert bundles["llm.client"].automatic is False
    assert bundles["llm.client"].depends_on == ["default"]
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



def _render_real(bundle_name, rel_source, overrides, facts, home):
    """Render a real bundle template with its declared defaults plus overrides."""
    from seshatlib import templates

    b = manifest.load_bundles(REPO)[bundle_name]
    values = {name: var.default for name, var in b.variables.items()}
    values.update(overrides)
    ctx = templates.build_context(values, facts, b, home, "test")
    return templates.render((REPO / rel_source).read_bytes(), ctx)



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


def test_real_llm_client_bundle_shape():
    bundles = manifest.load_bundles(REPO)
    b = bundles["llm.client"]
    # client-only, secret-free: the router has no API key by design
    assert b.requires_commands == ["claude", "qwen"]
    assert b.requires_kauket == []
    assert b.variables["router_url"].default == "https://llmrouter.lab.gn.al"
    assert b.variables["default_model"].default == "auto"
    # direct llama-server entries are opt-in (offline use)
    assert b.variables["local_host"].default == ""
    assert b.variables["local_alias"].default == "qwen3.8-27b-code"
    assert b.variables["local_alias2"].default == "qwen3.8-27b-think"

    for facts in (DARWIN, LINUX):
        targets = {t.id: t for t in manifest.resolve_targets(b, facts)}
        assert set(targets) == {"claude.settings.router", "qwen.settings.router", "qwen.env"}
        assert targets["claude.settings.router"].owns == ["/env", "/modelPicker"]
        assert targets["claude.settings.router"].template is True
        assert targets["qwen.settings.router"].owns == [
            "/modelProviders", "/primaryModel", "/model", "/security",
        ]
        assert targets["qwen.settings.router"].template is True
        assert targets["qwen.env"].mode == 0o600


def test_real_llm_client_claude_template(tmp_path):
    import json

    src = "bundles/llm.client/files/claude-settings.json.j2"
    doc = json.loads(_render_real("llm.client", src, {}, LINUX, tmp_path))
    # rendered keys must equal `owns` exactly (installer rule)
    assert set(doc) == {"env", "modelPicker"}
    env = doc["env"]
    assert env["ANTHROPIC_BASE_URL"] == "https://llmrouter.lab.gn.al"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "open"
    assert env["ANTHROPIC_API_KEY"] == ""          # blank keeps Claude Code on the gateway
    assert env["ANTHROPIC_MODEL"] == "auto"
    assert env["CLAUDE_CODE_GATEWAY_HINT_HEADERS"] == "1"
    picker = doc["modelPicker"]
    assert picker["replaceBuiltInOptions"] is True
    ids = [o["model"] for o in picker["options"]]
    assert ids[0] == "auto"
    for m in ("deepseek-flash", "claude-opus", "claude-sonnet", "qwen-local",
              "qwen-klaus", "qwen-minerva", "qwen-travelblock", "gpt-5.5"):
        assert m in ids, m
    assert all(o["label"] for o in picker["options"])

    other = json.loads(_render_real(
        "llm.client", src,
        {"router_url": "http://10.1.1.140:4000", "default_model": "deepseek-flash"},
        DARWIN, tmp_path,
    ))
    assert other["env"]["ANTHROPIC_BASE_URL"] == "http://10.1.1.140:4000"
    assert other["env"]["ANTHROPIC_MODEL"] == "deepseek-flash"


def test_real_llm_client_qwen_template(tmp_path):
    import json

    src = "bundles/llm.client/files/qwen-settings.json.j2"
    doc = json.loads(_render_real("llm.client", src, {}, LINUX, tmp_path))
    assert set(doc) == {"modelProviders", "primaryModel", "model", "security"}
    entries = doc["modelProviders"]["openai"]
    ids = [m["id"] for m in entries]
    assert ids[:3] == ["auto", "auto-claude", "deepseek-flash"]
    for m in ("qwen-local", "qwen-think", "qwen-klaus", "qwen-minerva", "qwen-travelblock",
              "qwen-travelblock-think", "claude-opus", "claude-haiku", "gpt-5.5"):
        assert m in ids, m
    assert {m["baseUrl"] for m in entries} == {"https://llmrouter.lab.gn.al/v1"}
    assert {m["envKey"] for m in entries} == {"LLM_ROUTER_API_KEY"}
    by_id = {m["id"]: m for m in entries}
    assert by_id["deepseek-flash"]["generationConfig"]["contextWindowSize"] == 1000000
    assert by_id["qwen-klaus"]["generationConfig"]["contextWindowSize"] == 65536
    assert by_id["qwen-minerva"]["generationConfig"]["contextWindowSize"] == 32768
    assert doc["primaryModel"] == "auto"
    assert doc["model"] == {"name": "auto", "baseUrl": "https://llmrouter.lab.gn.al/v1"}
    assert doc["security"]["auth"]["selectedType"] == "openai"

    # local_host adds DIRECT entries (code + think) after the router rows
    direct = json.loads(_render_real(
        "llm.client", src,
        {"local_host": "127.0.0.1", "default_model": "qwen3.8-27b-code"},
        DARWIN, tmp_path,
    ))
    d_entries = [m for m in direct["modelProviders"]["openai"] if m["envKey"] == "LOCAL_LLAMA_API_KEY"]
    assert [m["id"] for m in d_entries] == ["qwen3.8-27b-code", "qwen3.8-27b-think"]
    assert {m["baseUrl"] for m in d_entries} == {"http://127.0.0.1:8080/v1"}
    assert d_entries[0]["generationConfig"]["samplingParams"]["temperature"] == 0.7
    assert d_entries[1]["generationConfig"]["samplingParams"]["temperature"] == 1.0
    assert direct["primaryModel"] == "qwen3.8-27b-code"

    one = json.loads(_render_real(
        "llm.client", src, {"local_host": "travelblock.local", "local_alias2": ""}, LINUX, tmp_path,
    ))
    o_entries = [m for m in one["modelProviders"]["openai"] if m["envKey"] == "LOCAL_LLAMA_API_KEY"]
    assert [m["id"] for m in o_entries] == ["qwen3.8-27b-code"]
    assert o_entries[0]["baseUrl"] == "http://travelblock.local:8080/v1"
