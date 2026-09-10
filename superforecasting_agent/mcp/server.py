"""Create and run the Superforecasting Agent messaging MCP server."""

from __future__ import annotations

import logging
import sys
from typing import Optional

from .events import EventBridge
from .conversation_tools import register_tools as register_conversation_tools
from .event_tools import register_tools as register_event_tools

_MCP_SERVER_AVAILABLE = False
try:
    from mcp.server.fastmcp import FastMCP
    _MCP_SERVER_AVAILABLE = True
except ImportError:
    FastMCP = None


def create_mcp_server(event_bridge: Optional[EventBridge] = None) -> "FastMCP":
    """Create and return the Superforecasting Agent MCP server."""
    if not _MCP_SERVER_AVAILABLE:
        raise ImportError(
            "MCP server requires the 'mcp' package. "
            f"Install with: {sys.executable} -m pip install 'mcp'"
        )

    mcp = FastMCP(
        "superforecasting-agent",
        instructions=(
            "Superforecasting Agent messaging bridge. Use these tools to interact with "
            "conversations across Telegram, Discord, Slack, WhatsApp, Signal, "
            "Matrix, and other connected platforms."
        ),
    )

    bridge = event_bridge or EventBridge()

    # -- conversations_list ------------------------------------------------

    register_conversation_tools(mcp, bridge)
    register_event_tools(mcp, bridge)
    return mcp


def run_mcp_server(verbose: bool = False) -> None:
    """Start the Superforecasting Agent MCP server on stdio."""
    if not _MCP_SERVER_AVAILABLE:
        print(
            "Error: MCP server requires the 'mcp' package.\n"
            f"Install with: {sys.executable} -m pip install 'mcp'",
            file=sys.stderr,
        )
        sys.exit(1)

    if verbose:
        logging.basicConfig(level=logging.DEBUG, stream=sys.stderr)
    else:
        logging.basicConfig(level=logging.WARNING, stream=sys.stderr)

    bridge = EventBridge()
    bridge.start()

    server = create_mcp_server(event_bridge=bridge)

    import asyncio

    async def _run():
        try:
            await server.run_stdio_async()
        finally:
            bridge.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        bridge.stop()
