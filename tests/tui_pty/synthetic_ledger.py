"""Generate a synthetic forecast ledger for load-shaped tests.

Isolation is the first requirement: every function here writes to an explicit
``db_path`` you hand it, and never consults ``get_agent_home()``.  There is no
code path by which this touches an operator's real ledger.

Generation goes through the ``forecasting.ledger`` package API (``create_question``,
``create_snapshot``, ``create_alert``, ``schedule_review``, ``add_evidence``)
rather than raw SQL.  That is deliberate and it costs real time: writing rows
directly would be ~50x faster, but it would also silently drift from the schema
the moment a column moves, and a perf fixture that no longer resembles a real
ledger measures nothing.  Going through the API means a schema change either
keeps working or fails loudly here.

Two gates have to be handled to write at all:

* ``forecasting/ledger/gate.py`` refuses forecast-producing writes
  (``create_question`` / ``create_snapshot`` / ``record_panel_run``) outside a
  recognised commit context -- both by method name and by a connection-level
  SQLite authorizer, so it cannot be side-stepped with a raw connection.  The
  generator opens ``allow_ledger_writes()`` around those calls, which is the
  sanctioned path, rather than switching the gate off.
* Everything runs inside one ``ledger.transaction()`` per phase.  Without it
  each individual write opens its own connection and the fixture takes minutes
  instead of seconds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = ["LedgerSpec", "SMALL_BOOK", "LARGE_BOOK", "build_synthetic_ledger"]


@dataclass(frozen=True)
class LedgerSpec:
    """Shape of a synthetic book.  Deliberately plain ints so a failure message
    can quote the exact fixture that produced it."""

    questions: int
    snapshots_per_question: int = 3
    alerts: int = 0
    evidence_per_question: int = 2
    reviews: bool = True

    @property
    def label(self) -> str:
        return (
            f"{self.questions}q x{self.snapshots_per_question}snap "
            f"{self.alerts}alerts {self.questions * self.evidence_per_question}ev"
        )


# The pair used by the constant-connection-count test.  Their absolute sizes
# matter far less than the RATIO between them: the assertion is that the
# workspace fetch costs the SAME number of connections at both, which is what
# "no N+1" actually means.  ~8x apart is enough that any per-question query
# would show up as an ~8x difference.
SMALL_BOOK = LedgerSpec(questions=30, snapshots_per_question=3, alerts=40, evidence_per_question=2)

# Shaped after the operator's real desk at the time of writing (~1,100 open
# alerts, ~1,140 review schedules), scaled to what can be generated in a few
# seconds.  The point of the large book is to make a per-question regression
# expensive and obvious, not to reproduce production byte for byte.
LARGE_BOOK = LedgerSpec(questions=240, snapshots_per_question=3, alerts=1200, evidence_per_question=2)


def build_synthetic_ledger(db_path: str | Path, spec: LedgerSpec) -> dict[str, Any]:
    """Create a ledger at *db_path* matching *spec*; return what was written.

    Returns the realised counts (not the requested ones) so callers assert
    against what actually exists -- a fixture that silently generated half a
    book would otherwise make every downstream budget look great.
    """
    from forecasting.ledger import ForecastLedger, allow_ledger_writes
    from forecasting.models import OutcomeSpace

    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    ledger = ForecastLedger(db_path=str(db_path))

    domains = ("geopolitics", "macro", "technology", "public-health")
    question_ids: list[str] = []

    # Phase 1 + 2: questions and their snapshot history. Both are gated writes,
    # so both run inside allow_ledger_writes(); one transaction each keeps it to
    # a single connection per phase.
    with allow_ledger_writes(reason="tests/tui_pty synthetic ledger fixture"):
        with ledger.transaction():
            for i in range(spec.questions):
                question = ledger.create_question(
                    title=f"Synthetic forecast {i:04d}: will condition {i} hold?",
                    resolution_criteria=(
                        f"Resolves YES if synthetic condition {i} is met by the close time."
                    ),
                    outcome_space=OutcomeSpace(type="binary"),
                    domain=domains[i % len(domains)],
                    topics=[f"topic-{i % 11}"],
                    tags=[f"tag-{i % 7}"],
                )
                question_ids.append(question.id)

        with ledger.transaction():
            for i, question_id in enumerate(question_ids):
                for s in range(spec.snapshots_per_question):
                    ledger.create_snapshot(
                        question_id=question_id,
                        # Deterministic spread, no RNG: the same spec always
                        # produces the same book, so a count that moves is a
                        # code change and never fixture noise.
                        probability_or_distribution=0.05 + 0.09 * ((i + s) % 10),
                        rationale=(
                            f"Synthetic rationale for question {i} revision {s}. "
                            "Long enough to resemble a real desk note."
                        ),
                        method="synthetic-fixture",
                    )

    # Phase 3: ungated writes (alerts / reviews / evidence). Same transaction
    # discipline for the same reason.
    with ledger.transaction():
        for i in range(spec.alerts):
            ledger.create_alert(
                severity=("info", "warn", "critical")[i % 3],
                scope_type="question",
                scope_ref=question_ids[i % len(question_ids)],
                reason=f"synthetic alert {i}",
                recommended_action="review the synthetic condition",
            )

    if spec.reviews:
        with ledger.transaction():
            for question_id in question_ids:
                ledger.schedule_review(
                    scope_type="question", scope_ref=question_id, cadence="weekly"
                )

    with ledger.transaction():
        for i, question_id in enumerate(question_ids):
            for e in range(spec.evidence_per_question):
                ledger.add_evidence(
                    question_id=question_id,
                    source_or_note=f"synthetic source {i}.{e}",
                    claim=f"Synthetic claim {i}.{e} bearing on the question.",
                    summary="Synthetic evidence summary text for the desk detail pane.",
                )

    return {
        "db_path": str(db_path),
        "spec": spec,
        "questions": len(question_ids),
        "snapshots": len(question_ids) * spec.snapshots_per_question,
        "alerts": spec.alerts,
        "reviews": len(question_ids) if spec.reviews else 0,
        "evidence": len(question_ids) * spec.evidence_per_question,
        "db_bytes": db_path.stat().st_size if db_path.exists() else 0,
    }
