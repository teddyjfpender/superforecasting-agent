"""Compatibility launcher for existing Codex MCP configurations.

New configurations use agent.transports.forecast_tools_mcp_server.
"""

from agent.transports.forecast_tools_mcp_server import main


if __name__ == "__main__":
    raise SystemExit(main())
