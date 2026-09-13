"""Pure summary imports must not initialize storage or presentation."""
import subprocess
import sys

import pytest

from forecasting.distribution_summary import finite_number, summarize_distribution


def test_summary_import_is_independent_in_a_fresh_process():
    result = subprocess.run([sys.executable, "-c", '''
import sys
class Deny:
    def find_spec(self, fullname, path=None, target=None):
        if any(fullname == p or fullname.startswith(p + ".") for p in (
            "forecasting.ledger", "forecasting.models", "forecasting.dashboard",
            "forecasting.cli", "agent", "tools", "tui_gateway", "gateway", "cli",
        )):
            raise AssertionError("pure summary attempted to load " + fullname)
sys.meta_path.insert(0, Deny())
from forecasting.distribution_summary import summarize_distribution
view = summarize_distribution({"mean": 4.0, "sd": 0.1})
assert view["mean"] == 4.0
assert view["ci90"] == [4.0 - 1.6449 * 0.1, 4.0 + 1.6449 * 0.1]
'''], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_public_package_exports_keep_their_original_identity():
    import forecasting
    from forecasting.ledger import ForecastLedger
    from forecasting.models import ForecastQuestion, ValidationError
    assert forecasting.ForecastLedger is ForecastLedger
    assert forecasting.ForecastQuestion is ForecastQuestion
    assert forecasting.ValidationError is ValidationError
    assert set(forecasting.__all__) <= set(dir(forecasting))
    with pytest.raises(AttributeError):
        getattr(forecasting, "unknown_export")


@pytest.mark.parametrize("value", [True, False, float("inf"), float("nan"), 10**400, "0.6"])
def test_non_numeric_or_unrepresentable_values_are_not_summary_measurements(value):
    assert finite_number(value) is None
    assert summarize_distribution({"mean": value}) is None


def test_dashboard_alias_and_ledger_interpreter_share_one_implementation():
    from forecasting.dashboard import _distribution_view
    assert _distribution_view is summarize_distribution
    # Explicit intervals take precedence over approximate normal intervals.
    value = {"mean": 4, "sd": 1, "interval_90_low": 2, "interval_90_high": 9}
    assert summarize_distribution(value)["ci90"] == [2, 9]
    assert value == {"mean": 4, "sd": 1, "interval_90_low": 2, "interval_90_high": 9}
