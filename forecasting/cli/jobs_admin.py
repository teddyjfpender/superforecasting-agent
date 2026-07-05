"""``forecast jobs …`` — administer detached background forecast jobs.

The first carved CLI subcommand domain (the CLI-assembler analogue of the ledger
D1 watches slice): a domain module that registers its own subparsers via the
shared ``register(forecast_sub)`` hook and owns its handlers. The assembler
(:func:`forecasting.cli.core.register_cli`) calls :func:`register` at this
domain's position so ``forecast --help`` stays byte-identical.

Handlers here are self-contained (they reach the job runtime/policy by lazy
import at call time), so the module has NO load-time dependency on
``forecasting.cli.core`` — the cleanest possible carve.
"""

from __future__ import annotations

import argparse
import json
import sys


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``jobs`` command group onto the forecast subparsers."""

    jobs_parser = forecast_sub.add_parser(
        "jobs",
        help="Administer detached background forecast jobs",
    )
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_command")
    jobs_approve = jobs_sub.add_parser(
        "approve",
        help="Approve a parked job awaiting operator sign-off and (by default) resume it",
    )
    jobs_approve.add_argument("job_id", help="The parked job id (status awaiting_approval)")
    jobs_approve.add_argument(
        "--no-resume",
        action="store_true",
        help="Record the approval grant but do not re-run the job",
    )
    jobs_approve.add_argument("--json", action="store_true", help="Emit the job record as JSON")
    jobs_approve.set_defaults(_forecast_handler=_cmd_jobs_approve)


def _cmd_jobs_approve(args: argparse.Namespace) -> None:
    """`forecast jobs approve <job_id>` — approve a parked job awaiting operator
    sign-off and (by default) resume it to completion.

    A thin wrapper over :func:`forecasting.jobs.policy.approve_job` — the policy
    slice's named follow-up. The approve/resume path records the GRANT, acks the
    surfaced approval alert(s), flips the record back to ``queued`` and re-runs the
    job (which authorizes cleanly instead of re-parking)."""

    from forecasting.jobs.policy import approve_job

    try:
        record = approve_job(args.job_id, resume=not getattr(args, "no_resume", False))
    except ValueError as exc:
        print(f"forecast: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    payload = record.to_dict() if hasattr(record, "to_dict") else record
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    status = payload.get("status") if isinstance(payload, dict) else getattr(record, "status", "?")
    job_type = payload.get("type") if isinstance(payload, dict) else getattr(record, "type", "?")
    print(f"approved {args.job_id} ({job_type}) -> status={status}")
    error = payload.get("error") if isinstance(payload, dict) else getattr(record, "error", None)
    if error:
        print(f"  error: {error}")
