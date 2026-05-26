import json


def test_forecast_slash_command_delegates_to_forecast_cli(tmp_path, capsys):
    from cli import HermesCLI

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"

    HermesCLI._handle_forecast_command(
        cli,
        f"/forecast --db {db_path} status --json",
    )

    payload = json.loads(capsys.readouterr().out)
    assert payload["slug"] == "superforecasting-agent"
    assert payload["ledger_path"] == str(db_path)


def test_book_slash_command_opens_numbered_forecast_without_id(tmp_path, capsys, monkeypatch):
    from cli import HermesCLI
    from forecasting import ForecastLedger

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db_path))
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will book slash open details?",
        resolution_criteria="Resolved yes if /book 1 opens this forecast.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.62,
        rationale="Initial probability.",
    )

    HermesCLI._handle_forecast_book_command(cli, "/book 1")

    output = capsys.readouterr().out
    assert "Will book slash open details?" in output
    assert "0.620" in output
