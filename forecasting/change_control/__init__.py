"""Authoritative ledger changesets, policy, and review state."""

from __future__ import annotations

from typing import Any

from forecasting.change_control.apply import apply_changeset
from forecasting.change_control.compatibility import sync_legacy_proposal, wrap_legacy_proposal
from forecasting.change_control.models import LedgerOperation
from forecasting.change_control.policy import classify_operations, evaluate_quorum
from forecasting.change_control.preview import preview_changeset
from forecasting.change_control.store import (
    add_operation,
    add_review,
    create_changeset,
    current_revision,
    get_changeset,
    initialize_schema,
    list_changesets,
    list_operations,
    list_reviews,
    transition_changeset,
)


class ChangeControl:
    """Small façade over the change-control functions for one ledger."""

    def __init__(self, ledger: Any) -> None:
        self.ledger = ledger
        with ledger._connect() as conn:
            initialize_schema(conn)

    def current_revision(self) -> dict[str, Any]:
        return current_revision(self.ledger)

    def create_changeset(self, **kwargs: Any) -> dict[str, Any]:
        return create_changeset(self.ledger, **kwargs)

    def get_changeset(self, changeset_id: str) -> dict[str, Any]:
        return get_changeset(self.ledger, changeset_id)

    def list_changesets(self, **kwargs: Any) -> list[dict[str, Any]]:
        return list_changesets(self.ledger, **kwargs)

    def add_operation(
        self, changeset_id: str, operation: LedgerOperation | dict[str, Any]
    ) -> dict[str, Any]:
        return add_operation(self.ledger, changeset_id, operation)

    def list_operations(self, changeset_id: str) -> list[LedgerOperation]:
        return list_operations(self.ledger, changeset_id)

    def add_review(self, changeset_id: str, **kwargs: Any) -> dict[str, Any]:
        return add_review(self.ledger, changeset_id, **kwargs)

    def list_reviews(self, changeset_id: str) -> list[dict[str, Any]]:
        return list_reviews(self.ledger, changeset_id)

    def transition(self, changeset_id: str, status: str, **kwargs: Any) -> dict[str, Any]:
        return transition_changeset(self.ledger, changeset_id, status, **kwargs)

    def quorum(self, changeset_id: str) -> Any:
        changeset = self.get_changeset(changeset_id)
        return evaluate_quorum(
            risk_tier=changeset["risk_tier"],
            reviews=self.list_reviews(changeset_id),
            changeset_digest=changeset["digest"],
            head_sha=changeset.get("head_sha"),
            author_owner_ids=changeset["author_owner_ids"],
        )

    def preview(self, changeset_id: str) -> dict[str, Any]:
        return preview_changeset(self.ledger, changeset_id)

    def apply(self, changeset_id: str) -> dict[str, Any]:
        return apply_changeset(self.ledger, changeset_id)

    def wrap_legacy_proposal(self, proposal_id: str, **kwargs: Any) -> dict[str, Any]:
        return wrap_legacy_proposal(self.ledger, proposal_id, **kwargs)

    def sync_legacy_proposal(self, changeset_id: str, **kwargs: Any) -> dict[str, Any] | None:
        return sync_legacy_proposal(self.ledger, changeset_id, **kwargs)


__all__ = [
    "ChangeControl",
    "LedgerOperation",
    "apply_changeset",
    "classify_operations",
    "evaluate_quorum",
    "preview_changeset",
    "sync_legacy_proposal",
    "wrap_legacy_proposal",
]
