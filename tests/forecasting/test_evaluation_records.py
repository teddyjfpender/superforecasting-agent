"""The study must evaluate the original forecast, never a later update or inferred outcome."""
from forecasting import ForecastLedger
from forecasting.evaluation import market_evaluation_records
from forecasting.market_nightly import record_pending, score_matured, market_nightly_report


def test_exact_snapshot_resolution_and_baseline_pair(tmp_path):
    ledger = ForecastLedger(tmp_path / 'study.db')
    run = record_pending(ledger, [{'id': 'market', 'question': 'Will the release ship?', 'probability': .7,
                                 'close_time': '2026-06-15T00:00:00Z'}],
                         '2026-06-01T00:00:00Z', lambda m: .5)
    row = run.recorded[0]
    ledger.create_snapshot(question_id=row['question_id'], probability_or_distribution=.9,
                           rationale='Later exploratory estimate.', forecast_origin='exploratory')
    ledger.resolve_question(question_id=row['question_id'], outcome='no')
    score_matured(ledger, now='2026-07-01T00:00:00Z')
    with ledger._connect() as conn:
        result, = market_evaluation_records(conn)
    assert result['forecast_id'] == row['forecast_id']
    assert result['agent_p'] == .5
    assert result['outcome'] == 0  # .25 Brier cannot tell yes from no at p=.5
    assert result['exclusion_reason'] is None
    assert result['baseline_id'] == row['baseline_id']
    with ledger._connect() as conn:
        conn.execute("UPDATE score_records SET audit_quarantine_reason='invalid settlement' WHERE id=?",
                     (result['market_score_id'],))
        rejected, = market_evaluation_records(conn)
    assert rejected['outcome'] is None
    assert rejected['exclusion_reason'] == 'missing_or_mismatched_score_pair'
    assert market_nightly_report(ledger)['n_scored'] == 0
