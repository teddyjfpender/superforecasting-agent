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


def test_questions_slash_command_searches_forecasts_by_words(tmp_path, capsys, monkeypatch):
    from cli import HermesCLI
    from forecasting import ForecastLedger

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db_path))
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will CPI inflation exceed consensus?",
        resolution_criteria="Resolved yes if the next official CPI release is above the published consensus estimate.",
        close_time="2026-06-30T00:00:00Z",
        domain="macro",
        topics=["inflation", "energy"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.61,
        rationale="Initial probability.",
        confidence=0.62,
    )
    ledger.create_question(
        title="Will company Y default?",
        resolution_criteria="Resolved yes if company Y enters default before the close date.",
        domain="credit",
    )

    HermesCLI._handle_forecast_book_command(cli, "/questions inflation energy")

    output = capsys.readouterr().out
    assert "FORECAST SEARCH" in output
    assert "Will CPI inflation exceed consensus?" in output
    assert "Will company Y default?" not in output
    assert "Open one match with /open" in output


def test_forecast_lookup_shortcuts_resolve_words_before_ledger_actions(tmp_path, capsys, monkeypatch):
    from cli import HermesCLI
    from forecasting import ForecastLedger

    cli = HermesCLI.__new__(HermesCLI)
    db_path = tmp_path / "forecast.sqlite"
    monkeypatch.setenv("FORECAST_LEDGER_DB", str(db_path))
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will CPI inflation exceed consensus?",
        resolution_criteria="Resolved yes if the next official CPI release is above the published consensus estimate.",
        close_time="2026-06-30T00:00:00Z",
        domain="macro",
        topics=["inflation", "energy"],
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.61,
        rationale="Initial probability.",
        confidence=0.62,
    )

    HermesCLI._handle_forecast_open_command(cli, "/open inflation")
    assert "Will CPI inflation exceed consensus?" in capsys.readouterr().out

    HermesCLI._handle_forecast_evidence_for_command(
        cli,
        "/evidence-for inflation -- BLS release mentioned gasoline pressure",
    )
    evidence = ledger.list_evidence(question.id)
    assert len(evidence) == 1
    assert evidence[0].summary == "BLS release mentioned gasoline pressure"

    HermesCLI._handle_forecast_update_for_command(
        cli,
        '/update-for inflation -- --probability 0.64 --rationale "energy evidence moved up"',
    )
    snapshot = ledger.get_current_snapshot(question.id)
    assert snapshot is not None
    assert snapshot.probability_or_distribution == 0.64
    assert snapshot.rationale == "energy evidence moved up"
