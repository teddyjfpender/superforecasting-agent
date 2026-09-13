"""A stage's runtime owns its agent and releases it without weakening ledger gates."""

import pytest

from agent import forecast_stage
from forecasting.ledger import ForecastLedger


@pytest.mark.parametrize(
    "failure", [None, RuntimeError("provider interrupted"), KeyboardInterrupt()]
)
@pytest.mark.parametrize("close_fails", [False, True])
def test_stage_releases_agent_after_success_failure_or_interrupt(
    tmp_path, monkeypatch, failure, close_fails, caplog
):
    ledger = ForecastLedger(tmp_path / "ledger.db")
    question = ledger.create_question(
        title="Will X occur?", resolution_criteria="Resolves yes when X occurs."
    )
    events = []

    class Agent:
        def __init__(self, **kwargs):
            events.append(("constructed", kwargs))

        def run_conversation(self, user, *, system_message):
            events.append(("run", self.forecast_commit_policy))
            assert "gap list" in user + system_message
            if failure is not None:
                raise failure
            return {"final_response": "researched"}

        def close(self):
            events.append(("closed",))
            if close_fails:
                raise RuntimeError("cleanup failure")

    monkeypatch.setattr("agent.agent_factory._aiagent_cls", lambda: Agent)
    kwargs = dict(
        model="test",
        provider=None,
        max_iterations=3,
        stage="research",
        commit_policy="proposal_only",
        supplemental="gap list",
    )
    if failure is not None:
        with pytest.raises(type(failure)) as raised:
            forecast_stage.run_stage(ledger, question.id, **kwargs)
        assert raised.value is failure
    else:
        assert forecast_stage.run_stage(ledger, question.id, **kwargs) == {
            "final_response": "researched"
        }
    assert events[-1] == ("closed",)
    assert [e[0] for e in events] == ["constructed", "run", "closed"]
    assert events[0][1]["enabled_toolsets"] == ["forecasting", "file", "web"]
    assert events[1][1] == "proposal_only"
    assert ledger.get_current_snapshot(question.id) is None
    if close_fails:
        assert "Failed to close forecast stage agent" in caplog.text
        assert "cleanup failure" in caplog.text
