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
    # The event-name union is sorted and spans every registered family (pm + jobs).
    assert (
        "export type WireEventName = "
        "'jobs.complete' | 'jobs.error' | 'jobs.progress' | 'pm.tick'" in out
    )
    # A representative interface with sorted members and a nullable field.
    assert "export interface PMOrderBookDTO {" in out
    assert "  best_bid: null | number" in out
