"""Render ``docs/reference/skills.md`` from the bundled skills' frontmatter.

Source of truth: the YAML frontmatter of every ``skills/**/SKILL.md`` in the repo.

A *skill* is a self-contained capability the agent can load on demand; each ships
a ``SKILL.md`` whose frontmatter declares its ``name`` and ``description`` (and,
sometimes, an explicit ``triggers`` list). This page indexes them, grouped by the
category directory they live under, so the catalogue is generated from the skills
themselves and cannot drift. It reuses the agent's own frontmatter parser
(``agent.skill_utils.parse_frontmatter``) so the doc reads skills exactly the way
the runtime does.
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.docgen.common import header

SOURCE = "skills/**/SKILL.md frontmatter (parsed with agent.skill_utils.parse_frontmatter)"

_SKILLS_REL = "skills"
# Mirror the runtime's skip-list so the doc enumerates exactly the loadable set.
from agent.skill_utils import EXCLUDED_SKILL_DIRS  # noqa: E402

_TOP_LEVEL = "(top-level)"

# Extract a "when to use" clause from a prose description: the tail beginning at
# the first "Use when / Use for / Invoke when / Triggers on / ..." trigger.
_WHEN_RE = re.compile(
    r"(?i)\b(?:use|invoke|trigger|triggers)\b\s+"
    r"(?:when|whenever|for|to|this|it|before|on|after)\b"
)


def _escape(text: str) -> str:
    """Make a value safe for a one-line markdown table cell."""

    return " ".join(str(text).split()).replace("|", r"\|")


def _when_to_use(fm: dict) -> str:
    """The skill's trigger guidance: its ``triggers`` list, else the ``Use when…``
    clause mined from the description, else an em dash."""

    triggers = fm.get("triggers")
    if isinstance(triggers, list) and triggers:
        return "; ".join(_escape(t) for t in triggers if str(t).strip())
    desc = str(fm.get("description", ""))
    match = _WHEN_RE.search(desc)
    if match:
        return _escape(desc[match.start():])
    return "—"


def _category(rel: Path) -> str:
    """The grouping bucket: the top directory under ``skills/`` for a nested skill
    (``software-development/plan`` → ``software-development``), or ``(top-level)``
    for a skill that sits directly under ``skills/``."""

    parts = rel.parts  # e.g. ("software-development", "plan", "SKILL.md")
    return parts[0] if len(parts) >= 3 else _TOP_LEVEL


def render() -> str:
    root = Path(__file__).resolve().parents[2]
    skills_dir = root / _SKILLS_REL

    # category -> list of (name, rel_dir, description, when_to_use)
    groups: dict[str, list[tuple[str, str, str, str]]] = {}
    total = 0
    for path in sorted(skills_dir.rglob("SKILL.md")):
        rel = path.relative_to(skills_dir)
        if any(part in EXCLUDED_SKILL_DIRS for part in rel.parts):
            continue
        from agent.skill_utils import parse_frontmatter

        fm, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
        if not isinstance(fm, dict):
            continue
        name = str(fm.get("name") or rel.parts[-2])
        description = _escape(fm.get("description", "")) or "—"
        rel_dir = str(path.parent.relative_to(root))
        groups.setdefault(_category(rel), []).append(
            (name, rel_dir, description, _when_to_use(fm))
        )
        total += 1

    # Categories: the fork's own desk skills (top-level) first, then alphabetical.
    ordered = ([_TOP_LEVEL] if _TOP_LEVEL in groups else []) + sorted(
        c for c in groups if c != _TOP_LEVEL
    )

    blocks: list[str] = [
        header(
            "Skills",
            SOURCE,
            blurb=(
                f"The agent loads **skills** — self-contained capability bundles —"
                f" on demand. There are **{total} skills** in **{len(groups)}"
                f" categories**, indexed here straight from each `SKILL.md`'s"
                f" frontmatter. *When to use* is the skill's declared `triggers`"
                f" list when it has one, otherwise the `Use when…` guidance mined"
                f" from its description. Skills directly under `skills/` (the"
                f" forecasting desk's own) are listed first."
            ),
        ),
        "| category | count |\n| --- | --- |\n"
        + "\n".join(f"| `{c}` | {len(groups[c])} |" for c in ordered),
    ]

    for category in ordered:
        rows = ["| skill | when to use | what it does |", "| --- | --- | --- |"]
        for name, rel_dir, description, when in sorted(groups[category]):
            rows.append(f"| `{name}`<br>`{rel_dir}` | {when} | {description} |")
        blocks.append(f"## {category}\n\n" + "\n".join(rows))

    return "\n\n".join(blocks) + "\n"
