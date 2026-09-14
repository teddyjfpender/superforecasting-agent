"""Runtime tests for tool-call loop guardrails."""

import json
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from run_agent import AIAgent


def _make_tool_defs(*names: str) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": f"{name} tool",
                "parameters": {"type": "object", "properties": {}},
            },
        }
        for name in names
    ]


def _mock_tool_call(name="web_search", arguments="{}", call_id=None):
    return SimpleNamespace(
        id=call_id or f"call_{uuid.uuid4().hex[:8]}",
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def _mock_response(content="Hello", finish_reason="stop", tool_calls=None):
    msg = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(message=msg, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice], model="test/model", usage=None)


def _make_agent(*tool_names: str, max_iterations: int = 10, config: dict | None = None) -> AIAgent:
    with (
        patch("run_agent.get_tool_definitions", return_value=_make_tool_defs(*tool_names)),
        patch("run_agent.check_toolset_requirements", return_value={}),
        patch("superforecasting_agent.runtime.config.load_config", return_value=config or {}),
        patch("run_agent.OpenAI"),
    ):
        agent = AIAgent(
            api_key="test-key-1234567890",
            base_url="https://openrouter.ai/api/v1",
            max_iterations=max_iterations,
            quiet_mode=True,
            skip_context_files=True,
            skip_memory=True,
        )
    agent.client = MagicMock()
    agent._cached_system_prompt = "You are helpful."
    agent._use_prompt_caching = False
    agent.tool_delay = 0
    agent.compression_enabled = False
    agent.save_trajectories = False
    return agent


def _seed_exact_failures(agent: AIAgent, tool_name: str, args: dict, count: int = 2) -> None:
    for _ in range(count):
        agent._tool_guardrails.after_call(
            tool_name,
            args,
            json.dumps({"error": "boom"}),
            failed=True,
        )


def _hard_stop_config(**overrides) -> dict:
    cfg = {
        "tool_loop_guardrails": {
            "warnings_enabled": True,
            "hard_stop_enabled": True,
            "hard_stop_after": {
                "exact_failure": 2,
                "same_tool_failure": 8,
                "idempotent_no_progress": 5,
            },
        }
    }
    cfg["tool_loop_guardrails"].update(overrides)
    return cfg


def test_default_sequential_path_warns_repeated_exact_failure_without_blocking_execution():
    agent = _make_agent("web_search")
    args = {"query": "same"}
    _seed_exact_failures(agent, "web_search", args)
    starts = []
    progress = []
    agent.tool_start_callback = lambda *a, **k: starts.append((a, k))
    agent.tool_progress_callback = lambda *a, **k: progress.append((a, k))
    tc = _mock_tool_call("web_search", json.dumps(args), "c-soft")
    msg = SimpleNamespace(content="", tool_calls=[tc])
    messages = []

    with patch("run_agent.handle_function_call", return_value=json.dumps({"error": "boom"})) as mock_hfc:
        agent._execute_tool_calls_sequential(msg, messages, "task-1")

    mock_hfc.assert_called_once()
    assert len(starts) == 1
    assert any(event[0][0] == "tool.completed" for event in progress)
    assert len(messages) == 1
    assert messages[0]["role"] == "tool"
    assert messages[0]["tool_call_id"] == "c-soft"
    assert "repeated_exact_failure_warning" in messages[0]["content"]
    assert "repeated_exact_failure_block" not in messages[0]["content"]
    assert agent._tool_guardrail_halt_decision is None


def test_config_enabled_hard_stop_blocks_repeated_exact_failure_before_execution():
    agent = _make_agent("web_search", config=_hard_stop_config())
    args = {"query": "same"}
    _seed_exact_failures(agent, "web_search", args)
    starts = []
    progress = []
    agent.tool_start_callback = lambda *a, **k: starts.append((a, k))
    agent.tool_progress_callback = lambda *a, **k: progress.append((a, k))
    tc = _mock_tool_call("web_search", json.dumps(args), "c-block")
    msg = SimpleNamespace(content="", tool_calls=[tc])
    messages = []

    with patch("run_agent.handle_function_call", return_value="SHOULD_NOT_RUN") as mock_hfc:
        agent._execute_tool_calls_sequential(msg, messages, "task-1")

    mock_hfc.assert_not_called()
    assert starts == []
    assert progress == []
    assert len(messages) == 1
    assert messages[0]["role"] == "tool"
    assert messages[0]["tool_call_id"] == "c-block"
    assert "repeated_exact_failure_block" in messages[0]["content"]


