"""Tests for the bayes_toolkit conditional-chain primitive."""

from __future__ import annotations

import math

import pytest

from forecasting.bayes_toolkit import (
    BAYES_ACTIONS,
    ConditionalChain,
    conditional_chain,
    run_bayes_action,
)
from forecasting.models import ValidationError


def test_conditional_chain_multiplies_links_and_returns_chain_product():
    result = conditional_chain(
        [
            {"name": "A", "probability": 0.5},
            {"name": "B|A", "probability": 0.4},
            {"name": "C|A,B", "probability": 0.3},
        ],
        unconditional_estimate=0.06,
    )
    assert result.chain_product == pytest.approx(0.06, rel=1e-9)
    assert result.unconditional_estimate == pytest.approx(0.06, rel=1e-9)


def test_conditional_chain_passes_sanity_when_within_tolerance():
    result = conditional_chain(
        [{"probability": 0.2}, {"probability": 0.5}],
        unconditional_estimate=0.08,
        tolerance=2.0,
    )
    # Chain = 0.1, unconditional = 0.08, ratio = 1.25 → within 2.0× band.
    assert result.flagged is False
    assert result.flag_reason is None
    assert result.divergence_ratio == pytest.approx(0.1 / 0.08, rel=1e-9)


def test_conditional_chain_flags_when_outside_tolerance_band():
    result = conditional_chain(
        [{"probability": 0.4}, {"probability": 0.5}],
        unconditional_estimate=0.02,
        tolerance=2.0,
    )
    # Chain = 0.2, unconditional = 0.02 → 10× above.
    assert result.flagged is True
    assert "10.00x above" in result.flag_reason


def test_conditional_chain_flags_when_chain_far_below_unconditional():
    result = conditional_chain(
        [{"probability": 0.01}],
        unconditional_estimate=0.5,
        tolerance=2.0,
    )
    # Chain 0.01 is 50× below unconditional 0.5.
    assert result.flagged is True
    assert "below" in result.flag_reason


def test_conditional_chain_near_zero_uses_absolute_floor():
    # Chain is tiny but matches unconditional → not flagged.
    near_zero = conditional_chain(
        [{"probability": 0.0001}, {"probability": 0.0001}],
        unconditional_estimate=1e-8,
        tolerance=2.0,
        absolute_floor=1e-6,
    )
    assert near_zero.flagged is False
    # Chain tiny but unconditional 100× larger and above floor → flagged.
    far = conditional_chain(
        [{"probability": 1e-8}],
        unconditional_estimate=0.01,
        tolerance=2.0,
        absolute_floor=1e-4,
    )
    assert far.flagged is True


def test_conditional_chain_requires_at_least_one_link():
    with pytest.raises(ValidationError):
        conditional_chain([], unconditional_estimate=0.1)


def test_conditional_chain_rejects_tolerance_at_or_below_one():
    with pytest.raises(ValidationError):
        conditional_chain([{"probability": 0.5}], unconditional_estimate=0.5, tolerance=1.0)


def test_conditional_chain_rejects_link_without_probability():
    with pytest.raises(ValidationError):
        conditional_chain(
            [{"name": "A"}],
            unconditional_estimate=0.1,
        )


def test_conditional_chain_rejects_link_with_invalid_probability():
    with pytest.raises(ValidationError):
        conditional_chain(
            [{"probability": 1.5}],
            unconditional_estimate=0.1,
        )


def test_conditional_chain_accepts_probability_aliases():
    result = conditional_chain(
        [{"p": 0.6}, {"prob": 0.5}],
        unconditional_estimate=0.3,
    )
    assert result.chain_product == pytest.approx(0.3, rel=1e-9)


