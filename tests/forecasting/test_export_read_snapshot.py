"""Exports must represent one revision even when another instance updates it."""
import json

import pytest

from forecasting import ForecastLedger


@pytest.mark.parametrize("portfolio", [False, True])
def test_export_uses_one_revision_during_concurrent_update(tmp_path, monkeypatch, portfolio):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    writer = ForecastLedger(ledger.db_path)
    question = ledger.create_question(title='Synthetic?', resolution_criteria='Resolves YES if the stated event occurs by the deadline per the official source, else NO.')
    original = ledger.create_snapshot(question_id=question.id, probability_or_distribution=0.2, rationale='Before export')
    get_question = ledger.get_question
    changed = False

    def read_and_update(question_id):
        nonlocal changed
        result = get_question(question_id)
        if not changed:
            changed = True
            writer.create_snapshot(question_id=question.id, probability_or_distribution=0.8, rationale='Concurrent update')
        return result

    monkeypatch.setattr(ledger, 'get_question', read_and_update)
    payload = json.loads(ledger.export_all(fmt='json') if portfolio else ledger.export_question(question.id, fmt='json'))
    if portfolio:
        payload = payload['questions'][0]
    assert payload['question']['current_forecast_id'] == original.forecast_id
    assert [row['forecast_id'] for row in payload['forecast_history']] == [original.forecast_id]
    assert writer.get_current_snapshot(question.id).probability_or_distribution == 0.8


def test_question_score_filter_does_not_include_other_questions(tmp_path):
    ledger = ForecastLedger(tmp_path / 'ledger.db')
    questions = []
    for index in range(2):
        question = ledger.create_question(title=f'Synthetic {index}?', resolution_criteria='Resolves YES if the stated event occurs by the deadline per the official source, else NO.')
        ledger.create_snapshot(question_id=question.id, probability_or_distribution=0.5, rationale='Fixture')
        ledger.resolve_question(question_id=question.id, outcome=True, auto_score=True)
        questions.append(question)
    rows = ledger.list_scores(question_id=questions[0].id, include_invalidated=True)
    assert rows and {row.question_id for row in rows} == {questions[0].id}
    assert ledger.list_scores(question_id='missing') == []
