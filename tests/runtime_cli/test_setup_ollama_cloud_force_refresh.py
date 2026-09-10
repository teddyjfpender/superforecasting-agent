"""Ollama Cloud setup refreshes models immediately after key entry."""
from unittest.mock import Mock


def test_setup_ollama_cloud_passes_force_refresh(monkeypatch):
    from superforecasting_agent.runtime import auth, config, main, models

    provider = auth.PROVIDER_REGISTRY["ollama-cloud"]
    if provider.base_url_env_var:
        monkeypatch.delenv(provider.base_url_env_var, raising=False)
    monkeypatch.setattr(config, "get_env_value", lambda key: "")
    monkeypatch.setattr(config, "load_config", lambda: {})
    save = Mock()
    monkeypatch.setattr(config, "save_config", save)
    monkeypatch.setattr(main, "_prompt_api_key", lambda *args, **kwargs: ("fixture-key", False))
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    fetch = Mock(return_value=["fixture-model"])
    monkeypatch.setattr(models, "fetch_ollama_cloud_models", fetch)
    monkeypatch.setattr(auth, "_prompt_model_selection", lambda *args, **kwargs: None)

    main._model_flow_api_key_provider({}, "ollama-cloud")

    fetch.assert_called_once_with(
        api_key="fixture-key", base_url=provider.inference_base_url, force_refresh=True,
    )
    save.assert_not_called()
