#!/usr/bin/env python3
"""Verify built product wheels outside the checkout in fresh environments."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import select
import signal
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

# Run inside the installed backend interpreter, outside the source checkout.
NUMERICAL_FALLBACK_CHECK = """
import builtins
original_import = builtins.__import__
attempted_install = []
def isolated_import(name, *args, **kwargs):
    if name == 'tools.lazy_deps':
        attempted_install.append(name)
        raise AssertionError('numerical operation imported package installer')
    if name.split('.')[0] in {'numpy', 'scipy', 'statsmodels'}:
        raise ImportError('optional backend deliberately unavailable')
    return original_import(name, *args, **kwargs)
builtins.__import__ = isolated_import
from forecasting import bayes_toolkit as bayes, market_compute as market
assert bayes.ensure_industry_backends() == {'numpy': False, 'scipy': False}
assert abs(bayes.normal_cdf(0) - 0.5) < 1e-12
assert market.ensure_econometrics()['statsmodels'] is False
result = market.compute('ols', {'x': [0, 1, 2, 3], 'y': [1, 3, 5, 7]})
assert result['ok'], result
assert abs(result['block']['coeffs'][0]['value'] - 2) < 1e-9, result
assert attempted_install == [], attempted_install
"""


def verify_installed_terminal(
    terminal_python: Path,
    backend_python: Path,
    root: Path,
    env: dict[str, str],
    question: str,
    *,
    gateway_url: str | None = None,
) -> None:
    """Exercise packaged Ink against a separate local or remote backend."""
    if os.name == "nt":
        print(
            "Installed terminal PTY exercise: skipped on native Windows (requires ConPTY)."
        )
        return
    import fcntl
    import pty
    import struct
    import termios

    master, slave = pty.openpty()
    process = None
    try:
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 45, 160, 0, 0))
        process = subprocess.Popen(
            [
                str(terminal_python),
                "-c",
                "from superforecasting_agent_tui import main; raise SystemExit(main())",
                *(
                    ["--gateway-url", gateway_url]
                    if gateway_url
                    else ["--python", str(backend_python)]
                ),
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=root,
            env={
                **env,
                "TERM": "xterm-256color",
                "SUPERFORECASTING_AGENT_TUI_CRON_TICKER": "0",
            },
            start_new_session=True,
        )
        os.close(slave)
        slave = -1

        def expect(text: bytes) -> None:
            output = bytearray()
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                readable, _, _ = select.select([master], [], [], 0.2)
                if readable:
                    try:
                        chunk = os.read(master, 65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    output.extend(chunk)
                    if text in output:
                        return
                if process.poll() is not None:
                    break
            plain = re.sub(rb"\x1b\[[0-?]*[ -/]*[@-~]", b"", bytes(output))
            plain = re.sub(rb"[^\x20-\x7e\n\r]", b"", plain)
            raise RuntimeError(
                f"Installed terminal did not display {text!r}: {plain[-12000:]!r}"
            )

        expect(b"setup required")
        os.write(master, f"/score {question} --baselines\r".encode())
        expect(b"baseline_scores: none")
        os.write(master, b"q")
        expect(b"setup required")
        # Let the close redraw settle before the next physical key sequence.
        # A footer also appears under the open viewer, so matching its bytes
        # alone is not proof that the viewer has released input focus.
        settle_deadline = time.monotonic() + 3
        while time.monotonic() < settle_deadline:
            if not select.select([master], [], [], 0.2)[0]:
                break
            os.read(master, 65536)
        os.write(master, b"/quit\r")
        # Keep draining redraw/terminal-reset output while the child exits.
        # Waiting without reading can fill the PTY and block Node's shutdown.
        deadline = time.monotonic() + 15
        while process.poll() is None and time.monotonic() < deadline:
            if select.select([master], [], [], 0.2)[0]:
                try:
                    if not os.read(master, 65536):
                        break
                except OSError:
                    break
        if process.wait(timeout=3) != 0:
            raise RuntimeError("Installed terminal exited unsuccessfully")
        print(
            f"Installed terminal: negotiated {'remote' if gateway_url else 'local'} host, scored durable forecast and exited cleanly."
        )
    finally:
        if slave >= 0:
            os.close(slave)
        os.close(master)
        if process is not None and process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def assert_preserved(before: Any, after: Any, path: str = "state") -> None:
    """Allow added schema fields; never silently lose or alter existing values."""
    if isinstance(before, dict):
        if not isinstance(after, dict):
            raise AssertionError(f"{path}: mapping lost during upgrade")
        for key, value in before.items():
            if key not in after:
                raise AssertionError(f"{path}.{key}: missing after upgrade")
            assert_preserved(value, after[key], f"{path}.{key}")
    elif isinstance(before, list):
        if not isinstance(after, list) or len(before) != len(after):
            raise AssertionError(f"{path}: record count changed during upgrade")
        for index, value in enumerate(before):
            assert_preserved(value, after[index], f"{path}[{index}]")
    elif type(before) is not type(after) or before != after:
        raise AssertionError(f"{path}: value changed during upgrade")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", type=Path)
    parser.add_argument(
        "--upgrade-from",
        type=Path,
        help="Install this older backend wheel and create durable state before upgrading",
    )
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
        for name, wheel in (
            ("backend", args.upgrade_from.resolve() if args.upgrade_from else backend),
            ("terminal", terminal),
        ):
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
                    timeout=90,
                )
            except subprocess.CalledProcessError as exc:
                raise RuntimeError(exc.output) from exc

        backend_run(
            "-c",
            "import shutil; assert shutil.which('node') is None; import forecasting",
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
        if args.upgrade_from:
            forecast(
                "evidence",
                "add",
                question,
                "Local upgrade fixture",
                "--claim",
                "The isolated fixture is prepared",
                "--summary",
                "Synthetic engineering evidence; no forecasting skill claim",
                "--published-at",
                "2026-09-10T00:00:00Z",
            )
            export_path = root / "before-upgrade.json"
            forecast(
                "export", question, "--format", "json", "--output", str(export_path)
            )
            before = json.loads(export_path.read_text(encoding="utf-8"))
            if not before["forecast_history"] or not before["evidence"]:
                raise AssertionError(
                    "Older backend did not persist forecast/evidence fixtures"
                )
            config = profile / "config.yaml"
            config.write_text("display:\n  skin: mono\n", encoding="utf-8")
            config_before = config.read_bytes()
            session_import = (
                "from importlib.util import find_spec; from importlib import import_module; "
                "SessionDB = import_module('superforecasting_agent.storage.session' "
                "if find_spec('superforecasting_agent.storage') is not None "
                "else 'hermes_state').SessionDB; "
            )
            backend_run(
                "-c",
                session_import + "db=SessionDB(); "
                "db.create_session('upgrade-fixture', source='cli'); "
                "db.append_message('upgrade-fixture', 'user', 'Preserve this forecast note — 日本語'); db.close()",
            )
            read_session = (
                session_import + "import json; db=SessionDB(); "
                "print(json.dumps(db.get_messages('upgrade-fixture'))); db.close()"
            )
            messages = json.loads(backend_run("-c", read_session))
            if not messages:
                raise AssertionError(
                    "Older backend did not persist the session fixture"
                )
            old_version = backend_run(
                "-c",
                "from importlib.metadata import version; print(version('superforecasting-agent'))",
            ).strip()
            subprocess.run(
                [
                    "uv",
                    "pip",
                    "install",
                    "--reinstall-package",
                    "superforecasting-agent",
                    "--python",
                    str(backend_python),
                    str(backend),
                ],
                check=True,
            )
            subprocess.run(
                ["uv", "pip", "check", "--python", str(backend_python)], check=True
            )
            new_version = backend_run(
                "-c",
                "from importlib.metadata import version; print(version('superforecasting-agent'))",
            ).strip()
            forecast(
                "export", question, "--format", "json", "--output", str(export_path)
            )
            after = json.loads(export_path.read_text(encoding="utf-8"))
            for field in ("question", "forecast_history", "evidence"):
                assert_preserved(before[field], after[field], field)
            assert_preserved(
                messages,
                json.loads(backend_run("-c", read_session)),
                "session",
            )
            if config.read_bytes() != config_before:
                raise AssertionError("Upgrade changed user configuration")
            print(
                json.dumps({
                    "upgrade": {"from": old_version, "to": new_version},
                    "previous_sha256": hashlib.sha256(
                        args.upgrade_from.read_bytes()
                    ).hexdigest(),
                    "candidate_sha256": hashlib.sha256(
                        backend.read_bytes()
                    ).hexdigest(),
                    "preserved": [
                        "question",
                        "forecast_history",
                        "evidence",
                        "session",
                        "configuration",
                    ],
                })
            )
        backend_run("-c", "import forecasting.application.reviews")
        backend_run(
            "-c", "from superforecasting_agent.worker import main; assert main([]) == 2"
        )
        backend_run("-c", NUMERICAL_FALLBACK_CHECK)
        print(
            "Backend: numerical fallback passed without optional libraries or installer access."
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
        verify_installed_terminal(
            terminal_python, backend_python, root, terminal_env, question
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
        subprocess.run(
            [
                str(backend_python),
                str(Path(__file__).with_name("verify_headless_host.py").resolve()),
                "--terminal-python",
                str(terminal_python),
                "--profile",
                str(profile),
                "--question",
                question,
            ],
            cwd=root,
            env=terminal_env,
            check=True,
            timeout=180,
        )
        print("Optional web profile: installed authenticated hosting passed.")


if __name__ == "__main__":
    main()
