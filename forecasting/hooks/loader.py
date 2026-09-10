"""Load + compile user-defined hook rules from config (inline) + a workspace
``rules_file``. Invalid rules are skipped with a warn-once message (a broken
rules file must never brick every commit), mirroring the config layer's
degrade-don't-crash discipline.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from forecasting.hooks.dsl import RuleSpec, compile_rule, validate_rule
from forecasting.hooks.spec import SimpleRule

logger = logging.getLogger(__name__)

_warned: set[str] = set()
_cache: dict[Any, list[SimpleRule]] = {}


def _warn_once(key: str, message: str) -> None:
    if key not in _warned:
        _warned.add(key)
        logger.warning("forecast-hooks: %s", message)


def _rules_file_path(rel: str) -> str | None:
    try:
        from superforecasting_agent.runtime.config import get_config_path

        return os.path.join(str(get_config_path().parent), rel)
    except Exception:
        return None


def _read_rules_file(rel: str) -> tuple[list[dict], Any]:
    """Return (specs, cache_key_part). cache_key_part is (mtime, size) or None."""
    path = _rules_file_path(rel)
    if not path or not os.path.exists(path):
        return [], None
    try:
        st = os.stat(path)
        import yaml

        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or []
        specs = [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []
        return specs, (path, st.st_mtime_ns, st.st_size)
    except Exception as e:  # noqa: BLE001
        _warn_once(f"rulesfile:{rel}", f"could not parse rules_file {rel}: {e}; user rules skipped")
        return [], (path, "error")


def load_user_rule_specs(hooks_config: dict) -> list[dict]:
    """The RAW rule-spec dicts (inline + rules_file), unvalidated/uncompiled —
    for `forecast hooks lint` to validate + report each."""
    inline = [d for d in (hooks_config.get("rules") or []) if isinstance(d, dict)]
    rel = hooks_config.get("rules_file")
    file_specs = _read_rules_file(rel)[0] if rel else []
    return [*inline, *file_specs]


def load_user_rules(hooks_config: dict) -> list[SimpleRule]:
    """Compile the configured user rules (inline + rules_file). Invalid rules are
    dropped with a warn-once. Cached on the inline-rules identity + file stat."""
    inline = [d for d in (hooks_config.get("rules") or []) if isinstance(d, dict)]
    rel = hooks_config.get("rules_file")
    file_specs, file_key = _read_rules_file(rel) if rel else ([], None)

    cache_key = (id(hooks_config.get("rules")), len(inline), file_key)
    if cache_key in _cache:
        return _cache[cache_key]

    compiled: list[SimpleRule] = []
    known: set[str] = set()
    for raw in [*inline, *file_specs]:
        spec = RuleSpec.from_dict(raw)
        issues = validate_rule(spec, known_ids=known)
        errors = [i for i in issues if i.severity == "error"]
        if errors:
            _warn_once(f"rule:{spec.id or raw}", f"rule {spec.id or '(no id)'} invalid, skipped: {errors[0].message}")
            continue
        known.add(spec.id)
        compiled.append(compile_rule(spec))
    _cache[cache_key] = compiled
    return compiled


def clear_cache() -> None:
    _cache.clear()
    _warned.clear()
