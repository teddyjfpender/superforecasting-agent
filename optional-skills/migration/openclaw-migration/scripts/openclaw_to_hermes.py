#!/usr/bin/env python3
"""Compatibility launcher for the renamed OpenClaw migration command."""

import sys
from pathlib import Path

_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

import openclaw_to_forecast as _migration


def __getattr__(name):
    return getattr(_migration, name)


if __name__ == "__main__":
    raise SystemExit(_migration.main())
