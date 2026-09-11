import pytest

from forecasting import ForecastLedger


def test_initial_review_failure_rolls_back_question_creation(tmp_path, monkeypatch):
    ledger = ForecastLedger(tmp_path / "ledger.db")

    def fail_schedule(**kwargs):
        raise RuntimeError("schedule write interrupted")

    monkeypatch.setattr(ledger, "schedule_review", fail_schedule)
    with pytest.raises(RuntimeError, match="interrupted"):
        ledger.create_question(
            title="Will the shipment arrive?",
            resolution_criteria="YES if the official delivery report confirms arrival.",
            domain="logistics",
        )
    assert ledger.list_questions() == []
