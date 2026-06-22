"""Tests for the Market Models presentation schema (forecasting.presentation)."""

from __future__ import annotations

import forecasting.presentation as P


def _ok_block(**over):
    base = {"type": "metric", "id": "m1", "label": "R2", "value": 0.87}
    base.update(over)
    return base


def test_validate_accepts_a_well_formed_presentation():
    pres = P.build_presentation(
        model_id="mm_1",
        version=1,
        title="GPU vs NVDA",
        question="how does compute drive revenue",
        blocks=[
            {"type": "narrative", "body": "The trend is strong."},
            {"type": "finding", "claim": "Compute explains most of revenue growth."},
            {"type": "regression", "r2": 0.9, "coeffs": [{"name": "flops", "value": 1.2}]},
            {"type": "metric", "label": "R2", "value": 0.9},
        ],
    )
    ok, errors = P.validate_presentation(pres)
    assert ok, errors
    assert errors == []
    # build_presentation backfills ids for blocks that lack them
    assert all(b["id"] for b in pres["blocks"])
    assert pres["schema_version"] == P.SCHEMA_VERSION


def test_validate_flags_missing_required_fields_and_bad_status():
    pres = {
        "title": "x",
        "status": "weird",
        "blocks": [
            {"type": "regression", "id": "r1"},  # missing r2 + coeffs
            {"type": "metric", "id": "m1", "label": "only-label"},  # missing value
        ],
    }
    ok, errors = P.validate_presentation(pres)
    assert not ok
    assert any("status must be one of" in e for e in errors)
    assert any("missing required field 'r2'" in e for e in errors)
    assert any("missing required field 'value'" in e for e in errors)


def test_viz_block_types_are_known_and_validated():
    # The high-fidelity chart block types are additive + known (not fallback).
    for bt in ("heatmap", "distribution", "candles", "depth", "sparkgrid"):
        assert bt in P.BLOCK_TYPES
    # Each new type hard-fails when its single required field is missing.
    for bt, field in (("heatmap", "matrix"), ("distribution", "support"), ("candles", "candles"), ("depth", "bids"), ("sparkgrid", "cells")):
        ok_x, err_x = P.validate_presentation({"title": "t", "blocks": [{"type": bt}]})
        assert not ok_x and any(field in e for e in err_x), bt
    # heatmap requires `matrix`; missing it is a hard fail (known type).
    ok, errors = P.validate_presentation({"title": "t", "blocks": [{"type": "heatmap"}]})
    assert not ok and any("matrix" in e for e in errors)
    # a well-formed heatmap + a paths-bearing fan both validate.
    ok2, _ = P.validate_presentation(
        {
            "title": "t",
            "blocks": [
                {"type": "heatmap", "matrix": [[1, 0], [0, 1]], "diverging": True},
                {"type": "fan", "x": [1, 2], "median": [0.4, 0.5], "paths": [[0.4, 0.5], [0.3, 0.6]]},
            ],
        }
    )
    assert ok2


def test_unknown_block_type_is_a_fallback_not_a_hard_failure():
    pres = P.build_presentation(
        model_id="mm_2",
        version=1,
        title="t",
        question="q",
        blocks=[{"type": "sankey", "data": [[1, 2]]}],  # not a known type
    )
    ok, errors = P.validate_presentation(pres)
    # unknown types are allowed (renderer falls back) → still ok
    assert ok
    assert any("renders as fallback" in e for e in errors)


def test_validate_rejects_non_object_and_non_list_blocks():
    ok, errors = P.validate_presentation([1, 2, 3])
    assert not ok and "must be a JSON object" in errors[0]

    ok2, errors2 = P.validate_presentation({"title": "t", "blocks": "nope"})
    assert not ok2 and any("blocks must be a list" in e for e in errors2)


def test_duplicate_block_ids_flagged():
    pres = {
        "title": "t",
        "blocks": [_ok_block(id="dup"), _ok_block(id="dup")],
    }
    ok, errors = P.validate_presentation(pres)
    assert not ok
    assert any("duplicate id 'dup'" in e for e in errors)


def test_sanitize_strips_em_dashes_in_prose():
    pres = P.build_presentation(
        model_id="mm_3",
        version=1,
        title="t",
        question="q",
        blocks=[{"type": "narrative", "body": "Revenue rose — sharply — last year."}],
        summary="A clean — summary.",
    )
    P.sanitize_presentation_prose(pres)
    assert "—" not in pres["blocks"][0]["body"]
    assert "—" not in pres["summary"]
