import pytest

from seshatlib import providers
from seshatlib.providers import ProviderError


def test_missing_commands():
    assert providers.missing_commands(["sh"]) == []
    assert providers.missing_commands(["definitely-not-a-command-xyz"]) == [
        "definitely-not-a-command-xyz"
    ]
    assert providers.missing_commands([]) == []
    assert providers.missing_commands(None) == []


def test_kauket_install_invokes_get(fake_kauket):
    providers.run_kauket([{"id": "aws.profile.bedrock", "action": "install"}])
    log = fake_kauket["log"].read_text().strip().splitlines()
    assert log == ["get aws.profile.bedrock"]


def test_kauket_called_once_per_prereq(fake_kauket):
    providers.run_kauket(
        [
            {"id": "aws.profile.bedrock", "action": "install"},
            {"id": "ssh.deploy_key", "action": "install"},
        ]
    )
    log = fake_kauket["log"].read_text().strip().splitlines()
    assert log == ["get aws.profile.bedrock", "get ssh.deploy_key"]


def test_kauket_failure_raises(fake_kauket):
    fake_kauket["fail_flag"].touch()
    with pytest.raises(ProviderError, match="exit 3"):
        providers.run_kauket([{"id": "aws.profile.bedrock", "action": "install"}])


def test_kauket_unsupported_action(fake_kauket):
    with pytest.raises(ProviderError, match="unsupported kauket action"):
        providers.run_kauket([{"id": "x", "action": "uninstall"}])
    assert not fake_kauket["log"].exists()


def test_kauket_missing_binary(monkeypatch):
    monkeypatch.setenv("SESHAT_KAUKET", "/nonexistent/kauket-binary")
    with pytest.raises(ProviderError, match="not found"):
        providers.run_kauket([{"id": "x", "action": "install"}])


def test_same_origin_normalization():
    assert providers.same_origin(
        "https://github.com/GonzaloAlvarez/vim", "https://github.com/gonzaloalvarez/vim.git"
    )
    assert providers.same_origin("https://x/y/", "https://x/y")
    assert not providers.same_origin("https://x/y", "https://x/z")
    assert not providers.same_origin(None, "https://x/y")
