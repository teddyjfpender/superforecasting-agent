"""Malformed prediction entries cannot move values between choice labels."""
import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("prediction", [
    [None, 0.2, 0.8], [0.2, None, 0.8], ["invalid", 0.2, 0.8],
    [float("inf"), 0.2, 0.8],
])
def test_missing_choice_probability_does_not_shift_labels(monkeypatch, prediction):
    payload = {"id": 123, "title": "Which outcome?", "type": "multiple_choice",
               "options": ["A", "B"], "community_prediction": prediction}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args, **kwargs: payload)
    question = source_adapters.load_metaculus_question("123")
    assert question.distribution is None


@pytest.mark.parametrize("prediction", [[0.2, 0.8], ["0.2", "0.8"], [0.2, 0.8, None]])
def test_valid_choice_positions_are_preserved(monkeypatch, prediction):
    payload = {"id": 123, "title": "Which outcome?", "type": "multiple_choice",
               "options": ["A", "B"], "community_prediction": prediction}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args, **kwargs: payload)
    question = source_adapters.load_metaculus_question("123")
    assert question.distribution == {"A": 0.2, "B": 0.8}