def test_sequential_after_call_appends_guidance_to_tool_result_without_extra_messages():
    agent = _make_agent("web_search")
    args = {"query": "same"}
    _seed_exact_failures(agent, "web_search", args, count=1)
    tc = _mock_tool_call("web_search", json.dumps(args), "c-warn")
    msg = SimpleNamespace(content="", tool_calls=[tc])
    messages = []

    with patch("run_agent.handle_function_call", return_value=json.dumps({"error": "boom"})):
        agent._execute_tool_calls_sequential(msg, messages, "task-1")

    assert [m["role"] for m in messages] == ["tool"]
    assert messages[0]["tool_call_id"] == "c-warn"
    assert "Tool loop warning" in messages[0]["content"]
    assert "repeated_exact_failure_warning" in messages[0]["content"]


def test_same_tool_failure_warning_tells_model_to_recover_with_tools():
    agent = _make_agent("terminal")
    guardrails = getattr(agent, "_tool_guardrails")
    guardrails.after_call(
        "terminal",
        {"command": "bad-1"},
        json.dumps({"exit_code": 1}),
        failed=True,
    )
    guardrails.after_call(
        "terminal",
        {"command": "bad-2"},
        json.dumps({"exit_code": 1}),
        failed=True,
    )
    tc = _mock_tool_call("terminal", json.dumps({"command": "bad-3"}), "c-recover")
    msg = SimpleNamespace(content="", tool_calls=[tc])
    messages = []

    with patch("run_agent.handle_function_call", return_value=json.dumps({"exit_code": 1})):
        agent._execute_tool_calls_sequential(msg, messages, "task-1")

    content = messages[0]["content"]
    assert "same_tool_failure_warning" in content
    assert "Do not switch to text-only replies" in content
    assert "keep using tools" in content
    assert "pwd && ls -la" in content
    assert "absolute path" in content
    assert "different tool" in content


def test_config_enabled_hard_stop_concurrent_path_does_not_submit_blocked_calls_and_preserves_result_order():
    agent = _make_agent("web_search", config=_hard_stop_config())
    blocked_args = {"query": "blocked"}
    allowed_args = {"query": "allowed"}
    _seed_exact_failures(agent, "web_search", blocked_args)
    starts = []
    progress_events = []
    agent.tool_start_callback = lambda tool_call_id, name, args: starts.append((tool_call_id, name, args))
    agent.tool_progress_callback = lambda event, name, preview, args, **kw: progress_events.append((event, name, args, kw))
    calls = [
        _mock_tool_call("web_search", json.dumps(blocked_args), "c-block"),
        _mock_tool_call("web_search", json.dumps(allowed_args), "c-allow"),
    ]
    msg = SimpleNamespace(content="", tool_calls=calls)
    messages = []
    executed = []

    def fake_handle(name, args, task_id, **kwargs):
        executed.append((name, args, kwargs["tool_call_id"]))
        return json.dumps({"ok": args["query"]})

    with patch("run_agent.handle_function_call", side_effect=fake_handle):
        agent._execute_tool_calls_concurrent(msg, messages, "task-1")

    assert executed == [("web_search", allowed_args, "c-allow")]
    assert [m["tool_call_id"] for m in messages] == ["c-block", "c-allow"]
    assert "repeated_exact_failure_block" in messages[0]["content"]
    assert json.loads(messages[1]["content"]) == {"ok": "allowed"}
    assert starts == [("c-allow", "web_search", allowed_args)]
    started_events = [event for event in progress_events if event[0] == "tool.started"]
    completed_events = [event for event in progress_events if event[0] == "tool.completed"]
    assert started_events == [("tool.started", "web_search", allowed_args, {})]
    assert len(completed_events) == 1
    assert completed_events[0][1] == "web_search"


