"""Installed local speech backends must survive setup detection."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.runtime import setup


@pytest.fixture
def local_setup(monkeypatch):
    feature = SimpleNamespace(managed_by_nous=False, available=False,
                              current_provider=None, direct_override=False)
    features = SimpleNamespace(nous_auth_present=False, **{
        name: feature for name in ("web", "browser", "image_gen", "tts", "modal")
    })
    monkeypatch.setattr(setup, "get_nous_subscription_features", lambda config: features)
    monkeypatch.setattr(setup, "managed_nous_tools_enabled", lambda: False)
    monkeypatch.setattr(setup, "get_env_value", lambda key: None)
    monkeypatch.setattr("agent.auxiliary_client.get_available_vision_backends", lambda: [])


@pytest.mark.parametrize("provider,package,label", [
    ("neutts", "neutts", "NeuTTS"),
    ("kokoro", "kokoro_onnx", "Kokoro-82M"),
    ("kittentts", "kittentts", "KittenTTS"),
])
def test_summary_recognizes_installed_local_tts(
    local_setup, monkeypatch, tmp_path, capsys, provider, package, label
):
    original = setup.importlib.util.find_spec
    monkeypatch.setattr(setup.importlib.util, "find_spec",
                        lambda name: object() if name == package else original(name))
    setup._print_setup_summary({"tts": {"provider": provider}}, tmp_path)
    assert f"Text-to-Speech ({label} local)" in capsys.readouterr().out


@pytest.mark.parametrize("provider,package,label", [
    ("neutts", "neutts", "NeuTTS"),
    ("kokoro", "kokoro_onnx", "Kokoro-82M"),
    ("kittentts", "kittentts", "KittenTTS"),
])
def test_selection_preserves_installed_local_tts(
    local_setup, monkeypatch, provider, package, label
):
    monkeypatch.setattr(setup.importlib.util, "find_spec", lambda name: object() if name == package else None)
    monkeypatch.setattr(setup, "prompt_choice", lambda question, choices, default: next(
        i for i, choice in enumerate(choices) if choice.startswith(label)
    ))
    install_prompt = Mock(return_value=False)
    save = Mock()
    monkeypatch.setattr(setup, "prompt_yes_no", install_prompt)
    monkeypatch.setattr(setup, "save_config", save)
    config = {}
    setup._setup_tts_provider(config)
    install_prompt.assert_not_called()
    assert config["tts"]["provider"] == provider
    save.assert_called_once_with(config)
