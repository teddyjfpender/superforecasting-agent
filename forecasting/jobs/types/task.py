"""The TASK job type: the operator's Desk free-text "fix loop" on the one
detached-job runtime (Arc B2).

A task job is the visibility arc's other half: the readiness composite SHOWS the
operator what a question is missing (no watched sources, no executable trigger, …),
and a task job is how they FIX it — a free-text instruction over a BATCH of
questions, run as ONE bounded, gated agent session. The session works the SAME
gated ``forecast_ledger_tool`` every commit path uses; this type only scopes it to
the composed instruction + the question list (each carrying its readiness gaps so
the agent sees WHAT is missing) and reports progress honestly. NOTHING here opens a
new write path.

:func:`execute` is a faithful lift of the old ``reforecast_jobs._execute_task_job``:
one ``run_conversation`` over the whole batch, staging started/working/done
progress notes + a final summary that is the agent's OWN ``final_response`` — never
fabricated. Honest completion: ``done`` only when the session returns; an empty
instruction, a bad db, a compose failure, or an agent raise lands ``error`` with the
reason (the runtime stamps the terminal state; the last progress note records it).

``_run_task_agent`` / ``_compose_task_prompt`` are module-level so tests can stub
them exactly as the CLI stubs ``cli._run_update_agent``.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from forecasting.jobs.types import JobType, register

# Bound the ONE agent session a task job runs (spec override). A batch chore
# ("add watched sources to these five", "set executable triggers") sweeps several
# questions in a single session, so it gets a larger default than the per-question
# reforecast leg.
DEFAULT_TASK_MAX_ITERATIONS = 20


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_task_agent(
    user_message: str,
    *,
    system_message: str,
    model: str | None,
    provider: str | None,
    max_iterations: int,
) -> dict[str, Any]:
    """Run ONE gated agent session for a Desk task job — the SAME seam
    :func:`forecasting.cli._run_update_agent` uses (the ``forecasting`` toolset
    through ``run_agent.AIAgent``), so every write still goes through the gated
    ``forecast_ledger_tool``; this only scopes the session to the composed
    instruction. Returns ``run_conversation``'s result dict. A module-level function
    so tests can stub it exactly as they stub ``cli._run_update_agent``."""
    from agent.runtime import AIAgent

    agent = AIAgent(
        model=model or "",
        provider=provider,
        max_iterations=max_iterations,
        # The forecasting toolset is the gated write path; file+web let the chore
        # do real research (import a source, add a reference class) when the
        # instruction calls for it — the same toolset a research/base_rate stage uses.
        enabled_toolsets=["forecasting", "file", "web"],
        platform="cli",
    )
    return agent.run_conversation(user_message, system_message=system_message)


def _compose_task_prompt(
    ledger: Any, instruction: str, question_ids: list[str]
) -> tuple[str, str]:
    """Build ``(system, user)`` for a task session: the forecasting-desk system
    prompt + the operator's instruction followed by the scoped question list, each
    line carrying id + title + the machine-readiness GAPS the desk is missing, so the
    agent sees exactly WHAT to fix. Read-only assembly."""
    from forecasting.protocol import SYSTEM_PROMPT
    from forecasting.readiness_lens import build_question_readiness

    lines: list[str] = []
    for qid in question_ids:
        try:
            composite = build_question_readiness(ledger, qid)
        except Exception:  # noqa: BLE001 — a bad id never aborts the compose
            lines.append(f"- {qid}")
            continue
        header = f"- {qid}"
        if composite.get("title"):
            header += f" — {composite['title']}"
        score = composite.get("score")
        if score is not None:
            header += f"  (machine-readiness {score}/100)"
        lines.append(header)
        gaps = composite.get("gaps") or []
        if not gaps:
            lines.append("    · machine-ready — no missing inputs")
        for gap in gaps:
            lines.append(f"    · MISSING {gap['label']}: {gap['fix_hint']}")

    user = (
        "## Operator task\n"
        f"{instruction.strip()}\n\n"
        "## Questions in scope\n"
        "Work through these questions. Each line lists the question id, title, and the "
        "machine-readiness gaps the autonomous desk is currently missing (watched "
        "sources, structured components, reference classes, an executable update "
        "trigger, an enabled review schedule, close_time / impact / resolution rule). "
        "Use the forecasting tools to close the gaps the instruction calls for, "
        "committing every change through the gated tool. When finished, summarise what "
        "you changed per question.\n\n" + "\n".join(lines)
    )
    return SYSTEM_PROMPT.strip(), user


def execute(spec: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """Run a task job: ONE gated agent session over the whole batch, staging
    started/working/done progress notes + a final summary of what the agent reported.

    An empty instruction, a bad db, a compose failure, or the session raising is a
    whole-job ``error`` — the last progress note records the reason, then the
    exception propagates to the runtime, which stamps ``status='error'``. The summary
    is the agent's own ``final_response`` — never fabricated."""
    from forecasting.ledger import ForecastLedger

    instruction = str(spec.get("instruction") or "").strip()
    question_ids = [
        str(q).strip() for q in (spec.get("question_ids") or []) if str(q).strip()
    ]
    model = spec.get("model") or None
    provider = spec.get("provider") or None
    try:
        max_iterations = int(spec.get("max_iterations") or DEFAULT_TASK_MAX_ITERATIONS)
    except (TypeError, ValueError):
        max_iterations = DEFAULT_TASK_MAX_ITERATIONS

    progress: list[dict[str, Any]] = []

    def _note(stage: str, detail: str) -> None:
        """Stage a human-readable progress note onto the record (persisted
        unconditionally — the compat read-shim surfaces it as job['progress'])."""
        progress.append({"stage": stage, "detail": detail, "at": _now_iso()})
        ctx.annotate("progress", progress)

    if not instruction:
        _note("error", "task job requires a non-empty instruction")
        raise ValueError("task job requires a non-empty instruction")

    # Arc-9 approval gate: a task session SPENDS (one bounded agent run) and may WRITE
    # (every change goes through the gated forecast_ledger_tool). Authorize both up
    # front — before the compose + session — so an ask/never cell parks or refuses
    # before any spend. AUTO under every default.
    from forecasting.jobs.policy import ActionClass

    ctx.authorize(ActionClass.LLM_SPEND, f"one task session over {len(question_ids)} question(s)")
    ctx.authorize(ActionClass.LEDGER_WRITES, "gated forecast_ledger_tool commits")

    _note("start", f"composing task over {len(question_ids)} question(s)")

    ledger = ForecastLedger(spec.get("db"))  # a bad db → runtime marks the job error

    try:
        system_message, user_message = _compose_task_prompt(
            ledger, instruction, question_ids
        )
    except Exception as exc:  # noqa: BLE001
        _note("error", f"compose failed: {type(exc).__name__}: {exc}")
        raise

    _note("working", f"running one agent session (max_iterations={max_iterations})")

    try:
        result = _run_task_agent(
            user_message,
            system_message=system_message,
            model=model,
            provider=provider,
            max_iterations=max_iterations,
        )
    except Exception as exc:  # noqa: BLE001 — the session raising is a job error
        _note("error", f"agent session failed: {type(exc).__name__}: {exc}")
        raise

    result = result or {}
    summary = str(result.get("final_response") or "").strip()
    task_result = {
        "final_response": summary,
        "api_calls": result.get("api_calls"),
        "completed": result.get("completed"),
        "failed": bool(result.get("failed")),
    }
    ctx.record.total = len(question_ids)
    ctx.record.done_count = len(question_ids)
    ctx.record.annotations["task_summary"] = summary
    ctx.record.annotations["task_result"] = task_result
    _note("done", summary[:500] if summary else "agent session complete (no summary)")

    return {
        "task_summary": summary,
        "task_result": task_result,
        "done_count": len(question_ids),
    }


TASK = JobType(
    name="task",
    execute=execute,
    min_interval_s=0.0,
    alias_namespace="forecast.reforecast",
    spend_class="agent",
)

register(TASK)

__all__ = [
    "DEFAULT_TASK_MAX_ITERATIONS",
    "TASK",
    "execute",
    "_run_task_agent",
    "_compose_task_prompt",
    "_now_iso",
]
