"""Agent execution adapter for shared forecasting workflows."""

from __future__ import annotations

import logging
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.protocol import build_protocol_messages

logger = logging.getLogger(__name__)


def run_stage(
    ledger: ForecastLedger,
    question_id: str,
    *,
    model: str | None,
    provider: str | None,
    max_iterations: int,
    stage: str = "update",
    commit_policy: str | None = None,
    supplemental: str | None = None,
) -> dict[str, Any]:
    """Run the LLM agent for one question's pipeline stage and RETURN the structured
    result (no printing). The agent commits through the forecasting tool, whose commit
    hook writes the analyst brief — so the loop closes. Shared by `forecast agent`,
    `refresh --agent`, and background jobs. This adapter owns the stage agent
    and releases its resources on both success and failure.

    ``commit_policy="commit_material"`` commits a material move for an explicit run;
    ``"proposal_only"`` forces unattended work through review. ``supplemental`` injects a
    stage-scoped note (the chain's research re-run passes the adequacy gap list)."""
    messages = build_protocol_messages(
        ledger,
        question_id,
        stage=stage,
        commit_policy=commit_policy,
        supplemental=supplemental,
    )
    enabled_toolsets = toolsets_for_stage(stage)
    from agent.agent_factory import build_agent

    agent = build_agent(
        runtime={"provider": provider},
        model=model or "",
        max_iterations=max_iterations,
        enabled_toolsets=enabled_toolsets,
        platform="cli",
    )
    agent.forecast_commit_policy = commit_policy or ""
    try:
        return agent.run_conversation(
            messages[1].content, system_message=messages[0].content
        )
    finally:
        try:
            agent.close()
        except Exception:
            logger.exception(
                "Failed to close forecast stage agent for %s (%s)", question_id, stage
            )


def toolsets_for_stage(stage: str) -> list[str]:
    toolsets = {
        "parse": ["forecasting", "file"],
        "research": ["forecasting", "file", "web"],
        "base_rate": ["forecasting", "file", "web"],
        "model": ["forecasting", "file", "terminal"],
        "update": ["forecasting"],
        "resolve": ["forecasting", "file", "web"],
        "postmortem": ["forecasting"],
        "self_check": ["forecasting", "file", "web"],
    }
    return toolsets.get(stage, ["forecasting"])


def research_audit_round_limit() -> int:
    """Resolve the existing profile setting without changing its fallback policy."""
    from superforecasting_agent.runtime.config import cfg_get, load_config_readonly

    try:
        value = int(
            cfg_get(
                load_config_readonly(),
                "forecasting",
                "research",
                "max_audit_rounds",
                default=2,
            )
            or 0
        )
    except Exception:
        value = 2
    return max(0, value)


def build_triage_runner(*, model: str | None = None):
    """Construct the CHEAP triage auto-labeler runner + resolved model id.

    Returns ``(runner, model)`` where ``runner`` has the injected labeler shape
    ``(model, system, user) -> str``. The SAME construction the ``triage_label``
    tool action uses (``forecasting.quorum.make_aiagent_runner``), so the CLI, the
    tool, and the evidence-autopilot all label with identical wiring. Accessed via
    the ``quorum`` module (not a ``from`` import) so tests can monkeypatch
    ``forecasting.quorum.make_aiagent_runner`` like ``tests/forecasting/test_triage.py``.
    """
    from forecasting import appconfig, quorum

    configured = appconfig.get_str("FORECAST_TRIAGE_MODEL")
    if model or configured:
        resolved = model or configured
    else:
        from forecasting.quorum_autorun import resolve_active_model_id
        from superforecasting_agent.runtime.config import load_config

        resolved = (
            resolve_active_model_id(load_config().get("model"))
            or quorum.DEFAULT_JUDGE_MODEL
        )
    runner = quorum.make_aiagent_runner(
        toolsets=(), max_iterations=2, quiet=True, timeout=180
    )
    return runner, resolved
