"""Test that session ids are exposed via fork-native and legacy aliases."""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../.."))

from run_agent import AIAgent


@pytest.fixture(autouse=True)
def _cleanup_env():
    """Remove session id aliases before/after each test."""
    for name in (
        "SUPERFORECASTING_AGENT_SESSION_ID",
        "FORECAST_SESSION_ID",
        "HERMES_SESSION_ID",
    ):
        os.environ.pop(name, None)
    yield
    for name in (
        "SUPERFORECASTING_AGENT_SESSION_ID",
        "FORECAST_SESSION_ID",
        "HERMES_SESSION_ID",
    ):
        os.environ.pop(name, None)


def test_session_id_env_set_on_init():
    """AIAgent.__init__ sets fork-native and legacy session env aliases."""
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    assert os.environ.get("SUPERFORECASTING_AGENT_SESSION_ID") == agent.session_id
    assert os.environ.get("FORECAST_SESSION_ID") == agent.session_id
    assert os.environ.get("HERMES_SESSION_ID") == agent.session_id
    assert len(agent.session_id) > 0


def test_session_id_env_uses_provided_id():
    """When session_id is passed explicitly, every alias reflects it."""
    custom_id = "20260511_120000_abc12345"
    agent = AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        session_id=custom_id,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    assert os.environ["SUPERFORECASTING_AGENT_SESSION_ID"] == custom_id
    assert os.environ["FORECAST_SESSION_ID"] == custom_id
    assert os.environ["HERMES_SESSION_ID"] == custom_id
    assert agent.session_id == custom_id


def test_session_id_contextvar_set():
    """AIAgent.__init__ also sets the ContextVar for concurrency safety."""
    custom_id = "20260511_130000_def67890"
    AIAgent(
        api_key="test-key",
        base_url="https://openrouter.ai/api/v1",
        session_id=custom_id,
        quiet_mode=True,
        skip_context_files=True,
        skip_memory=True,
    )
    from gateway.session_context import get_session_env
    assert get_session_env("SUPERFORECASTING_AGENT_SESSION_ID") == custom_id
    assert get_session_env("FORECAST_SESSION_ID") == custom_id
    assert get_session_env("HERMES_SESSION_ID") == custom_id
