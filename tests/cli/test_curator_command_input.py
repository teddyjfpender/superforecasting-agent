"""Invalid slash-command quoting must leave the interactive session usable."""
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from cli import ForecastCLI


@pytest.mark.parametrize("command", ['/curator run "unfinished', "/curator run 'unfinished"])
def test_curator_bad_quoting_reports_error(command, monkeypatch, capsys):
    from superforecasting_agent.runtime import curator
    handler = Mock()
    monkeypatch.setattr(curator, "cli_main", handler)
    ForecastCLI._handle_curator_command(SimpleNamespace(), command)
    assert "curator: No closing quotation" in capsys.readouterr().out
    handler.assert_not_called()


@pytest.mark.parametrize("command,args", [("/curator", ["status"]), ('/curator run "two words"', ["run", "two words"])])
def test_curator_valid_input_preserves_arguments(command, args, monkeypatch):
    from superforecasting_agent.runtime import curator
    handler = Mock()
    monkeypatch.setattr(curator, "cli_main", handler)
    ForecastCLI._handle_curator_command(SimpleNamespace(), command)
    handler.assert_called_once_with(args)
