"""Repair merged GitHub proposals without weakening ledger authority."""

from __future__ import annotations

from typing import Any, Callable

from forecasting.change_control.apply import apply_changeset
from forecasting.change_control.store import get_changeset


class MergeApplyReconciler:
    """Apply merged changesets once and retry only classified transient failures."""

    def __init__(
        self,
        ledger: Any,
        *,
        on_result: Callable[[dict[str, Any]], None] | None = None,
        max_transient_attempts: int = 5,
    ) -> None:
        self.ledger = ledger
        self.on_result = on_result
        self.max_transient_attempts = max(1, int(max_transient_attempts))

    def run(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.ledger._connect() as conn:
            rows = conn.execute(
                """SELECT id FROM ledger_changesets
                   WHERE status IN ('merged_apply_pending', 'apply_failed')
                   ORDER BY updated_at, id LIMIT ?""",
                (max(1, min(int(limit), 1000)),),
            ).fetchall()
        return [self.reconcile(row["id"]) for row in rows]

    def reconcile(self, changeset_id: str) -> dict[str, Any]:
        changeset = get_changeset(self.ledger, changeset_id)
        if changeset["status"] == "applied":
            result = {"changeset_id": changeset_id, "state": "applied", "duplicate": True}
            self._notify(result)
            return result
        attempts = self._attempts(changeset_id)
        if changeset["status"] == "apply_failed":
            latest = attempts[0] if attempts else None
            if latest is None or not str(latest.get("diagnostic") or "").startswith("transient:"):
                result = {
                    "changeset_id": changeset_id,
                    "state": "blocked",
                    "reason": "semantic_failure_requires_superseding_changeset",
                }
                self._notify(result)
                return result
            transient_count = sum(
                str(row.get("diagnostic") or "").startswith("transient:") for row in attempts
            )
            if transient_count >= self.max_transient_attempts:
                result = {
                    "changeset_id": changeset_id,
                    "state": "blocked",
                    "reason": "transient_retry_limit_reached",
                }
                self._notify(result)
                return result
        try:
            apply_result = apply_changeset(self.ledger, changeset_id)
        except Exception:
            refreshed = get_changeset(self.ledger, changeset_id)
            latest = self._attempts(changeset_id)
            diagnostic = str((latest[0] if latest else {}).get("diagnostic") or "")
            result = {
                "changeset_id": changeset_id,
                "state": refreshed["status"],
                "retryable": diagnostic.startswith("transient:"),
                "reason": "application_failed",
            }
        else:
            result = {
                "changeset_id": changeset_id,
                "state": "applied",
                "revision": apply_result.get("revision"),
                "ledger_digest": apply_result.get("ledger_digest"),
            }
        self._notify(result)
        return result

    def _attempts(self, changeset_id: str) -> list[dict[str, Any]]:
        with self.ledger._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """SELECT state, diagnostic, started_at, finished_at
                       FROM ledger_apply_attempts WHERE changeset_id = ?
                       ORDER BY started_at DESC, id DESC""",
                    (changeset_id,),
                ).fetchall()
            ]

    def _notify(self, result: dict[str, Any]) -> None:
        if self.on_result is not None:
            self.on_result(result)


__all__ = ["MergeApplyReconciler"]
