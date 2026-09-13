"""Standalone terminal product: no backend imports or dependencies."""

from __future__ import annotations

import argparse
import importlib.metadata
import os
import shutil
import subprocess
import sys
from pathlib import Path


def bundle_path() -> Path:
    return Path(__file__).parent / "dist" / "entry.js"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gateway-url", help="WebSocket URL for a remote backend")
    parser.add_argument(
        "--python", help="Python interpreter of a local backend installation"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check local prerequisites without starting the terminal",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=importlib.metadata.version("superforecasting-agent-tui"),
    )
    args = parser.parse_args()
    node = shutil.which("node")
    if not node:
        parser.error("Node.js 20.10 or newer is required for the TUI.")
    if not bundle_path().is_file():
        parser.error(
            "The installed TUI bundle is missing; reinstall superforecasting-agent-tui."
        )
    env = os.environ.copy()
    if args.gateway_url:
        env["SUPERFORECASTING_AGENT_TUI_GATEWAY_URL"] = args.gateway_url
    remote = any(
        env.get(prefix + "_TUI_GATEWAY_URL")
        for prefix in ("SUPERFORECASTING_AGENT", "FORECAST", "HERMES")
    )
    python = args.python or env.get("SUPERFORECASTING_AGENT_PYTHON") or sys.executable
    env["SUPERFORECASTING_AGENT_PYTHON"] = python
    version = subprocess.check_output([node, "--version"], text=True).strip()
    if tuple(map(int, version.lstrip("v").split(".")[:2])) < (20, 10):
        parser.error("Node.js 20.10 or newer is required for the TUI.")
    # Node 20 ships WebSocket behind this flag; it is also accepted on Node 22+.
    # Use identical runtime options for prerequisite checks and the actual desk.
    node_argv = [node, "--experimental-websocket"]
    if remote:
        probe = subprocess.run(
            [*node_argv, "-e", "process.exit(typeof WebSocket === 'function' ? 0 : 1)"],
            capture_output=True,
            text=True,
        )
        if probe.returncode:
            parser.error(
                "This Node.js runtime cannot provide WebSocket support; install Node.js 22 or newer."
            )
    if args.check:
        if not remote:
            probe = subprocess.run(
                [python, "-c", "import tui_gateway.entry"],
                capture_output=True,
                text=True,
            )
            if probe.returncode:
                parser.error(
                    "Local backend is unavailable. Install superforecasting-agent in this interpreter, specify --python, or use --gateway-url."
                )
        print(
            "TUI prerequisites available"
            + ("; remote compatibility is checked on connection." if remote else ".")
        )
        return 0
    return subprocess.call([*node_argv, str(bundle_path())], env=env)
