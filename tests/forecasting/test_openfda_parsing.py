from forecasting.sources.openfda import parse_openfda_drug_applications, load_openfda_drug_applications
from forecasting.models import ValidationError
import pytest


def test_dated_submissions_beat_malformed_dates_and_retained_payload_replays():
    payload = {'results': [{'application_number': 'NDA123456', 'submissions': [
        {'submission_status_date': '20260102', 'submission_status': 'AP'},
        {'submission_status_date': '99999999', 'submission_status': 'UNTRUSTED'},
        {'submission_status_date': '2025-12-31', 'submission_status': 'OLDER'},
    ]}]}
    parsed = parse_openfda_drug_applications(payload)
    assert parsed[0].latest_submission_status == 'AP'
    assert parsed[0].latest_submission_status_date == '2026-01-02T00:00:00Z'
    calls = []
    def fetch(endpoint, label):
        calls.append(endpoint)
        return payload
    assert load_openfda_drug_applications('NDA123456', _read_json_endpoint=fetch) == parsed
    assert len(calls) == 1
    assert parse_openfda_drug_applications(payload, since='2026-01-03') == []
    with pytest.raises(ValidationError):
        load_openfda_drug_applications('NDA123456', since='invalid', _read_json_endpoint=fetch)
    assert len(calls) == 1


def test_missing_submission_dates_stay_unknown():
    payload = {'results': [{'application_number': 'NDA123456', 'submissions': [{'submission_status': 'AP'}]}]}
    assert parse_openfda_drug_applications(payload)[0].latest_submission_status_date is None
    assert parse_openfda_drug_applications(payload, since='2026-01-01') == []
