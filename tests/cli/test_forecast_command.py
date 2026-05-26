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


def test_questions_slash_command_prints_headline_rows_without_ids(tmp_path, capsys, monkeypatch):
    from cli import HermesCLI
    from forecasting import ForecastLedger

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db_path))
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will questions slash show headline values?",
        resolution_criteria="Resolved yes if /questions lists this forecast.",
        close_time="2026-06-30T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.62,
        rationale="Initial probability.",
        as_of="2026-05-24T00:00:00Z",
        confidence=0.7,
    )

    HermesCLI._handle_forecast_book_command(cli, "/questions")

    output = capsys.readouterr().out
    assert "FORECAST QUESTIONS" in output
    assert "Row" in output
    assert "Freshness" in output
    assert "Will questions slash show headline values?" in output
    assert "0.620" in output
    assert "Open details with /questions <row>" in output


def test_book_alias_opens_numbered_forecast_without_id(tmp_path, capsys, monkeypatch):
    from cli import HermesCLI
    from forecasting import ForecastLedger

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db_path))
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will book alias open details?",
        resolution_criteria="Resolved yes if /book 1 opens this forecast.",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.62,
        rationale="Initial probability.",
    )

    HermesCLI._handle_forecast_book_command(cli, "/book 1")

    output = capsys.readouterr().out
    assert "Will book alias open details?" in output
    assert "0.620" in output
