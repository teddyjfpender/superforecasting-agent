"""Compatibility entrypoint for the backend forecast worker."""

from superforecasting_agent.worker import main as _worker_main


def main(argv: list[str] | None = None) -> int:
    return _worker_main(argv, program="python -m forecasting.jobs")


if __name__ == "__main__":
    raise SystemExit(main())
