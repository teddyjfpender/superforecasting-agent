"""backfill_market_ids tool action (tools/forecast_actions/resolution.py).

Some open questions reference a market only in prose (resolution criteria) or via a
structured link, with no ``metadata.market_id`` — so the resolution detector can't
read their terminal outcome. This action infers the canonical ``<venue>:<id>`` ref
DETERMINISTICALLY (structured links first, then an UNAMBIGUOUS criteria URL; a
question with zero or >1 distinct market references is SKIPPED, never guessed) and
writes it through the gated fill-only path. These tests pin: link-based inference,
criteria-slug inference (via an injected canonicalizer, no network), the
ambiguous-skip, dry_run purity (no writes), the write gate, fill-only semantics,
and metadata preservation.
"""

from __future__ import annotations

import json

import pytest

from forecasting.ledger import ForecastLedger
from forecasting.ledger.gate import allow_ledger_writes
from forecasting.models import ForecastingError, ValidationError
import tools.forecast_actions.resolution as res

PAST = "2020-01-01T00:00:00Z"
# a generic ≥5-word auditable condition (satisfies the scoreability gate)
CRIT = "Resolves yes if the linked market settles yes."


def _ledger(tmp_path) -> ForecastLedger:
    lg = ForecastLedger(db_path=str(tmp_path / "bf.db"))
    lg.initialize_schema()
    return lg


def _fake_canon(mapping):
    """A no-network canonicalizer: (venue, url) -> ('<venue>:<id>', venue)."""
    def canon(venue, ref):
        if ref in mapping:
            return f"{venue}:{mapping[ref]}", venue
        raise ForecastingError(f"no market for {ref}")
    return canon


# ── inference: an unambiguous criteria URL (slug-based) ──────────────────────────
def test_infer_from_criteria_url(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Will the linked market settle YES?",
        resolution_criteria="Resolves yes if https://manifold.markets/alice/will-x-happen settles yes.",
        resolution_time=PAST,
    )
    url = "https://manifold.markets/alice/will-x-happen"
    monkeypatch.setattr(res, "_canonicalize_market_ref", _fake_canon({url: "QqS2cRR252"}))
    result = res._infer_market_ref(lg, lg.get_question(q.id))
    assert result["status"] == "proposed"
    assert result["market_id"] == "manifold:QqS2cRR252"
    assert result["market_source"] == "manifold"
    assert result["origin"] == "criteria_url"


