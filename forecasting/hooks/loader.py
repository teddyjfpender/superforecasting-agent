"""Load + compile user-defined hook rules from config (inline) + a workspace
``rules_file``. Invalid rules are skipped with a warn-once message (a broken
rules file must never brick every commit), mirroring the config layer's
degrade-don't-crash discipline.
"""

from __future__ import annotations

import logging
import os

from forecasting.hooks.dsl import RuleSpec, compile_rule, validate_rule
from forecasting.hooks.spec import SimpleRule

logger = logging.getLogger(__name__)

_warned: set[str] = set()


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning("forecast-hooks: %s", message)


def _rules_file_path(rel: str) -> str | None:
    try:
        from superforecasting_agent.constants import get_agent_home

        return os.path.join(str(get_agent_home()), rel)
    except Exception:
        return None


def _read_rules_file(rel: str) -> list[dict]:
    """Read current specifications without relying on file metadata."""
    path = _rules_file_path(rel)
    if not path or not os.path.exists(path):
        return []
    try:
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or []
        specs = (
            [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
        )
        return specs
    except Exception as e:  # noqa: BLE001
        _warn_once(
            f"rulesfile:{rel}",
            f"could not parse rules_file {rel}: {e}; user rules skipped",
        )
        return []


def load_user_rule_specs(hooks_config: dict) -> list[dict]:
    """The RAW rule-spec dicts (inline + rules_file), unvalidated/uncompiled —
    for `forecast hooks lint` to validate + report each."""
    inline = [d for d in (hooks_config.get("rules") or []) if isinstance(d, dict)]
    rel = hooks_config.get("rules_file")
    file_specs = _read_rules_file(rel) if rel else []
    return [*inline, *file_specs]


def load_user_rules(hooks_config: dict) -> list[SimpleRule]:
    """Compile the configured user rules (inline + rules_file). Invalid rules are
    dropped with a warn-once. Compile current values on each load: list identity
    and file metadata cannot establish whether a validation policy changed."""
    inline = [d for d in (hooks_config.get("rules") or []) if isinstance(d, dict)]
    rel = hooks_config.get("rules_file")
    file_specs = _read_rules_file(rel) if rel else []

    compiled: list[SimpleRule] = []
    known: set[str] = set()
    for raw in [*inline, *file_specs]:
        spec = RuleSpec.from_dict(raw)
        issues = validate_rule(spec, known_ids=known)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            _warn_once(
                f"rule:{spec.id or raw}",
                f"rule {spec.id or '(no id)'} invalid, skipped: {errors[0].message}",
            )
            continue
        known.add(spec.id)
        compiled.append(compile_rule(spec))
    return compiled


def clear_cache() -> None:
    """Compatibility reset for warning suppression; rules are never cached."""
    _warned.clear()
