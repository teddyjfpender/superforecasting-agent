from unittest.mock import MagicMock, patch

from cli import HermesCLI


class _InsightsEngineStub:
    calls = []

    def __init__(self, db):
        self.db = db

    def generate(self, *, days=30, source=None):
        self.calls.append({"days": days, "source": source})
        return {"days": days, "source": source}

    def format_terminal(self, report):
        return f"days={report['days']} source={report['source']}"


def _run_show_insights(command: str):
    cli_obj = HermesCLI.__new__(HermesCLI)
    db = MagicMock()
    _InsightsEngineStub.calls = []
    with patch("superforecasting_agent.storage.session.SessionDB", return_value=db), \
         patch("agent.insights.InsightsEngine", _InsightsEngineStub):
        cli_obj._show_insights(command)
    return _InsightsEngineStub.calls, db


def test_cli_insights_accepts_positional_days(capsys):
    calls, db = _run_show_insights("/insights 7")

    assert calls == [{"days": 7, "source": None}]
    db.close.assert_called_once()
    assert "days=7 source=None" in capsys.readouterr().out


def test_cli_insights_keeps_days_flag_and_source(capsys):
    calls, db = _run_show_insights("/insights --days 14 --source discord")

    assert calls == [{"days": 14, "source": "discord"}]
    db.close.assert_called_once()
    assert "days=14 source=discord" in capsys.readouterr().out


def test_cli_insights_closes_database_when_generation_fails(capsys):
    db = MagicMock()
    with patch("superforecasting_agent.storage.session.SessionDB", return_value=db), \
         patch("agent.insights.InsightsEngine") as engine:
        engine.return_value.generate.side_effect = RuntimeError("fixture failure")
        HermesCLI.__new__(HermesCLI)._show_insights("/insights 7")
    db.close.assert_called_once_with()
    assert "fixture failure" in capsys.readouterr().out


def test_messaging_insights_closes_database_when_generation_fails():
    import asyncio
    from types import SimpleNamespace
    from gateway.run import GatewayRunner

    db = MagicMock()
    event = SimpleNamespace(get_command_args=lambda: "—days 7")
    with patch("superforecasting_agent.storage.session.SessionDB", return_value=db), \
         patch("agent.insights.InsightsEngine") as engine:
        engine.return_value.generate.side_effect = RuntimeError("fixture failure")
        result = asyncio.run(GatewayRunner._handle_insights_command(None, event))
    db.close.assert_called_once_with()
    engine.return_value.generate.assert_called_once_with(days=7, source=None)
    assert "fixture failure" in result
