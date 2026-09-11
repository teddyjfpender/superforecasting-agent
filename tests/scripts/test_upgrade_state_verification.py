"""The upgrade verifier permits schema additions, never lost historical data."""
import pytest

from scripts.verify_profiles import assert_preserved


def test_added_fields_preserve_existing_provenance():
    assert_preserved(
        {"history": [{"probability": 0.7, "source": "fixture"}]},
        {"history": [{"probability": 0.7, "source": "fixture", "revision": 1}], "schema": 2},
    )


@pytest.mark.parametrize(
    "after",
    [
        {},
        {"history": []},
        {"history": [{"probability": 0.8, "source": "fixture"}]},
        {"history": [{"probability": 0.7, "source": "different"}]},
        {"history": [{"probability": "0.7", "source": "fixture"}]},
    ],
)
def test_missing_changed_or_retyped_state_fails(after):
    with pytest.raises(AssertionError, match="history"):
        assert_preserved({"history": [{"probability": 0.7, "source": "fixture"}]}, after)


def test_boolean_is_not_accepted_as_numeric_state():
    with pytest.raises(AssertionError):
        assert_preserved({"count": 1}, {"count": True})
