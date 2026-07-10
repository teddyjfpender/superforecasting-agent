"""The RPC-registry byte-identity gate for a tui_gateway server family carve.

Imports ``tui_gateway.server`` and prints every registered JSON-RPC method name
in SORTED order (the dispatch dict ``_methods`` keys). A moves-only family carve
(Wave-2 of the modularization program) relocates ``@rpc_validated`` handler
bodies into a ``<family>_rpc.py`` sibling; the registration must land in the SAME
dispatch dict, so this dump is **byte-identical** before and after every slice.

Order-independent by construction (sorted): a registration that moves to the
bottom-of-module sibling import re-inserts at a different dict position but the
sorted set is unchanged — which is exactly the wire-protocol invariant (dispatch
is a key lookup, never positional).

Usage:
    python scripts/carve/dump_registry.py            # sorted method names
    python scripts/carve/dump_registry.py --count     # + a trailing count line
"""
from __future__ import annotations

import pathlib
import sys

# Running this file as a script puts scripts/carve/ on sys.path[0]; the gateway
# imports top-level repo modules (``protocol`` etc.), so ensure the repo root is
# importable regardless of invocation directory.
_REPO_ROOT = str(pathlib.Path(__file__).resolve().parents[2])
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)


def main() -> int:
    import tui_gateway.server as server

    # The gateway swaps ``sys.stdout`` at import (fd 1 is the JSON-RPC wire), so
    # emit the dump to the ORIGINAL stdout to reach the real fd 1 / a redirect.
    out = sys.__stdout__
    names = sorted(server._methods.keys())
    for name in names:
        out.write(name + "\n")
    if "--count" in sys.argv[1:]:
        out.write(f"# {len(names)} methods\n")
    out.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
