"""Tests for the VOI-driven desk attention ranking.

The score answers value-of-information ("what should I touch next?"): an additive
BASE every question earns (cadence-relative staleness + resolution/review proximity
+ open-alert pressure) times a thesis-sensitivity AMPLIFIER for the members whose
±2pp move swings a thesis event, dampened when the question has no watched sources.
These pin the three invariants the coordinator required plus payload conformance.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from forecasting.dashboard import (
    _attach_voi,
    _cadence_days,
    _voi_for_forecast,
    _voi_sensitivity_map,
    build_workspace_payload,
)
from forecasting.ledger import ForecastLedger

NOW = datetime(2026, 7, 5, tzinfo=timezone.utc)


def _fc(**kw):
    """A minimal workspace-forecast dict (only the fields VOI reads)."""
    base = {
        "id": kw.get("id", "q"),
        "title": kw.get("title", "Q"),
        "as_of": None,
        "review_cadence": "weekly",
        "resolution_time": None,
        "close_time": None,
        "next_review_at": None,
        "src_count": 2,
        "open_alert_count": 0,
    }
    base.update(kw)
    return base


def _thesis(member_deltas: dict[str, float], *, tid="t1", title="Senate majority"):
    """A thesis payload dict carrying stored per-member event sensitivities."""
    return {
        "id": tid,
        "title": title,
        "event_detail": {
            "sensitivities": [
                {"member_id": mid, "delta_p_event": d} for mid, d in member_deltas.items()
            ]
        },
    }


# ── _cadence_days ─────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "cadence,days",
    [
        ("daily", 1.0), ("1d", 1.0), ("weekly", 7.0), ("1w", 7.0),
        ("monthly", 30.0), ("2w", 14.0), ("3d", 3.0), ("12h", 0.5),
        ("every 2 weeks", 14.0), (None, 7.0), ("nonsense", 7.0),
    ],
)
def test_cadence_days_vocabulary(cadence, days):
    assert _cadence_days(cadence) == pytest.approx(days)


# ── Invariant 1: cadence-relative staleness ───────────────────────────────────


def test_staleness_is_relative_to_own_cadence():
    """A weekly question 6d old is due; a monthly one 6d old is not — so the weekly
    one must score higher on staleness even though raw age is identical."""
    weekly = _fc(id="w", as_of="2026-06-29T00:00:00Z", review_cadence="weekly")  # 6d
    monthly = _fc(id="m", as_of="2026-06-29T00:00:00Z", review_cadence="monthly")  # 6d
    vw = _voi_for_forecast(weekly, {}, NOW)
    vm = _voi_for_forecast(monthly, {}, NOW)
    assert vw["components"]["staleness"]["ratio"] > vm["components"]["staleness"]["ratio"]
    assert vw["score"] > vm["score"]
    # The weekly one is ~due (ratio ~0.86); the monthly one is early (ratio ~0.2).
    assert vw["components"]["staleness"]["ratio"] == pytest.approx(6 / 7, abs=0.02)
    assert vm["components"]["staleness"]["ratio"] == pytest.approx(6 / 30, abs=0.02)


# ── Invariant 2: a stale, near-resolution NON-thesis question outranks a fresh,
#    low-value thesis member (the additive base earns rank, sensitivity only amps) ─


def test_stale_nonthesis_outranks_fresh_thesis_member():
    stale_nonmember = _fc(
        id="stale", as_of="2026-06-21T00:00:00Z", review_cadence="weekly",  # 14d, 2x cadence
        resolution_time="2026-07-09T00:00:00Z",  # resolves in 4d
    )
    fresh_member = _fc(id="fresh", as_of="2026-07-05T00:00:00Z", review_cadence="weekly")  # fresh
    theses = [_thesis({"fresh": 0.08})]  # the fresh member hugely swings the thesis
    forecasts = [fresh_member, stale_nonmember]
    _attach_voi(forecasts, theses, NOW)
    assert stale_nonmember["voi"]["score"] > fresh_member["voi"]["score"]
    assert stale_nonmember["voi"]["rank"] < fresh_member["voi"]["rank"]
    # The fresh member's sensitivity is real but its base is ~0 → amplifying 0 is 0.
    assert fresh_member["voi"]["components"]["sensitivity"]["abs_pp"] == pytest.approx(8.0)
    assert fresh_member["voi"]["components"]["base"] == pytest.approx(0.0, abs=1e-9)


def test_sensitivity_amplifies_an_equally_stale_member():
    """Between two equally stale, in-play questions, the thesis mover ranks higher —
    the amplifier tilts the ranking without ever manufacturing base value."""
    plain = _fc(id="plain", as_of="2026-06-21T00:00:00Z")  # 14d stale
    mover = _fc(id="mover", as_of="2026-06-21T00:00:00Z")  # 14d stale, moves a thesis
    theses = [_thesis({"mover": 0.10})]
    forecasts = [plain, mover]
    _attach_voi(forecasts, theses, NOW)
    assert mover["voi"]["score"] > plain["voi"]["score"]
    assert mover["voi"]["components"]["amplifier"] > 1.0
    assert plain["voi"]["components"]["amplifier"] == pytest.approx(1.0)


# ── Invariant 3: the add_sources split (no watched sources → U re-pools nothing) ─


def test_no_sources_routes_to_add_sources_not_update():
    sourced = _fc(id="sourced", as_of="2026-06-21T00:00:00Z", src_count=3)  # stale, fuelled
    dry = _fc(id="dry", as_of="2026-06-21T00:00:00Z", src_count=0)  # stale, no fuel
    vs = _voi_for_forecast(sourced, {}, NOW)
    vd = _voi_for_forecast(dry, {}, NOW)
    assert vs["action"] == "update"
    assert vd["action"] == "add_sources"
    assert "re-pool nothing" in vd["reason"]
    # A no-source question is dampened so it ranks below an equally-stale fuelled one.
    assert vd["components"]["readiness"]["dampen"] < 1.0
    assert vd["score"] < vs["score"]


def test_resolution_due_routes_to_review_due():
    due = _fc(id="due", as_of="2026-07-04T00:00:00Z", resolution_time="2026-07-06T00:00:00Z")
    v = _voi_for_forecast(due, {}, NOW)
    assert v["action"] == "review_due"
    assert "verify the outcome" in v["reason"].lower()


def test_fresh_quiet_question_has_no_action():
    quiet = _fc(id="quiet", as_of="2026-07-05T00:00:00Z")  # fresh, nothing pending
    v = _voi_for_forecast(quiet, {}, NOW)
    assert v["action"] == "none"


# ── _voi_sensitivity_map keeps the biggest mover across theses ────────────────


def test_sensitivity_map_takes_the_largest_absolute_mover():
    theses = [
        _thesis({"m": 0.03}, tid="t1", title="A"),
        _thesis({"m": -0.09}, tid="t2", title="B"),
    ]
    sens = _voi_sensitivity_map(theses)
    assert sens["m"]["thesis_id"] == "t2"
    assert sens["m"]["abs_delta"] == pytest.approx(0.09)
    assert sens["m"]["delta_p_event"] == pytest.approx(-0.09)


# ── next_actions: ranked, actionable-only, top-5 ──────────────────────────────


def test_next_actions_are_ranked_actionable_and_capped():
    forecasts = [
        _fc(id=f"s{i}", as_of="2026-06-01T00:00:00Z", src_count=2) for i in range(7)
    ] + [_fc(id="fresh", as_of="2026-07-05T00:00:00Z")]  # fresh → action none, excluded
    actions = _attach_voi(forecasts, [], NOW)
    assert len(actions) == 5  # capped
    assert all(a["action"] != "none" for a in actions)
    assert "fresh" not in {a["question_id"] for a in actions}
    scores = [a["score"] for a in actions]
    assert scores == sorted(scores, reverse=True)  # descending by score


# ── Integration: build_workspace_payload attaches voi + next_actions + conforms ─


def _seed(ledger: ForecastLedger, qid_title: str, *, as_of: str, sources: int) -> str:
    q = ledger.create_question(
        title=qid_title,
        resolution_criteria=(
            "Resolves YES if the official certified 2026 US Senate result names the "
            "Republican as the winner by 2026-11-30."
        ),
        domain="us-politics",
        close_time="2026-11-03T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=q.id, probability_or_distribution=0.5, rationale="seed", as_of=as_of
    )
    for i in range(sources):
        ledger.add_watched_source(scope_type="question", scope_ref=q.id, source=f"fred:{q.id}:{i}")
    return q.id


def test_workspace_payload_carries_voi_and_next_actions(tmp_path):
    from protocol import RPC_BY_METHOD

    ledger = ForecastLedger(db_path=str(tmp_path / "voi.db"))
    ledger.initialize_schema()
    stale_id = _seed(ledger, "Stale sourced race", as_of="2026-05-01T00:00:00Z", sources=2)
    dry_id = _seed(ledger, "Stale dry race", as_of="2026-05-01T00:00:00Z", sources=0)

    payload = build_workspace_payload(
        ledger=ledger, include_related=False, include_lessons=False, now="2026-07-05T00:00:00Z"
    )

    by_id = {f["id"]: f for f in payload["forecasts"]}
    for fid in (stale_id, dry_id):
        voi = by_id[fid]["voi"]
        assert set(voi) >= {"score", "rank", "action", "reason", "components"}
        assert isinstance(voi["score"], (int, float))
        assert set(voi["components"]) >= {"base", "amplifier", "staleness", "proximity", "alerts", "sensitivity", "readiness"}

    assert by_id[stale_id]["voi"]["action"] == "update"
    assert by_id[dry_id]["voi"]["action"] == "add_sources"

    # Ranks are a 1..N permutation over the whole book.
    ranks = sorted(f["voi"]["rank"] for f in payload["forecasts"])
    assert ranks == list(range(1, len(payload["forecasts"]) + 1))

    # The desk-level next_actions is present and the same server-built ranking.
    assert payload["next_actions"]
    assert payload["next_actions"][0]["question_id"] in {stale_id, dry_id}

    # Payload conformance: the real frame validates against the protocol model.
    RPC_BY_METHOD["forecast.workspace"].response.model_validate(payload)
