#!/usr/bin/env python3
"""Build independently installable backend and terminal wheels."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("backend", "tui", "all"), default="all")
    parser.add_argument("--out", type=Path, default=ROOT / "dist" / "profiles")
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if args.profile in ("tui", "all"):
        subprocess.run(
            [shutil.which("npm") or "npm", "run", "build"],
            cwd=ROOT / "ui-tui",
            check=True,
        )
        bundle = ROOT / "products/tui/superforecasting_agent_tui/dist"
        bundle.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / "ui-tui/dist/entry.js", bundle / "entry.js")
        (bundle / "package.json").write_text('{"type":"module"}\n', encoding="utf-8")
    if args.profile in ("backend", "all"):
        with tempfile.TemporaryDirectory(prefix="forecast-source-build-") as temporary:
            subprocess.run(
                ["uv", "build", "--sdist", "--out-dir", temporary, str(ROOT)],
                cwd=ROOT,
                check=True,
            )
            (source_archive,) = Path(temporary).glob("*.tar.gz")
            subprocess.run(
                [
                    "uv",
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(output),
                    str(source_archive),
                ],
                cwd=ROOT,
                check=True,
            )
    if args.profile in ("tui", "all"):
        subprocess.run(
            [
                "uv",
                "build",
                "--wheel",
                "--out-dir",
                str(output),
                str(ROOT / "products/tui"),
            ],
            cwd=ROOT,
            check=True,
        )
    for wheel in output.glob("superforecasting_agent-*.whl"):
        with zipfile.ZipFile(wheel) as archive:
            forbidden = [
                name
                for name in archive.namelist()
                if "/tui_dist/" in name
                or "/web_dist/" in name
                or "/node_modules/" in name
            ]
        if forbidden:
            raise RuntimeError(f"Backend wheel contains UI assets: {forbidden[:5]}")
    print(f"Independent wheels: {output}")


if __name__ == "__main__":
    main()
