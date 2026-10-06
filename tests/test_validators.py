import sys
import types

import pytest

from seshatlib.installer import ValidationError, run_validators


def _staged(target_id="t.toml", mode=None):
    # run_validators only reads target_id (messages) and mode (executable check).
    return types.SimpleNamespace(target_id=target_id, mode=mode)


def test_toml_validator_accepts_valid_toml():
    run_validators(["toml"], b'[herdr]\nname = "x"\nn = 1\n', _staged())


def test_toml_validator_rejects_invalid_toml():
    with pytest.raises(ValidationError) as ei:
        run_validators(["toml"], b"[herdr\nname = \n", _staged())
    assert "t.toml" in str(ei.value)


def test_toml_validator_falls_back_to_tomli_backport(monkeypatch):
    # Python < 3.11 has no tomllib; the launcher installs tomli there and the
    # validator must use it transparently.
    calls = []
    fake = types.ModuleType("tomli")
    fake.loads = lambda text: calls.append(text) or {}
    monkeypatch.setitem(sys.modules, "tomllib", None)  # import -> ImportError
    monkeypatch.setitem(sys.modules, "tomli", fake)
    run_validators(["toml"], b"a = 1\n", _staged())
    assert calls == ["a = 1\n"]


def test_toml_validator_names_the_missing_backport(monkeypatch):
    monkeypatch.setitem(sys.modules, "tomllib", None)
    monkeypatch.setitem(sys.modules, "tomli", None)
    with pytest.raises(ValidationError) as ei:
        run_validators(["toml"], b"a = 1\n", _staged())
    assert "tomli backport" in str(ei.value)


def test_launcher_pins_tomli_only_below_3_11():
    # The polyglot launcher cannot be imported; check the pin and its guard as text.
    from tests.conftest import REPO

    src = (REPO / "seshat").read_text()
    assert 'DEPS.append("tomli==' in src
    assert "sys.version_info < (3, 11)" in src
