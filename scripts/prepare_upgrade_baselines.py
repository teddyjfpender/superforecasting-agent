#!/usr/bin/env python3
"""Prepare immutable older product inputs for native upgrade qualification."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_NAME = "superforecasting_agent-0.19.0-py3-none-any.whl"
BACKEND_SHA256 = "1fdd753c680994131d55e90e23d0362d62c187b3cf0843cfe5b98f174fb56919"
BACKEND_URL = (
    "https://github.com/teddyjfpender/superforecasting-agent/releases/download/v0.19.0/"
    + BACKEND_NAME
)
TERMINAL_SOURCE = "3a42c3054f2a7f9671b69259ec2388b037728d55"


def verify_backend(payload: bytes) -> None:
    if hashlib.sha256(payload).hexdigest() != BACKEND_SHA256:
        raise ValueError("Published upgrade baseline checksum mismatch")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "dist/upgrade-baselines")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    backend = output / BACKEND_NAME
    if backend.exists():
        payload = backend.read_bytes()
    else:
        with urllib.request.urlopen(BACKEND_URL, timeout=90) as response:
            payload = response.read()
    verify_backend(payload)
    backend.write_bytes(payload)
    subprocess.run(
        ["git", "fetch", "--no-tags", "origin", TERMINAL_SOURCE], cwd=ROOT, check=True
    )
    archive = subprocess.check_output(
        [
            "git",
            "archive",
            TERMINAL_SOURCE,
            "products/tui",
            "ui-tui",
            "scripts/build_profiles.py",
        ],
        cwd=ROOT,
    )
    with tempfile.TemporaryDirectory(prefix="forecast-old-terminal-") as temporary:
        source = Path(temporary)
        with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
            bundle.extractall(source, filter="data")
        subprocess.run(
            [shutil.which("npm") or "npm", "ci"],
            cwd=source / "ui-tui",
            check=True,
        )
        # Build the historical Ink source too, not a new bundle in an old wrapper.
        subprocess.run(
            [
                sys.executable,
                str(source / "scripts/build_profiles.py"),
                "--profile",
                "tui",
                "--out",
                str(source / "wheels"),
            ],
            check=True,
        )
        shutil.copy2(
            source / "wheels/superforecasting_agent_tui-0.1.0-py3-none-any.whl", output
        )
    terminal = output / "superforecasting_agent_tui-0.1.0-py3-none-any.whl"
    receipt = {
        "schema_version": 1,
        "backend": {"url": BACKEND_URL, "sha256": BACKEND_SHA256},
        "terminal": {
            "source_commit": TERMINAL_SOURCE,
            "provenance": "historical source build; not a published release",
            "sha256": hashlib.sha256(terminal.read_bytes()).hexdigest(),
        },
    }
    (output / "provenance.json").write_text(
        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
