"""Context accounting survives restart and rejects stale measured baselines."""

from dataclasses import asdict
from types import SimpleNamespace

import pytest

from agent.context_usage import (
    UsageAnchor,
    context_tokens,
    record_usage,
    snapshot_request,
)
from agent.model_metadata import (
    estimate_messages_tokens_rough,
    estimate_request_tokens_rough,
)
from superforecasting_agent.storage.session import SessionDB


def _agent(db, session_id="s"):
    return SimpleNamespace(
        model="test-model",
        provider="local",
        base_url="http://127.0.0.1",
        api_mode="chat_completions",
        tools=[],
        _cached_system_prompt="system",
        _session_db=db,
        session_id=session_id,
        _ensure_db_session=lambda: None,
    )


def test_real_database_restart_counts_only_new_visible_content(tmp_path):
    path = tmp_path / "sessions.db"
    messages = [{"role": "user", "content": "research fq_abcdef012345"}]
    db = SessionDB(path)
    db.create_session("s", "test", model_config={"temperature": 0.2})
    db.append_message("s", "user", messages[0]["content"])
    agent = _agent(db)
    record_usage(agent, snapshot_request(agent, messages), 40000)
    assert '"temperature": 0.2' in db.get_session("s")["model_config"]
    db.close()
    db = SessionDB(path)
    resumed = _agent(db)
    messages = db.get_messages_as_conversation("s")
    # Hidden billed reasoning is not replayed and must not enter the estimate.
    resumed.session_completion_tokens = 80000
    visible = {"role": "assistant", "content": "Checking source", "tool_calls": []}
    tool = {"role": "tool", "content": "new evidence " * 1000, "tool_call_id": "c1"}
    assert context_tokens(
        resumed, messages + [visible, tool]
    ) == 40000 + estimate_messages_tokens_rough([visible, tool])
    db.close()


@pytest.mark.parametrize(
    "mutation", ["prefix", "rewind", "model", "provider", "tools", "system", "session"]
)
def test_any_priced_prefix_or_request_identity_change_invalidates(mutation):
    agent = _agent(None)
    messages = [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "last"},
    ]
    record_usage(agent, snapshot_request(agent, messages), 40000)
    if mutation == "prefix":
        messages[0]["content"] = "edited first, unchanged last"
    elif mutation == "rewind":
        messages.pop()
    elif mutation == "tools":
        agent.tools = [
            {
                "type": "function",
                "function": {"name": "forecast_new", "parameters": {"type": "object"}},
            }
        ]
    elif mutation == "system":
        agent._cached_system_prompt = "different system"
    elif mutation == "session":
        agent.session_id = "new-session"
    else:
        setattr(agent, mutation, "changed")
    assert context_tokens(agent, messages) == estimate_request_tokens_rough(
        messages, system_prompt=agent._cached_system_prompt, tools=agent.tools
    )


@pytest.mark.parametrize("value", [None, {}, {"version": True}, {"version": 99}])
def test_malformed_or_future_baselines_fail_closed(value):
    assert UsageAnchor.decode(value) is None


def test_nonfinite_or_noninteger_usage_is_not_recorded():
    agent = _agent(None)
    for count in [True, -1, 0, 2.5, float("nan")]:
        record_usage(agent, snapshot_request(agent, []), count)
        assert not hasattr(agent, "_context_usage_anchor")


def test_store_does_not_create_ghost_session(tmp_path):
    db = SessionDB(tmp_path / "sessions.db")
    anchor = UsageAnchor.capture([], {}, 100)
    assert not db.save_context_usage("missing", asdict(anchor))
    assert db.get_session("missing") is None
    db.close()


def test_agent_loop_and_tui_include_new_tool_results_without_billed_reasoning(tmp_path):
    from unittest.mock import patch
    from tests.run_agent.test_tool_call_guardrail_runtime import _make_agent, _mock_response, _mock_tool_call
    from tui_gateway.server import _get_usage

    agent = _make_agent("web_search")
    agent._session_db = SessionDB(tmp_path / "loop.db")
    first = _mock_response(content="", finish_reason="tool_calls", tool_calls=[_mock_tool_call("web_search", "{}", "source1")])
    first.usage = SimpleNamespace(prompt_tokens=40000, completion_tokens=80000, total_tokens=120000)
    # Missing usage on the second call must retain the valid measured baseline
    # and estimate all added visible messages, rather than double counting bills.
    final = _mock_response(content="finished")
    agent.client.chat.completions.create.side_effect = [first, final]
    with (
        patch("run_agent.handle_function_call", return_value='{"evidence": "' + "source " * 1500 + '"}'),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("Research the question")
    assert result["completed"]
    assert 40000 < result["context_used"] < 50000
    usage = _get_usage(agent)
    assert usage["context_used"] == result["context_used"]
    assert usage["completion"] == 80000
    agent._session_db.close()


def test_ephemeral_prefill_changes_invalidate_and_enter_fallback_estimate():
    agent = _agent(None)
    messages = [{"role": "user", "content": "question"}]
    record_usage(agent, snapshot_request(agent, messages), 40000)
    agent.ephemeral_system_prompt = "New ephemeral prompt " * 100
    agent.prefill_messages = [{"role": "user", "content": "prefill " * 100}]
    expected = estimate_request_tokens_rough(agent.prefill_messages + messages, system_prompt="system\n\n" + agent.ephemeral_system_prompt, tools=[])
    assert context_tokens(agent, messages) == expected


def test_accounting_does_not_mutate_discovery_permissions():
    agent = _agent(None)
    agent.tool_discovery_config = {"enabled": True}
    agent.tools = [{"type": "function", "function": {"name": "optional_lookup", "description": "Find data", "parameters": {"type": "object"}}}]
    agent.valid_tool_names = {"optional_lookup"}
    context_tokens(agent, [])
    assert agent.valid_tool_names == {"optional_lookup"}


def test_resumed_tui_uses_stored_prompt_before_first_model_call(tmp_path):
    from tui_gateway.server import _get_usage

    path = tmp_path / "resume.db"
    db = SessionDB(path)
    db.create_session("s", "tui")
    db.update_system_prompt("s", "system")
    messages = [{"role": "user", "content": "retained question"}]
    db.append_message("s", "user", "retained question")
    before = _agent(db)
    record_usage(before, snapshot_request(before, messages), 12345)
    db.close()
    db = SessionDB(path)
    resumed = _agent(db)
    resumed._cached_system_prompt = None
    resumed._session_messages = db.get_messages_as_conversation("s")
    resumed.context_compressor = SimpleNamespace(context_length=100000, last_prompt_tokens=0)
    usage = _get_usage(resumed)
    assert usage["context_used"] == 12345
    assert usage["context_percent"] == 12
    assert resumed._cached_system_prompt is None  # Display does not mutate agent prompt ownership.
    db.close()
