"""Conformance for the ``forecast.warnings.*`` protocol models (Arc A3).

* every registered ``forecast.warnings.*`` RPC has a request + response model;
* a REAL aggregate frame (``fold_warning_groups``, the server's actual fold) parses
  through the response model and the four operator tiers survive;
* the gateway wrapper is VALIDATE-ONLY — a drift-y response with an undeclared key
  is returned on the wire UNCHANGED (the wire can never regress), and a request that
  the handler itself rejects keeps the handler's OWN error code (no short-circuit).
"""

from __future__ import annotations

import pytest

from forecasting.warnings import fold_warning_groups
from protocol import RPC_BY_METHOD

WARNINGS_METHODS = [
    "forecast.warnings.list",
    "forecast.warnings.aggregate",
    "forecast.warnings.resolve",
    "forecast.warnings.dismiss",
    "forecast.warnings.automode.run",
]


def _real_summary() -> dict:
    return {
        "groups": [
            {"reason": "evidence_stale_30d", "kind": "reforecast", "severity": "warn",
             "recommended_action": "reforecast", "auto_resolvable": True, "count": 3,
             "scope_refs": ["q1", "q2"]},
            {"reason": "needs_score", "kind": "score", "severity": "info",
             "recommended_action": "score", "auto_resolvable": True, "count": 2,
             "scope_refs": ["q3"]},
            {"reason": "contested_label", "kind": "contested_label", "severity": "warn",
             "recommended_action": "hand-label", "auto_resolvable": False, "count": 1,
             "scope_refs": ["q4"]},
        ],
        "group_count": 3,
        "open_total": 6,
    }


@pytest.mark.parametrize("method", WARNINGS_METHODS)
def test_warnings_rpc_registered(method):
    spec = RPC_BY_METHOD[method]
    assert spec.request is not None and spec.response is not None


def test_aggregate_real_frame_validates_and_folds():
    frame = fold_warning_groups(_real_summary())
    model = RPC_BY_METHOD["forecast.warnings.aggregate"].response.model_validate(frame)
    assert model.headline.total == 6
    assert model.free.total == 2 and model.agent.total == 3 and model.manual.total == 1
    # the STALE sub-bucket is a view over the agent tier (evidence_stale_* prefix)
    assert model.agent.stale.total == 3


def test_list_frame_validates():
    frame = {
        "groups": _real_summary()["groups"],
        "group_count": 3,
        "open_total": 6,
    }
    model = RPC_BY_METHOD["forecast.warnings.list"].response.model_validate(frame)
    assert model.group_count == 3 and len(model.groups) == 3


def test_resolve_and_dismiss_frames_validate():
    resolve = {"results": [{"alert_id": "al_1", "reason": "needs_score",
                            "status": "resolved", "acknowledged": True}], "count": 1}
    RPC_BY_METHOD["forecast.warnings.resolve"].response.model_validate(resolve)
    dismiss = {"dismissed": [{"alert_id": "al_2", "reason": "x", "dismiss_ttl_days": 7}],
               "count": 1, "matched": 1}
    RPC_BY_METHOD["forecast.warnings.dismiss"].response.model_validate(dismiss)


# ── gateway wrapper: VALIDATE-ONLY (the wire can never regress) ────────────────


def test_aggregate_wrapper_returns_wire_unchanged_over_empty_ledger():
    from tui_gateway import server

    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.aggregate", "params": {}}
    )
    # empty ledger → a real, valid, zeroed aggregate; the wrapper returns it as-is
    assert resp["result"]["headline"]["total"] == 0
    assert set(resp["result"]) == {"headline", "free", "agent", "manual"}


def test_aggregate_wrapper_passes_undeclared_drift_key_through(monkeypatch):
    """A response key the model does NOT declare must survive on the wire — the
    validate-only wrapper never re-serialises this family."""
    from tui_gateway import server

    def _fake_aggregate(ledger, *, scope=None, reason=None):
        return {"headline": {"total": 0}, "free": {"total": 0, "reasons": []},
                "agent": {"total": 0, "reasons": []}, "manual": {"total": 0, "reasons": []},
                "__drift_only_key__": {"unmodelled": True}}

    monkeypatch.setattr("forecasting.warnings.aggregate_open_warnings", _fake_aggregate)
    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.aggregate", "params": {}}
    )
    assert resp["result"]["__drift_only_key__"] == {"unmodelled": True}


def test_resolve_request_missing_alert_id_keeps_handler_error_code():
    """The wrapper validates-and-logs the request but NEVER short-circuits — the
    handler's own ``5008`` (not a pydantic ``-32602``) is what the caller sees."""
    from tui_gateway import server

    resp = server.handle_request(
        {"id": "1", "method": "forecast.warnings.resolve", "params": {}}
    )
    assert resp["error"]["code"] == 5008
    assert "alert_id" in resp["error"]["message"]
