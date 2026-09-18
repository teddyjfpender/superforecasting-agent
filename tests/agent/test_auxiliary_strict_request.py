"""Paid interview requests preserve caps and never retry with changed semantics."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent import auxiliary_client as aux


@pytest.fixture
def client(monkeypatch):
    client = Mock()
    client.base_url = "https://example.invalid/v1"
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))]
    )
    monkeypatch.setattr(
        aux,
        "_resolve_task_provider_model",
        lambda *args: ("custom", "test-model", client.base_url, "test", None),
    )
    monkeypatch.setattr(
        aux, "_get_cached_client", Mock(return_value=(client, "test-model"))
    )
    monkeypatch.setattr(aux, "_get_task_extra_body", lambda task: {})
    monkeypatch.setattr(aux, "auxiliary_is_nous", False)
    return client


def request(**kwargs):
    return aux.call_llm(
        task="forecast_interview",
        messages=[{"role": "user", "content": "test"}],
        strict_request=True,
        max_tokens=512,
        timeout=5,
        **kwargs,
    )


@pytest.mark.parametrize(
    "error",
    [
        "unsupported_parameter: max_tokens",
        "unsupported temperature",
        "Payment Required",
        "Rate limit exceeded",
        "Unauthorized",
    ],
)
def test_errors_never_remove_cap_or_retry(client, error):
    client.chat.completions.create.side_effect = RuntimeError(error)
    with pytest.raises(RuntimeError, match=error):
        request(temperature=0)
    assert client.chat.completions.create.call_count == 1
    assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 512
    assert aux._get_cached_client.call_count == 1


def test_success_preserves_requested_cap(client):
    assert request().choices[0].message.content == "{}"
    assert client.chat.completions.create.call_args.kwargs["max_tokens"] == 512


@pytest.mark.parametrize(
    "field",
    [
        "max_tokens",
        "max_completion_tokens",
        "max_output_tokens",
        "model",
        "messages",
        "n",
    ],
)
def test_extra_body_cannot_override_contract(client, field):
    with pytest.raises(ValueError, match="protected fields"):
        request(extra_body={field: 9000})
    client.chat.completions.create.assert_not_called()


def test_codex_route_rejected_before_spend(client, monkeypatch):
    codex = aux.CodexAuxiliaryClient(client, "test-model")
    monkeypatch.setattr(
        aux, "_get_cached_client", Mock(return_value=(codex, "test-model"))
    )
    with pytest.raises(ValueError, match="Codex OAuth"):
        request()
    client.responses.create.assert_not_called()


def test_missing_output_cap_fails_before_provider_resolution(monkeypatch):
    resolve = Mock()
    monkeypatch.setattr(aux, "_resolve_task_provider_model", resolve)
    with pytest.raises(ValueError, match="positive max_tokens"):
        aux.call_llm(messages=[], strict_request=True)
    resolve.assert_not_called()


def test_unavailable_route_does_not_fall_back(client, monkeypatch):
    resolve = Mock(return_value=(None, "test-model"))
    monkeypatch.setattr(aux, "_get_cached_client", resolve)
    with pytest.raises(RuntimeError, match="No LLM provider"):
        request()
    assert resolve.call_count == 1


def test_adapter_omitting_cap_fails_before_spend(client, monkeypatch):
    monkeypatch.setattr(
        aux,
        "_build_call_kwargs",
        lambda *args, **kwargs: {"model": "test-model", "messages": []},
    )
    with pytest.raises(ValueError, match="preserve"):
        request()
    client.chat.completions.create.assert_not_called()


def test_interview_worker_requires_strict_request(client, monkeypatch):
    from forecasting.interviews.model_worker import call

    send = Mock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
            model="test-model",
            usage=None,
        )
    )
    monkeypatch.setattr(aux, "call_llm", send)
    call({"options": {"max_tokens": 512, "timeout_seconds": 5}, "messages": []})
    assert send.call_args.kwargs["strict_request"] is True
    assert send.call_args.kwargs["max_tokens"] == 512