# ── inference: a structured forecast-link market_id (no canonicalization) ─────────
def test_infer_from_forecast_link_market_id(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Linked via edge", resolution_criteria=CRIT, resolution_time=PAST)
    other = lg.create_question(title="Sibling target market", resolution_criteria=CRIT, resolution_time=PAST)
    lg.add_forecast_link(q.id, other.id, link_type="related", metadata={"market_id": "polymarket:0xabc"})
    # a structured ref is trusted verbatim — the canonicalizer must NOT be consulted
    def _boom(*a):
        raise AssertionError("structured ref must not hit the network")
    result = res._infer_market_ref(lg, lg.get_question(q.id), canonicalize=_boom)
    assert result["status"] == "proposed"
    assert result["market_id"] == "polymarket:0xabc"
    assert result["origin"] == "forecast_link.market_id"


# ── inference: two distinct market URLs → ambiguous, never guessed ────────────────
def test_ambiguous_two_markets_skipped(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Ambiguous",
        resolution_criteria=(
            "Resolves yes if https://manifold.markets/a/one or https://polymarket.com/market/two settles yes."
        ),
        resolution_time=PAST,
    )
    result = res._infer_market_ref(lg, lg.get_question(q.id), canonicalize=lambda *a: ("x:y", "x"))
    assert result["status"] == "skipped"
    assert "ambiguous" in result["reason"]


def test_same_url_twice_is_not_ambiguous(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="One market mentioned twice",
        resolution_criteria="Resolves yes if https://manifold.markets/a/one and https://manifold.markets/a/one/ settle yes.",
        resolution_source="https://manifold.markets/a/one",
        resolution_time=PAST,
    )
    monkeypatch.setattr(res, "_canonicalize_market_ref", _fake_canon({"https://manifold.markets/a/one": "ID1"}))
    result = res._infer_market_ref(lg, lg.get_question(q.id))
    assert result["status"] == "proposed" and result["market_id"] == "manifold:ID1"


def test_no_market_reference_skipped(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Pure metric question",
        resolution_criteria="Resolves to the https://www.bls.gov/ces/ nonfarm payroll first release.",
        resolution_time=PAST,
    )
    result = res._infer_market_ref(lg, lg.get_question(q.id))
    assert result["status"] == "skipped" and "no market reference" in result["reason"]


def test_already_has_market_id_skipped(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Already linked",
        resolution_criteria="Resolves yes if https://manifold.markets/a/one settles yes.",
        resolution_time=PAST,
        metadata={"market_id": "manifold:existing"},
    )
    result = res._infer_market_ref(lg, lg.get_question(q.id))
    assert result["status"] == "skipped" and "already" in result["reason"]


def test_unreadable_reference_skipped(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Deleted market",
        resolution_criteria="Resolves yes if https://manifold.markets/a/gone settles yes.",
        resolution_time=PAST,
    )
    monkeypatch.setattr(res, "_canonicalize_market_ref", _fake_canon({}))  # every ref fails
    result = res._infer_market_ref(lg, lg.get_question(q.id))
    assert result["status"] == "skipped" and "unreadable" in result["reason"]


# ── dry_run purity: the default reports but never writes ─────────────────────────
def test_backfill_dry_run_writes_nothing(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Dry run",
        resolution_criteria="Resolves yes if https://manifold.markets/a/one settles yes.",
        resolution_time=PAST,
    )
    monkeypatch.setattr(res, "_canonicalize_market_ref", _fake_canon({"https://manifold.markets/a/one": "ID1"}))
    out = json.loads(res.backfill_market_ids({}, lg))  # dry_run defaults True
    assert out["dry_run"] is True
    assert out["proposed_count"] == 1 and out["written_count"] == 0
    assert out["proposals"][0]["written"] is False
    # nothing persisted
    assert "market_id" not in (lg.get_question(q.id).metadata or {})


def test_backfill_apply_writes_ref(tmp_path, monkeypatch):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Apply",
        resolution_criteria="Resolves yes if https://manifold.markets/a/one settles yes.",
        resolution_time=PAST,
    )
    monkeypatch.setattr(res, "_canonicalize_market_ref", _fake_canon({"https://manifold.markets/a/one": "ID1"}))
    out = json.loads(res.backfill_market_ids({"dry_run": False}, lg))
    assert out["written_count"] == 1
    meta = lg.get_question(q.id).metadata
    assert meta["market_id"] == "manifold:ID1" and meta["market_source"] == "manifold"


# ── gated write proof: refused outside a commit context, allowed inside ──────────
def test_set_market_ref_is_gated(tmp_path, monkeypatch):
    monkeypatch.setenv("FORECAST_GATE_DIRECT_WRITES", "on")  # re-enable (conftest defaults off)
    lg = _ledger(tmp_path)
    with allow_ledger_writes("setup"):
        q = lg.create_question(title="Gated", resolution_criteria=CRIT, resolution_time=PAST)
    with pytest.raises(ForecastingError):
        lg.set_question_market_ref(q.id, market_id="manifold:abc", market_source="manifold")
    with allow_ledger_writes("write"):
        lg.set_question_market_ref(q.id, market_id="manifold:abc", market_source="manifold")
    assert lg.get_question(q.id).metadata["market_id"] == "manifold:abc"


def test_set_market_ref_is_fill_only_and_idempotent(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Fill only", resolution_criteria=CRIT, resolution_time=PAST)
    lg.set_question_market_ref(q.id, market_id="manifold:abc", market_source="manifold")
    # identical ref → idempotent no-op
    lg.set_question_market_ref(q.id, market_id="manifold:abc", market_source="manifold")
    assert lg.get_question(q.id).metadata["market_id"] == "manifold:abc"
    # a DIFFERENT ref → refused (never silently overwrites)
    with pytest.raises(ValidationError):
        lg.set_question_market_ref(q.id, market_id="manifold:other", market_source="manifold")


def test_set_market_ref_rejects_non_canonical(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(title="Bad ref", resolution_criteria=CRIT, resolution_time=PAST)
    with pytest.raises(ValidationError):
        lg.set_question_market_ref(q.id, market_id="not-a-venue-ref", market_source="")


def test_set_market_ref_preserves_other_metadata(tmp_path):
    lg = _ledger(tmp_path)
    q = lg.create_question(
        title="Keep meta", resolution_criteria=CRIT, resolution_time=PAST,
        metadata={"market_nightly": True, "as_of": "2026-06-01T00:00:00Z"},
    )
    lg.set_question_market_ref(q.id, market_id="manifold:abc", market_source="manifold")
    meta = lg.get_question(q.id).metadata
    assert meta["market_nightly"] is True and meta["as_of"] == "2026-06-01T00:00:00Z"
    assert meta["market_id"] == "manifold:abc"
