"""Batch workers preserve explicit configuration through the shared factory."""

from unittest.mock import MagicMock


def test_worker_uses_explicit_configuration_without_provider_resolution(monkeypatch):
    import superforecasting_agent.trajectories.batch_worker as batch
    from agent import agent_factory

    agent = MagicMock()
    agent.run_conversation.return_value = {
        "messages": [], "completed": True, "api_calls": 1,
    }
    agent._convert_to_trajectory_format.return_value = []
    constructor = MagicMock(return_value=agent)
    monkeypatch.setattr("superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider",
                        MagicMock(side_effect=AssertionError("unexpected provider resolution")))
    monkeypatch.setattr(agent_factory, "_aiagent_cls", lambda: constructor)
    monkeypatch.setattr(batch, "AIAgent", MagicMock(side_effect=AssertionError("bypassed factory")), raising=False)
    monkeypatch.setattr(batch, "sample_toolsets_from_distribution", lambda _: ["web"])
    config = {
        "distribution": "research", "model": "fixture-model",
        "api_key": "fixture-key", "base_url": "https://fixture.invalid/v1",
        "max_iterations": 3,
    }

    result = batch._process_single_prompt(7, {"prompt": "fixture question"}, 2, config)

    assert result["success"] is True
    kwargs = constructor.call_args.kwargs
    assert kwargs["model"] == config["model"]
    assert kwargs["api_key"] == config["api_key"]
    assert kwargs["base_url"] == config["base_url"]
    assert kwargs["enabled_toolsets"] == ["web"]
    assert kwargs["skip_memory"] is True
    assert kwargs["skip_context_files"] is True
    agent.run_conversation.assert_called_once_with("fixture question", task_id="task_7")


def test_list_distributions_does_not_require_a_dataset(capsys):
    from superforecasting_agent.trajectories.batch import main

    main(list_distributions=True)

    output = capsys.readouterr().out
    assert "Available Toolset Distributions" in output
    assert "research" in output
    assert "--dataset_file is required" not in output
