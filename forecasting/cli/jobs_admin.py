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
from typing import Any


def register(forecast_sub: argparse._SubParsersAction) -> None:
    """Register the ``jobs`` command group onto the forecast subparsers."""

    jobs_parser = forecast_sub.add_parser(
        "jobs",
        help="Administer detached background forecast jobs",
    )
    jobs_sub = jobs_parser.add_subparsers(dest="jobs_command")
    jobs_status = jobs_sub.add_parser("status", help="Show one job record")
    jobs_status.add_argument("job_id", help="The job id")
    jobs_status.add_argument("--json", action="store_true", help="Emit the job record as JSON")
    jobs_status.set_defaults(_forecast_handler=_cmd_jobs_status)

    jobs_active = jobs_sub.add_parser(
        "active",
        aliases=["list"],
        help="List queued/running jobs with a fresh heartbeat",
    )
    jobs_active.add_argument("--type", dest="job_type", action="append", help="Filter to a job type; repeatable")
    jobs_active.add_argument("--limit", type=int, default=100)
    jobs_active.add_argument("--all-status", action="store_true", help="List all stored jobs, not only active ones")
    jobs_active.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    jobs_active.set_defaults(_forecast_handler=_cmd_jobs_active)

    jobs_cancel = jobs_sub.add_parser("cancel", help="Request cooperative cancellation for a running job")
    jobs_cancel.add_argument("job_id", help="The job id")
    jobs_cancel.add_argument("--json", action="store_true", help="Emit the updated job record as JSON")
    jobs_cancel.set_defaults(_forecast_handler=_cmd_jobs_cancel)

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


def _record_payload(record) -> dict[str, Any]:
    return record.to_dict() if hasattr(record, "to_dict") else dict(record)


def _print_job(payload: dict[str, Any]) -> None:
    print(
        f"{payload.get('job_id')}  {payload.get('type')}  {payload.get('status')}  "
        f"{payload.get('done_count', 0)}/{payload.get('total') or '?'}"
    )
    current = payload.get("current")
    if current:
        print(f"  current: {current}")
    if payload.get("cancel_requested"):
        print("  cancel_requested: true")
    if payload.get("error"):
        print(f"  error: {payload['error']}")


def _cmd_jobs_status(args: argparse.Namespace) -> None:
    from forecasting.jobs.store import JobStore

    try:
        payload = _record_payload(JobStore().read(args.job_id))
    except (FileNotFoundError, ValueError) as exc:
        print(f"forecast: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    _print_job(payload)


def _cmd_jobs_active(args: argparse.Namespace) -> None:
    from forecasting.jobs.store import JobStore

    store = JobStore()
    limit = max(1, int(getattr(args, "limit", 100) or 100))
    if getattr(args, "all_status", False):
        records = store.list(limit=limit)
        if getattr(args, "job_type", None):
            wanted = set(args.job_type)
            records = [record for record in records if record.type in wanted]
    else:
        records = store.active(types=getattr(args, "job_type", None), limit=limit)
    payload = [_record_payload(record) for record in records]
    if getattr(args, "json", False):
        print(json.dumps({"count": len(payload), "jobs": payload}, indent=2, sort_keys=True))
        return
    if not payload:
        print("No jobs found." if getattr(args, "all_status", False) else "No active jobs.")
        return
    for row in payload:
        _print_job(row)


def _cmd_jobs_cancel(args: argparse.Namespace) -> None:
    from forecasting.jobs.store import JobStore

    store = JobStore()
    try:
        ok = store.request_cancel(args.job_id)
    except ValueError as exc:
        print(f"forecast: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if not ok:
        print(f"forecast: no job '{args.job_id}'", file=sys.stderr)
        raise SystemExit(1)
    payload = _record_payload(store.read(args.job_id))
    if getattr(args, "json", False):
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"cancel requested for {args.job_id}")
    _print_job(payload)


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
