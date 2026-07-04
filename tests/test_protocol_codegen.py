"""Golden-file + determinism tests for the protocol TypeScript codegen (Arc A1).

The golden test IS the staleness gate in pytest form: if a model changes without
regenerating ``ui-tui/src/protocol/generated.ts`` (or vice-versa) this fails with
"generated.ts is stale", the same signal ``python -m protocol.codegen --check``
emits in CI.
"""

from __future__ import annotations

from protocol import codegen


def test_generated_ts_matches_committed_file():
    path = codegen.generated_path()
    assert path.exists(), "run `python -m protocol.codegen` to create generated.ts"
    assert path.read_text(encoding="utf-8") == codegen.render(), (
        "generated.ts is STALE — run `python -m protocol.codegen` and commit it"
    )


def test_check_mode_passes_when_fresh():
    assert codegen.main(["--check"]) == 0


def test_render_is_deterministic():
    assert codegen.render() == codegen.render()


def test_render_carries_version_and_event_names():
    out = codegen.render()
    assert "export const PROTOCOL_VERSION = 1" in out
    # The event-name union is sorted and spans every registered family (A2 added
    # the gateway/turn/tool/prompt/subagent/voice/desk/markets/warnings families).
    assert "export type WireEventName = 'approval.request' | " in out
    for name in ("'pm.tick'", "'review.sweep'", "'markets.model.progress'",
                 "'forecast.warnings.automode.progress'", "'error'"):
        assert name in out
    # A representative interface with sorted members and a nullable field.
    assert "export interface PMOrderBookDTO {" in out
    assert "  best_bid: null | number" in out


def test_render_emits_wire_event_const_object():
    """Every event name is a `WireEvent.<KEY>` constant — the ONLY place a raw
    event-name literal is allowed. The TUI references these constants so a
    renamed/removed event is a compile error, never a silent miss."""

    out = codegen.render()
    assert "export const WireEvent = {" in out
    assert "} as const" in out
    # SCREAMING_SNAKE keys map to the exact wire names.
    for key, name in (
        ("GATEWAY_READY", "gateway.ready"),
        ("REVIEW_SWEEP", "review.sweep"),
        ("MARKETS_MODEL_PROGRESS", "markets.model.progress"),
        ("FORECAST_WARNINGS_AUTOMODE_ERROR", "forecast.warnings.automode.error"),
        ("ERROR", "error"),
    ):
        assert f"  {key}: '{name}'," in out
