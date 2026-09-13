"""Malformed rule data produces structured issues before compilation or writes."""
import pytest

from forecasting.hooks.dsl import RuleSpec, validate_rule
from forecasting.hooks.loader import load_user_rules


@pytest.mark.parametrize(
    "change,field",
    [
        ({"id": 12}, "id"),
        ({"check": []}, "check"),
        ({"applies_to": [["domain", "politics"]]}, "applies_to"),
        ({"check": {"signal": [], "op": ">=", "value": 2}}, "check"),
        ({"check": {"signal": "components.count", "op": [], "value": 2}}, "check"),
        ({"check": {"all": [], "any": []}}, "check"),
        ({"check": {"not": {}, "signal": "components.count"}}, "check"),
    ],
)
def test_malformed_rule_fields_are_reported_and_skipped(change, field):
    raw = {"id": "fixture-rule", "check": {"signal": "components.count", "op": ">=", "value": 2}, **change}
    issues = validate_rule(RuleSpec.from_dict(raw))
    assert any(issue.field == field and issue.severity == "error" for issue in issues)
    assert load_user_rules({"rules": [raw]}) == []


@pytest.mark.parametrize("value", [True, False, "3", None, float("nan"), float("inf")])
@pytest.mark.parametrize("op", [">=", "==", "!="])
def test_numeric_predicates_require_finite_numbers(value, op):
    issues = validate_rule(RuleSpec.from_dict({
        "id": "fixture-rule",
        "check": {"signal": "components.count", "op": op, "value": value},
    }))
    assert any("finite numeric" in issue.message for issue in issues)


@pytest.mark.parametrize("value", [1, 0, "false", None])
def test_boolean_predicate_does_not_coerce_numbers_or_strings(value):
    issues = validate_rule(RuleSpec.from_dict({
        "id": "fixture-rule",
        "check": {"signal": "components.present", "op": "==", "value": value},
    }))
    assert any("boolean value" in issue.message for issue in issues)


def test_direct_compilation_cannot_bypass_validation():
    from forecasting.hooks.dsl import compile_rule

    spec = RuleSpec.from_dict({
        "id": "fixture-rule",
        "check": {"signal": "components.count", "op": ">=", "value": True},
    })
    with pytest.raises(ValueError, match="finite numeric"):
        compile_rule(spec)
