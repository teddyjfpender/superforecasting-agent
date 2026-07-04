"""``python -m scripts.docgen`` — generate (or ``--check``) the reference docs."""

from __future__ import annotations

from scripts.docgen.registry import main

if __name__ == "__main__":
    raise SystemExit(main())
