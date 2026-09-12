"""Read-only configuration reporting shared by terminal and RPC consumers."""

from __future__ import annotations

from typing import Any


def configuration_sections(
    *,
    model: str,
    base_url: str,
    api_key: Any,
    max_turns: int,
    toolsets: list[str] | None,
    verbose: bool,
    cwd: str,
    config_path: str,
) -> list[dict[str, Any]]:
    # Credentials may be callable token providers. Inspection must never fetch a
    # token or display any of its bytes, including when no model is initialized.
    auth = (
        "Token provider"
        if callable(api_key)
        else "Configured"
        if api_key
        else "Not set"
    )
    return [
        {
            "title": "Model",
            "rows": [
                ["Model", model],
                ["Base URL", base_url or "(default)"],
                ["API Key", auth],
            ],
        },
        {
            "title": "Agent",
            "rows": [
                ["Max Turns", str(max_turns)],
                [
                    "Toolsets",
                    "all" if toolsets is None else ", ".join(toolsets) or "none",
                ],
                ["Verbose", str(verbose)],
            ],
        },
        {
            "title": "Environment",
            "rows": [["Working Dir", cwd], ["Config File", config_path]],
        },
    ]


def configuration_text(sections: list[dict[str, Any]]) -> str:
    return "\n\n".join(
        "\n".join([
            f"-- {section['title']} --",
            *(f"{name}: {value}" for name, value in section["rows"]),
        ])
        for section in sections
    )