def test_conditional_chain_preserves_link_metadata_in_output():
    result = conditional_chain(
        [
            {
                "name": "step1",
                "condition": "Russia uses tactical nuke",
                "probability": 0.05,
                "rationale": "expert panel median",
            }
        ],
        unconditional_estimate=0.05,
        target_name="Nuclear strike in city X",
    )
    payload = result.to_dict()
    assert payload["target_name"] == "Nuclear strike in city X"
    assert payload["links"][0]["condition"] == "Russia uses tactical nuke"
    assert payload["links"][0]["rationale"] == "expert panel median"


def test_conditional_chain_to_text_marks_flag_visibly():
    result = conditional_chain(
        [{"probability": 0.5}, {"probability": 0.5}],
        unconditional_estimate=0.05,
    )
    text = result.to_text()
    assert "Chain product:" in text
    assert "Unconditional sanity-check:" in text
    assert "FLAGGED" in text


def test_conditional_chain_to_text_says_sanity_check_passes():
    result = conditional_chain(
        [{"probability": 0.5}],
        unconditional_estimate=0.5,
    )
    text = result.to_text()
    assert "passes" in text


def test_conditional_chain_to_dict_includes_log_chain_product():
    result = conditional_chain(
        [{"probability": 0.1}, {"probability": 0.1}],
        unconditional_estimate=0.01,
    )
    payload = result.to_dict()
    assert payload["log_chain_product"] == pytest.approx(math.log(0.01), abs=1e-3)


# ---------- dispatch via run_bayes_action ----------


def test_bayes_actions_advertises_conditional_chain():
    assert "conditional_chain" in BAYES_ACTIONS
    assert "unconditional_estimate" in BAYES_ACTIONS["conditional_chain"]


def test_run_bayes_action_dispatches_conditional_chain():
    out = run_bayes_action(
        "conditional_chain",
        {
            "target_name": "Test event",
            "links": [{"probability": 0.5}, {"probability": 0.4}],
            "unconditional_estimate": 0.18,
        },
    )
    assert out["action"] == "conditional_chain"
    assert out["result"]["chain_product"] == pytest.approx(0.2, rel=1e-3)
    assert out["result"]["unconditional_estimate"] == pytest.approx(0.18, rel=1e-3)
    assert "Chain product" in out["rationale"]


def test_run_bayes_action_chain_alias_works():
    out = run_bayes_action(
        "chain",
        {
            "links": [{"probability": 0.5}],
            "unconditional_estimate": 0.5,
        },
    )
    assert out["action"] == "chain"
    assert out["result"]["flagged"] is False


def test_run_bayes_action_requires_unconditional_estimate():
    with pytest.raises(ValidationError) as exc:
        run_bayes_action(
            "conditional_chain",
            {"links": [{"probability": 0.5}]},
        )
    assert "unconditional_estimate" in str(exc.value)


def test_run_bayes_action_accepts_unconditional_aliases():
    out = run_bayes_action(
        "conditional_chain",
        {
            "links": [{"probability": 0.5}],
            "unconditional": 0.5,
        },
    )
    assert out["result"]["unconditional_estimate"] == pytest.approx(0.5, rel=1e-9)


def test_run_bayes_action_respects_custom_tolerance():
    payload = {
        "links": [{"probability": 0.5}, {"probability": 0.5}],
        "unconditional_estimate": 0.1,
        # 0.25 / 0.1 = 2.5 — outside default 2.0, inside 3.0
        "tolerance": 3.0,
    }
    out = run_bayes_action("conditional_chain", payload)
    assert out["result"]["flagged"] is False
    payload["tolerance"] = 2.0
    out2 = run_bayes_action("conditional_chain", payload)
    assert out2["result"]["flagged"] is True


def test_run_bayes_action_unknown_action_lists_conditional_chain():
    with pytest.raises(ValidationError) as exc:
        run_bayes_action("nope", {})
    assert "conditional_chain" in str(exc.value)


def test_dataclass_returned_type():
    result = conditional_chain(
        [{"probability": 0.5}],
        unconditional_estimate=0.5,
    )
    assert isinstance(result, ConditionalChain)