def test_plugin_pre_tool_block_wins_without_counting_as_toolguard_block():
    agent = _make_agent("web_search")
    args = {"query": "same"}
    tc = _mock_tool_call("web_search", json.dumps(args), "c-plugin")
    msg = SimpleNamespace(content="", tool_calls=[tc])
    messages = []

    with (
        patch("superforecasting_agent.runtime.plugins.get_pre_tool_call_block_message", return_value="plugin policy"),
        patch("run_agent.handle_function_call", return_value="SHOULD_NOT_RUN") as mock_hfc,
    ):
        agent._execute_tool_calls_sequential(msg, messages, "task-1")

    mock_hfc.assert_not_called()
    assert "plugin policy" in messages[0]["content"]
    assert agent._tool_guardrails.before_call("web_search", args).action == "allow"


def test_default_run_conversation_warns_without_guardrail_halt():
    agent = _make_agent("web_search", max_iterations=10)
    same_args = {"query": "same"}
    responses = [
        _mock_response(
            content="",
            finish_reason="tool_calls",
            tool_calls=[_mock_tool_call("web_search", json.dumps(same_args), f"c{i}")],
        )
        for i in range(1, 4)
    ]
    responses.append(_mock_response(content="done", finish_reason="stop", tool_calls=None))
    agent.client.chat.completions.create.side_effect = responses

    with (
        patch("run_agent.handle_function_call", return_value=json.dumps({"error": "boom"})) as mock_hfc,
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("search repeatedly")

    assert mock_hfc.call_count == 3
    assert result["turn_exit_reason"].startswith("text_response")
    assert "guardrail" not in result
    assert result["final_response"] == "done"
    tool_contents = [m["content"] for m in result["messages"] if m.get("role") == "tool"]
    assert any("repeated_exact_failure_warning" in content for content in tool_contents)


def test_config_enabled_hard_stop_run_conversation_returns_controlled_guardrail_halt_without_top_level_error():
    agent = _make_agent("web_search", max_iterations=10, config=_hard_stop_config())
    same_args = {"query": "same"}
    responses = [
        _mock_response(
            content="",
            finish_reason="tool_calls",
            tool_calls=[_mock_tool_call("web_search", json.dumps(same_args), f"c{i}")],
        )
        for i in range(1, 10)
    ]
    agent.client.chat.completions.create.side_effect = responses

    with (
        patch("run_agent.handle_function_call", return_value=json.dumps({"error": "boom"})) as mock_hfc,
        patch.object(agent, "_persist_session"),
        patch.object(agent, "_save_trajectory"),
        patch.object(agent, "_cleanup_task_resources"),
    ):
        result = agent.run_conversation("search repeatedly")

    assert mock_hfc.call_count == 2
    assert result["api_calls"] == 3
    assert result["api_calls"] < agent.max_iterations
    assert result["turn_exit_reason"] == "guardrail_halt"
    assert "error" not in result
    assert result["completed"] is True
    assert "stopped retrying" in result["final_response"]
    assert result["guardrail"]["code"] == "repeated_exact_failure_block"
    assert result["guardrail"]["tool_name"] == "web_search"

    assistant_tool_calls = [m for m in result["messages"] if m.get("role") == "assistant" and m.get("tool_calls")]
    for assistant_msg in assistant_tool_calls:
        call_ids = [tc["id"] for tc in assistant_msg["tool_calls"]]
        following_results = [m for m in result["messages"] if m.get("role") == "tool" and m.get("tool_call_id") in call_ids]
        assert len(following_results) == len(call_ids)


def test_repeated_observations_still_execute_and_replay_original(tmp_path):
    from superforecasting_agent.storage.session import SessionDB
    agent = _make_agent('web_search')
    raw = json.dumps({'results': ['source evidence ' * 100]})
    messages = []
    with patch('run_agent.handle_function_call', return_value=raw) as execute:
        for number in range(3):
            call = _mock_tool_call('web_search', '{"query":"same"}', f'repeat-{number}')
            messages.append({'role':'assistant', 'content':'', 'tool_calls':[{'id':call.id,'type':'function','function':{'name':'web_search','arguments':call.function.arguments}}]})
            agent._execute_tool_calls_sequential(SimpleNamespace(content='', tool_calls=[call]), messages, 'references')
    assert execute.call_count == 3
    results = [m for m in messages if m['role'] == 'tool']
    assert raw in results[0]['content']
    assert all('repeat-0' in m['content'] and 'executed again' in m['content'] for m in results[1:])
    assert all(raw not in m['content'] for m in results[1:])
    db = SessionDB(db_path=tmp_path/'references.db')
    try:
        db.create_session('references', source='cli')
        db.replace_messages('references', messages)
    finally:
        db.close()
    db = SessionDB(db_path=tmp_path/'references.db')
    try:
        replay = db.get_messages_as_conversation('references')
        results = [m for m in replay if m['role']=='tool']
        assert raw in results[0]['content']
        assert 'repeat-0' in results[-1]['content']
    finally:
        db.close()


def test_concurrent_result_references_preserve_call_order_and_execute_every_call():
    agent = _make_agent('web_search')
    raw = json.dumps({'results': ['unchanged ' * 100]})
    calls = [_mock_tool_call('web_search', '{"query":"same"}', f'parallel-{i}') for i in range(2)]
    messages = []
    with patch('run_agent.handle_function_call', return_value=raw) as execute:
        agent._execute_tool_calls_concurrent(SimpleNamespace(content='',tool_calls=calls), messages, 'references')
    assert execute.call_count == 2
    assert [m['tool_call_id'] for m in messages] == ['parallel-0','parallel-1']
    assert raw in messages[0]['content']
    assert 'parallel-0' in messages[1]['content'] and raw not in messages[1]['content']


def test_agent_delegate_dispatch_forwards_images_and_background():
    agent = _make_agent('delegate_task')
    with patch('tools.delegate_tool.delegate_task', return_value='{}') as delegate:
        agent._dispatch_delegate_task({'goal':'Read chart', 'images':['chart.png'], 'background':True})
    assert delegate.call_args.kwargs['images'] == ['chart.png']
    assert delegate.call_args.kwargs['background'] is True
    assert delegate.call_args.kwargs['parent_agent'] is agent


def test_progressive_tools_reach_provider_wire_and_normal_dispatch():
    agent = _make_agent('forecast_ledger','clarify','mcp_weather_read')
    agent.tool_discovery_config = {'enabled':True}
    kwargs = agent._build_api_kwargs([{'role':'user','content':'Research'}])
    names = {entry['function']['name'] for entry in kwargs['tools']}
    assert 'forecast_ledger' in names and 'clarify' in names
    assert 'tool_call' in names and 'mcp_weather_read' not in names
    assert 'mcp_weather_read' in agent.valid_tool_names
    call = _mock_tool_call('tool_call', json.dumps({'calls':[{'name':'mcp_weather_read','arguments':{}}]}), 'bridge')
    messages = []
    with patch('run_agent.handle_function_call', return_value='{"observed": 12}') as execute:
        agent._execute_tool_calls_sequential(SimpleNamespace(content='',tool_calls=[call]), messages, 'discovery')
    assert execute.call_args.args[0] == 'mcp_weather_read'
    assert messages[0]['tool_call_id'] == 'bridge'
    assert 'untrusted_tool_result' in messages[0]['content']
    assert 'observed' in messages[0]['content']


def test_discovery_validates_whole_batch_before_effects_and_checks_real_tool_hooks():
    agent = _make_agent('mcp_weather_read')
    agent.tool_discovery_config = {'enabled':True}
    from agent.tool_discovery import execute_discovery
    with patch('run_agent.handle_function_call') as execute:
        result = execute_discovery(agent, 'tool_call', {'calls':[{'name':'mcp_weather_read','arguments':{}},{'name':'not_selected','arguments':{}}]}, 'task', 'batch', [])
        assert 'error' in json.loads(result)
        execute.assert_not_called()
    with patch('superforecasting_agent.runtime.plugins.get_pre_tool_call_block_message', return_value='Blocked by policy'), patch('run_agent.handle_function_call') as execute:
        result = execute_discovery(agent, 'tool_call', {'calls':[{'name':'mcp_weather_read','arguments':{}}]}, 'task', 'batch', [])
        assert 'Blocked by policy' in result
        execute.assert_not_called()


def test_discovery_cancellation_prevents_remaining_batch_calls():
    from agent.tool_discovery import execute_discovery
    agent = _make_agent('mcp_weather_read')
    agent.tool_discovery_config = {'enabled':True}
    def stop(*args, **kwargs):
        agent._interrupt_requested = True
        return '{"observed":12}'
    with patch('run_agent.handle_function_call', side_effect=stop) as execute:
        result = json.loads(execute_discovery(agent, 'tool_call', {'calls':[{'name':'mcp_weather_read','arguments':{}},{'name':'mcp_weather_read','arguments':{}}]}, 'task', 'batch', []))
    assert execute.call_count == 1
    assert len(result['results']) == 1 and 'interrupted' in result['error']


def test_discovery_stops_when_tool_selection_changes_mid_batch():
    from agent.tool_discovery import execute_discovery
    agent = _make_agent('mcp_weather_read')
    agent.tool_discovery_config = {'enabled':True}
    def remove(*args, **kwargs):
        agent.tools = []
        return '{"observed":12}'
    with patch('run_agent.handle_function_call', side_effect=remove) as execute:
        result = json.loads(execute_discovery(agent, 'tool_call', {'calls':[{'name':'mcp_weather_read','arguments':{}},{'name':'mcp_weather_read','arguments':{}}]}, 'task', 'batch', []))
    assert execute.call_count == 1
    assert len(result['results']) == 1 and 'selection changed' in result['error']


def test_discovery_preserves_memory_provider_tool_ownership():
    from agent.tool_discovery import execute_discovery
    agent = _make_agent('custom_memory_recall')
    agent.tool_discovery_config = {'enabled':True}
    memory = agent._memory_manager = MagicMock()
    memory.has_tool.return_value = True
    memory.handle_tool_call.return_value = '{"evidence":"retained"}'
    with patch('run_agent.handle_function_call') as registry:
        result = execute_discovery(agent, 'tool_call', {'calls':[{'name':'custom_memory_recall','arguments':{}}]}, 'task', 'batch', [])
    assert 'retained' in result
    memory.handle_tool_call.assert_called_once_with('custom_memory_recall', {})
    registry.assert_not_called()


def test_discovery_is_applied_before_each_provider_transport():
    for mode in ('chat_completions', 'anthropic_messages', 'bedrock_converse', 'codex_responses'):
        agent = _make_agent('forecast_ledger', 'clarify', 'mcp_weather_read')
        agent.tool_discovery_config = {'enabled':True}
        agent.api_mode = mode
        try:
            kwargs = agent._build_api_kwargs([{'role':'user','content':'Research'}])
            if mode == 'chat_completions':
                definitions = {tool['function']['name']: tool['function']['parameters'] for tool in kwargs['tools']}
            elif mode == 'anthropic_messages':
                definitions = {tool['name']: tool['input_schema'] for tool in kwargs['tools']}
            elif mode == 'bedrock_converse':
                definitions = {tool['toolSpec']['name']: tool['toolSpec']['inputSchema']['json'] for tool in kwargs['toolConfig']['tools']}
            else:
                definitions = {tool['name']: tool['parameters'] for tool in kwargs['tools']}
            assert {'forecast_ledger', 'clarify', 'tool_search', 'tool_describe', 'tool_call'} <= definitions.keys(), mode
            assert 'mcp_weather_read' not in definitions, mode
            assert definitions['tool_call']['properties']['calls']['type'] == 'array', mode
        finally:
            agent.close()
