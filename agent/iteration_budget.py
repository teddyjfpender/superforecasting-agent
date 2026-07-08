"""Per-agent iteration budget — thread-safe consume/refund counter.

Extracted from ``run_agent.py``.  Each ``AIAgent`` instance (parent or
subagent) holds an :class:`IterationBudget`; the parent's cap comes from
``max_iterations`` (default 90), each subagent's cap comes from
``delegation.max_iterations`` (default 50).

``run_agent`` re-exports ``IterationBudget`` so existing
``from run_agent import IterationBudget`` imports keep working unchanged.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass

logger = logging.getLogger("agent.iteration_budget")

# ── The per-turn soft cap (appconfig-tunable) ────────────────────────────────
#
# Canonical key + the legacy env family it supersedes (checked front-to-back so
# an operator's explicit override wins, in a deterministic order).
MAX_TOOL_ITERATIONS_KEY = "FORECAST_AGENT_MAX_TOOL_ITERATIONS"
HARD_MULTIPLIER_KEY = "FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER"
_MAX_TOOL_ITERATIONS_ALIASES: tuple[str, ...] = (
    "SUPERFORECASTING_AGENT_MAX_ITERATIONS",
    "FORECAST_MAX_ITERATIONS",
    "HERMES_MAX_ITERATIONS",
)

# Raised from the historical 90 to 200. Rationale: a real deep-research turn —
# fan-out web searches + source fetches + adversarial verification + synthesis —
# routinely needs well over 90 tool calls in a single uninterrupted window
# (the operator's deep-research runs are the motivating case), yet rarely more
# than ~200 before a natural pause. And because hitting the cap is now a
# CHECKPOINT that continues rather than a hard stop, this number only sets how
# OFTEN the loop pauses to surface progress — not a wall the work dies against.
DEFAULT_MAX_TOOL_ITERATIONS = 200

# The absolute ceiling that still stops a genuinely runaway loop is this multiple
# of the soft cap (10× ⇒ 2000 tool calls by default). The spend caps metered by
# the policy layer are the PRIMARY governor of unattended cost; this multiple is
# the last-resort backstop that stops even an interactive run with an honest,
# key-naming message.
DEFAULT_HARD_CEILING_MULTIPLIER = 10


def _read_config_int(key: str, aliases: tuple[str, ...] = ()) -> int | None:
    """First set, integer-valued value across ``(key, *aliases)``.

    Prefers :mod:`forecasting.appconfig` (which merges the config.yaml ``env:``
    section with ``os.environ``) and falls back to ``os.environ`` when appconfig
    is unavailable. An empty or non-integer value is treated as unset (logged).
    """

    for name in (key, *aliases):
        raw: str | None = None
        try:
            from forecasting import appconfig

            raw = appconfig.get_str(name, None)
        except Exception:  # noqa: BLE001 — config is best-effort; fall back to env
            raw = None
        if raw is None:
            raw = os.getenv(name)
        if raw is None or not str(raw).strip():
            continue
        try:
            return int(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning(
                "iteration budget: %s=%r is not an integer; ignoring", name, raw
            )
    return None


def resolve_max_tool_iterations(default: int = DEFAULT_MAX_TOOL_ITERATIONS) -> int:
    """The per-turn soft cap: ``FORECAST_AGENT_MAX_TOOL_ITERATIONS`` (or a legacy
    alias), else *default* (200). Non-positive overrides fall through to *default*."""

    value = _read_config_int(MAX_TOOL_ITERATIONS_KEY, _MAX_TOOL_ITERATIONS_ALIASES)
    if value is not None and value > 0:
        return value
    return default


def resolve_hard_ceiling(soft_cap: int) -> int:
    """The absolute tool-call ceiling that still stops a runaway loop: the soft cap
    times ``FORECAST_AGENT_MAX_TOOL_ITERATIONS_HARD_MULTIPLIER`` (default 10×),
    floored at ``soft_cap + 1`` so continuation is always possible at least once."""

    mult = _read_config_int(HARD_MULTIPLIER_KEY)
    if mult is None or mult < 1:
        mult = DEFAULT_HARD_CEILING_MULTIPLIER
    return max(soft_cap + 1, soft_cap * mult)


@dataclass(frozen=True)
class CheckpointDecision:
    """The outcome of a soft-cap checkpoint: whether to continue and why.

    ``reason`` is one of ``interactive`` | ``policy_auto`` (continue) or
    ``hard_ceiling`` | ``policy_denied`` (stop).
    """

    should_continue: bool
    reason: str
    interactive: bool
    hard_ceiling: int
    config_key: str = MAX_TOOL_ITERATIONS_KEY


def decide_checkpoint_continuation(
    *,
    api_call_count: int,
    soft_cap: int,
    hard_ceiling: int,
    interactive: bool,
    policy_allows: bool,
) -> CheckpointDecision:
    """Govern a soft-cap checkpoint by the RIGHT quantity.

    The absolute ceiling always wins — even an interactive run stops there. Below
    it, an operator physically present (interactive) continues; otherwise the
    spend policy decides (``llm_spend`` auto ⇒ continue, bounded by the spend
    caps the policy layer already meters).
    """

    if api_call_count >= hard_ceiling:
        return CheckpointDecision(False, "hard_ceiling", interactive, hard_ceiling)
    if interactive:
        return CheckpointDecision(True, "interactive", interactive, hard_ceiling)
    if policy_allows:
        return CheckpointDecision(True, "policy_auto", interactive, hard_ceiling)
    return CheckpointDecision(False, "policy_denied", interactive, hard_ceiling)


class IterationBudget:
    """Thread-safe iteration counter for an agent.

    Each agent (parent or subagent) gets its own ``IterationBudget``.
    The parent's budget is capped at ``max_iterations`` (default 90).
    Each subagent gets an independent budget capped at
    ``delegation.max_iterations`` (default 50) — this means total
    iterations across parent + subagents can exceed the parent's cap.
    Users control the per-subagent limit via ``delegation.max_iterations``
    in config.yaml.

    ``execute_code`` (programmatic tool calling) iterations are refunded via
    :meth:`refund` so they don't eat into the budget.
    """

    def __init__(self, max_total: int):
        self.max_total = max_total
        self._used = 0
        self._lock = threading.Lock()

    def consume(self) -> bool:
        """Try to consume one iteration.  Returns True if allowed."""
        with self._lock:
            if self._used >= self.max_total:
                return False
            self._used += 1
            return True

    def refund(self) -> None:
        """Give back one iteration (e.g. for execute_code turns)."""
        with self._lock:
            if self._used > 0:
                self._used -= 1

    @property
    def used(self) -> int:
        with self._lock:
            return self._used

    @property
    def remaining(self) -> int:
        with self._lock:
            return max(0, self.max_total - self._used)


__all__ = [
    "IterationBudget",
    "CheckpointDecision",
    "MAX_TOOL_ITERATIONS_KEY",
    "HARD_MULTIPLIER_KEY",
    "DEFAULT_MAX_TOOL_ITERATIONS",
    "DEFAULT_HARD_CEILING_MULTIPLIER",
    "resolve_max_tool_iterations",
    "resolve_hard_ceiling",
    "decide_checkpoint_continuation",
]
