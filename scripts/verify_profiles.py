#!/usr/bin/env python3
"""Verify built product wheels outside the checkout in fresh environments."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import tempfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", type=Path)
    parser.add_argument(
        "--python",
        default="3.11",
        help="Supported Python version or interpreter for isolated installs",
    )
    args = parser.parse_args()
    (backend,) = args.wheels.resolve().glob("superforecasting_agent-*.whl")
    (terminal,) = args.wheels.resolve().glob("superforecasting_agent_tui-*.whl")
    with tempfile.TemporaryDirectory(prefix="forecast-distribution-test-") as temporary:
        root = Path(temporary)
        bins = "Scripts" if os.name == "nt" else "bin"
        python_name = "python.exe" if os.name == "nt" else "python"
        for name, wheel in (("backend", backend), ("terminal", terminal)):
            env_root = root / name
            subprocess.run(
                ["uv", "venv", str(env_root), "--python", args.python], check=True
            )
            python = env_root / bins / python_name
            subprocess.run(
                ["uv", "pip", "install", "--python", str(python), str(wheel)],
                check=True,
            )
            subprocess.run(["uv", "pip", "check", "--python", str(python)], check=True)
        backend_python = root / "backend" / bins / python_name
        terminal_python = root / "terminal" / bins / python_name
        profile = root / "profile"
        profile.mkdir()
        env = {
            "PATH": str(backend_python.parent),
            "HOME": str(profile),
            "SUPERFORECASTING_AGENT_HOME": str(profile),
            "HERMES_HOME": str(profile),
            "LANG": "C.UTF-8",
            "PYTHONUTF8": "1",
        }
        if os.name == "nt":
            env["SYSTEMROOT"] = os.environ["SYSTEMROOT"]

        def backend_run(*arguments: str) -> str:
            try:
                return subprocess.check_output(
                    [str(backend_python), *arguments],
                    cwd=root,
                    env=env,
                    text=True,
                    stderr=subprocess.STDOUT,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(exc.output) from exc

        backend_run(
            "-c",
            "import shutil; assert shutil.which('node') is None; import forecasting.application.reviews",
        )

        def forecast(*arguments: str) -> str:
            return backend_run("-m", "superforecasting_agent", "forecast", *arguments)

        created = forecast(
            "new",
            "Will the fixture finish?",
            "--resolution-criteria",
            "Resolves YES if the official fixture completion record confirms completion by 2026-09-11; otherwise NO.",
        )
        match = re.search(r"\bfq_[a-z0-9]+\b", created)
        if match is None:
            raise RuntimeError(f"Question was not created: {created}")
        question = match.group()
        forecast(
            "update",
            question,
            "--probability",
            "0.7",
            "--rationale",
            "Fixture baseline",
            "--reason-up",
            "The fixture is ready to run",
            "--reason-down",
            "Execution could fail",
            "--change-my-mind",
            "A failed completion record",
        )
        resolved = forecast(
            "resolve", question, "--outcome", "true", "--source", "Fixture completion"
        )
        if "auto_score:" not in resolved:
            raise RuntimeError(f"Resolution did not return a score: {resolved}")
        print("Backend: create, update, resolve and score passed without Node on PATH.")
        terminal_env = {**env, "PATH": os.environ["PATH"]}
        subprocess.run(
            [
                str(terminal_python),
                "-c",
                "import importlib.util; assert importlib.util.find_spec('forecasting') is None; from superforecasting_agent_tui import bundle_path; assert bundle_path().is_file()",
            ],
            cwd=root,
            env=terminal_env,
            check=True,
        )
        subprocess.run(
            [
                str(terminal_python),
                "-c",
                "from superforecasting_agent_tui import main; raise SystemExit(main())",
                "--check",
                "--gateway-url",
                "ws://127.0.0.1:9999/api/ws",
            ],
            cwd=root,
            env=terminal_env,
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "install", "--python", str(backend_python), str(terminal)],
            check=True,
        )
        subprocess.run(
            [
                str(backend_python),
                "-c",
                "from pathlib import Path; from superforecasting_agent.runtime.main import _make_tui_argv; from superforecasting_agent_tui import bundle_path; argv, cwd = _make_tui_argv(Path('absent-checkout'), False); assert argv[-1] == str(bundle_path())",
            ],
            cwd=root,
            env=terminal_env,
            check=True,
        )
        print(
            "Terminal: independent remote prerequisites and combined backend discovery passed."
        )
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--python",
                str(backend_python),
                str(backend) + "[web]",
            ],
            check=True,
        )
        subprocess.run(
            ["uv", "pip", "check", "--python", str(backend_python)], check=True
        )
        subprocess.run(
            [
                str(backend_python),
                "-c",
                "import fastapi; import uvicorn; from tui_gateway.http_server import make_server; host = make_server(host='127.0.0.1', port=0); host.restore_transport(); host.server_close()",
            ],
            cwd=root,
            env=terminal_env,
            check=True,
        )
        print("Optional web profile: dependencies and local host construction passed.")


if __name__ == "__main__":
    main()
