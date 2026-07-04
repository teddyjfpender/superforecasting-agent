"""Detached worker entrypoint: ``python -m forecasting.jobs run <job_id>``.

A fresh process, so discover plugins first (search/extract providers) exactly as
the quorum/reforecast workers do, then run the job to its terminal state.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "run":
        sys.stderr.write("usage: python -m forecasting.jobs run <job_id>\n")
        return 2

    # A detached worker is a fresh process: register the search/extract providers
    # so job types that research have them (mirrors quorum_jobs' worker boot).
    try:
        from hermes_cli.plugins import discover_plugins

        discover_plugins()
    except Exception:  # noqa: BLE001 — degrade gracefully if discovery fails
        pass

    from forecasting.jobs.runtime import run

    record = run(argv[1])
    return 0 if record.status in ("done", "cancelled") else 1


if __name__ == "__main__":
    raise SystemExit(main())
