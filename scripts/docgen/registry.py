"""The generator registry + the read/write/check plumbing.

Add a reference page by writing a ``render() -> str`` module and appending one
``Generated`` entry here. Everything else — the writer, the ``--check`` gate, the
generated index — picks it up automatically.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from scripts.docgen import (
    cli_reference_doc,
    config_env_doc,
    hooks_rules_doc,
    job_types_doc,
    protocol_doc,
    providers_doc,
    skills_doc,
    tool_actions_doc,
)

_REFERENCE_REL = Path("docs/reference")


@dataclass(frozen=True)
class Generated:
    """One generated reference page."""

    filename: str  # relative to docs/reference/
    title: str  # human title for the index
    render: Callable[[], str]  # returns the full markdown body
    summary: str  # one-line index blurb


GENERATORS: list[Generated] = [
    Generated(
        "protocol.md",
        "Gateway wire protocol",
        protocol_doc.render,
        "Every RPC method and event crossing the gateway, with request/response/payload schemas.",
    ),
    Generated(
        "tool-actions.md",
        "Forecast tool actions",
        tool_actions_doc.render,
        "The `forecast_ledger` tool's actions and parameter bag — how the agent drives the desk.",
    ),
    Generated(
        "job-types.md",
        "Background job types",
        job_types_doc.render,
        "The detached-job runtime's registered job types (quorum, reforecast, refresh, task, warnings).",
    ),
    Generated(
        "providers.md",
        "Data-plane providers",
        providers_doc.render,
        "Market-data quote providers and prediction-market venues.",
    ),
    Generated(
        "cli-reference.md",
        "CLI reference",
        cli_reference_doc.render,
        "The exhaustive `forecast` command tree, introspected from argparse.",
    ),
    Generated(
        "hooks-rules.md",
        "Forecast hooks (built-in rules)",
        hooks_rules_doc.render,
        "The commit-gate rules that warn on or block an under-saturated forecast.",
    ),
    Generated(
        "skills.md",
        "Skills catalogue",
        skills_doc.render,
        "Every bundled `SKILL.md`, grouped by category, with its when-to-use triggers.",
    ),
    Generated(
        "config-and-env.md",
        "Configuration & environment variables",
        config_env_doc.render,
        "Every environment variable the server, tools, and CLI read — defaults and secrets.",
    ),
]


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def reference_dir() -> Path:
    return repo_root() / _REFERENCE_REL


def _index_markdown() -> str:
    """The generated ``docs/reference/README.md`` — a table of contents for the
    generated reference, itself kept in sync by the same gate."""

    lines = [
        "# Reference (generated)",
        "",
        "<!-- GENERATED FILE - DO NOT EDIT BY HAND. -->",
        "<!-- Regenerate:      python -m scripts.docgen -->",
        "<!-- Staleness gate:  python -m scripts.docgen --check -->",
        "",
        "These pages are generated from the code — the protocol registry, the tool"
        " schema, the jobs registry, the provider registries, the CLI argparse tree,"
        " and the built-in hooks. They regenerate deterministically and a CI staleness"
        " gate fails if any is out of date, so the reference cannot drift from the"
        " system it documents. Do not edit them by hand.",
        "",
        "Regenerate after changing any of those sources:",
        "",
        "```bash",
        "python -m scripts.docgen            # rewrite docs/reference/*.md",
        "python -m scripts.docgen --check    # CI gate: fail if stale",
        "```",
        "",
        "| page | contents |",
        "| --- | --- |",
    ]
    for gen in GENERATORS:
        lines.append(f"| [{gen.title}]({gen.filename}) | {gen.summary} |")
    lines.append("")
    return "\n".join(lines)


def render_all() -> dict[Path, str]:
    """Absolute path -> rendered content for every generated file (index included)."""

    out: dict[Path, str] = {}
    ref = reference_dir()
    for gen in GENERATORS:
        out[ref / gen.filename] = gen.render()
    out[ref / "README.md"] = _index_markdown()
    return out


def write() -> list[Path]:
    """Write every generated file; return the paths written."""

    written: list[Path] = []
    for path, content in render_all().items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        written.append(path)
    return written


def check() -> list[Path]:
    """Return the paths whose on-disk content differs from a fresh render (stale)."""

    stale: list[Path] = []
    for path, content in render_all().items():
        current = path.read_text(encoding="utf-8") if path.exists() else ""
        if current != content:
            stale.append(path)
    return stale


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = repo_root()
    if "--check" in argv:
        stale = check()
        if stale:
            sys.stderr.write(
                "error: generated reference docs are STALE.\n"
                + "".join(f"  {p.relative_to(root)}\n" for p in stale)
                + "  fix: run  python -m scripts.docgen  and commit the result.\n"
            )
            return 1
        sys.stdout.write("reference docs are up to date.\n")
        return 0

    for path in write():
        sys.stdout.write(f"wrote {path.relative_to(root)}\n")
    return 0
