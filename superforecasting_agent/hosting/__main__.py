"""Launch the headless host with credentials read from a file."""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Serve the Superforecasting Agent protocol without a dashboard"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8642)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--allow-origin", action="append", default=[])
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error("--port must be between 0 and 65535")
    try:
        token = args.token_file.expanduser().read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError) as exc:
        parser.error(f"Cannot read --token-file: {exc}")
    if not token:
        parser.error("--token-file must contain a nonempty token")
    try:
        import uvicorn

        from superforecasting_agent.hosting.websocket import create_app
    except ImportError:
        parser.error(
            "Host dependencies are missing; install superforecasting-agent[web]"
        )
    try:
        app = create_app(token=token, allowed_origins=args.allow_origin)
    except ValueError as exc:
        parser.error(str(exc))
    # Query tokens are supported for the terminal client; never put URLs in logs.
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
