"""Detached forecast-job process launcher."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from superforecasting_agent.constants import subprocess_home_env


def spawn_detached_job(job_id: str, *, home: Path | None = None) -> None:
    env = subprocess_home_env(home) if home is not None else dict(os.environ)
    kwargs = {"start_new_session": True} if hasattr(os, "setsid") else {}
    process = subprocess.Popen(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, "-m", "superforecasting_agent.worker", "run", job_id],
        cwd=str(Path(__file__).resolve().parents[2]),
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        **kwargs,
    )
    threading.Thread(target=process.wait, daemon=True).start()


__all__ = ["spawn_detached_job"]
