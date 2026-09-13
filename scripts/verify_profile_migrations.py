#!/usr/bin/env python3
"""Seed with the installed old backend; verify profile and plugin migration after upgrade."""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import shutil
from pathlib import Path

MANAGED = "autonomous-ai-agents/hermes-agent"
CUSTOM = "software-development/hermes-agent-skill-authoring"
DELETED = "software-development/debugging-hermes-tui-commands"
CANONICAL_MANAGED = "autonomous-ai-agents/superforecasting-agent"
CANONICAL_CUSTOM = "software-development/superforecasting-agent-skill-authoring"
CANONICAL_DELETED = "software-development/debugging-superforecasting-tui-commands"


def profile_root() -> Path:
    return Path(os.environ["HERMES_HOME"])


def digests(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }


def verify_plugin() -> None:
    try:
        module = importlib.import_module("superforecasting_agent.runtime.plugins")
    except ModuleNotFoundError as exc:
        if exc.name not in {
            "superforecasting_agent.runtime",
            "superforecasting_agent.runtime.plugins",
        }:
            raise
        module = importlib.import_module("hermes_cli.plugins")
    module.discover_plugins()
    handler = module.get_plugin_command_handler("upgrade-fixture")
    if handler is None or handler("probe") != "compatible:probe":
        raise AssertionError(
            "Installed backend did not load and execute the legacy plugin: "
            + repr([
                item
                for item in module.get_plugin_manager().list_plugins()
                if item["name"] == "upgrade-fixture"
            ])
        )


def seed(root: Path) -> None:
    from tools.skills_sync import sync_skills

    sync_skills(quiet=True)
    skills = root / "skills"
    for relative in (MANAGED, CUSTOM, DELETED):
        if not (skills / relative / "SKILL.md").is_file():
            raise AssertionError(f"Old installed wheel did not seed {relative}")
    customized = skills / CUSTOM / "SKILL.md"
    customized.write_bytes(
        customized.read_bytes() + b"\nUser customization: preserve this note.\n"
    )
    shutil.rmtree(skills / DELETED)
    context = root / "HERMES.md"
    context.write_text(
        "# User context\n\nPreserve my forecast review rules.\n", encoding="utf-8"
    )
    plugin = root / "plugins/upgrade-fixture"
    plugin.mkdir(parents=True)
    (plugin / "plugin.yaml").write_text(
        "name: upgrade-fixture\nversion: 1.0.0\ndescription: Isolated upgrade compatibility fixture\n",
        encoding="utf-8",
    )
    (plugin / "__init__.py").write_text(
        "from tools.mcp_oauth import HermesTokenStorage\n"
        "def register(ctx):\n"
        "    assert HermesTokenStorage is not None\n"
        "    ctx.register_command('upgrade-fixture', lambda args: 'compatible:' + args)\n",
        encoding="utf-8",
    )
    (root / "config.yaml").write_text(
        "display:\n  skin: mono\nplugins:\n  enabled: [upgrade-fixture]\n",
        encoding="utf-8",
    )
    verify_plugin()
    receipt = {
        "custom": digests(skills / CUSTOM),
        "plugin": digests(plugin),
        "context": context.read_text(encoding="utf-8"),
    }
    (root / "upgrade-migration-fixture.json").write_text(
        json.dumps(receipt), encoding="utf-8"
    )


def verify(root: Path) -> None:
    from tools.skills_sync import sync_skills

    receipt = json.loads(
        (root / "upgrade-migration-fixture.json").read_text(encoding="utf-8")
    )
    skills = root / "skills"
    sync_skills(quiet=True)
    if (skills / MANAGED).exists() or not (
        skills / CANONICAL_MANAGED / "SKILL.md"
    ).is_file():
        raise AssertionError(
            "Unmodified bundled skill did not migrate to its canonical path"
        )
    if (
        digests(skills / CUSTOM) != receipt["custom"]
        or (skills / CANONICAL_CUSTOM).exists()
    ):
        raise AssertionError("Upgrade replaced or duplicated a customized skill")
    if (skills / DELETED).exists() or (skills / CANONICAL_DELETED).exists():
        raise AssertionError("Upgrade resurrected a deliberately deleted skill")
    if digests(root / "plugins/upgrade-fixture") != receipt["plugin"]:
        raise AssertionError("Upgrade modified the user plugin")
    if (root / "HERMES.md").read_text(encoding="utf-8") != receipt["context"]:
        raise AssertionError("Upgrade changed the legacy profile context")
    verify_plugin()
    before_retry = digests(skills)
    sync_skills(quiet=True)
    if digests(skills) != before_retry:
        raise AssertionError("Repeated skill migration is not idempotent")
    print(
        json.dumps({
            "legacy_profile": "passed",
            "managed_skills": "passed",
            "customized_skills": "passed",
            "deleted_skills": "passed",
            "plugin_execution": "passed",
            "idempotent_retry": "passed",
        })
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("seed", "verify"))
    args = parser.parse_args()
    (seed if args.action == "seed" else verify)(profile_root())


if __name__ == "__main__":
    main()
