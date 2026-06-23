"""Write layer for forecast hooks — the single place that mutates the hook
policy (config.yaml `forecasting.hooks`) and the user rules file. Used by both
the `forecast hooks` CLI write-commands and the gateway write RPCs, so the TUI
and CLI share one validated, atomic write path. Reads stay in engine/loader.
"""

from __future__ import annotations

import os
from typing import Any

from forecasting.hooks.builtins import BUILTIN_RULE_IDS
from forecasting.hooks.dsl import RuleSpec, validate_rule
from forecasting.hooks.profiles import HOOK_PROFILES

_SEVERITIES = ("off", "warn", "error")
_DEFAULT_RULES_FILE = "hooks/rules.yaml"


class HookWriteError(ValueError):
    """A hook write was refused (invalid severity/profile/rule). Message is
    user-facing; ``issues`` carries the DSL teaching issues for a bad rule."""

    def __init__(self, message: str, issues: list | None = None):
        super().__init__(message)
        self.issues = issues or []


# ── config (profile / severities / enabled) ───────────────────────────────────
def _hooks_block(config: dict) -> dict:
    return config.setdefault("forecasting", {}).setdefault("hooks", {})


def _known_rule_ids() -> set[str]:
    from forecasting.hooks.engine import load_hook_config
    from forecasting.hooks.loader import load_user_rule_specs

    ids = set(BUILTIN_RULE_IDS)
    for raw in load_user_rule_specs(load_hook_config()):
        rid = str(raw.get("id") or "").strip()
        if rid:
            ids.add(rid)
    return ids


def _save(config: dict) -> None:
    from hermes_cli.config import save_config

    save_config(config)


def _load() -> dict:
    from hermes_cli.config import load_config

    return load_config()


def set_severity(rule_id: str, severity: str) -> dict[str, Any]:
    severity = (severity or "").strip().lower()
    if severity not in _SEVERITIES:
        raise HookWriteError(f"severity must be one of {', '.join(_SEVERITIES)} (got {severity!r})")
    if rule_id not in _known_rule_ids():
        raise HookWriteError(f"unknown rule {rule_id!r} (not a built-in or user rule)")
    cfg = _load()
    _hooks_block(cfg).setdefault("overrides", {})[rule_id] = severity
    _save(cfg)
    return {"rule_id": rule_id, "severity": severity}


def clear_override(rule_id: str) -> dict[str, Any]:
    cfg = _load()
    (_hooks_block(cfg).get("overrides") or {}).pop(rule_id, None)
    _save(cfg)
    return {"rule_id": rule_id, "cleared": True}


def enable(rule_id: str) -> dict[str, Any]:
    """Enable = revert to the profile's severity for this rule (drop the override)."""
    if rule_id not in _known_rule_ids():
        raise HookWriteError(f"unknown rule {rule_id!r}")
    return clear_override(rule_id)


def disable(rule_id: str) -> dict[str, Any]:
    return set_severity(rule_id, "off")


def set_profile(name: str) -> dict[str, Any]:
    if name not in HOOK_PROFILES:
        raise HookWriteError(f"unknown profile {name!r}; choose from {', '.join(HOOK_PROFILES)}")
    cfg = _load()
    _hooks_block(cfg)["profile"] = name
    _save(cfg)
    return {"profile": name}


def set_enabled(enabled: bool) -> dict[str, Any]:
    cfg = _load()
    _hooks_block(cfg)["enabled"] = bool(enabled)
    _save(cfg)
    return {"enabled": bool(enabled)}


# ── user rules file ────────────────────────────────────────────────────────────
def _rules_path() -> str:
    from forecasting.hooks.engine import load_hook_config
    from hermes_cli.config import get_config_path

    rel = (load_hook_config().get("rules_file") or _DEFAULT_RULES_FILE)
    return os.path.join(str(get_config_path().parent), rel)


def _read_rules() -> list[dict]:
    path = _rules_path()
    if not os.path.exists(path):
        return []
    import yaml

    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _write_rules(rules: list[dict]) -> None:
    path = _rules_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from utils import atomic_yaml_write

        atomic_yaml_write(path, rules)
    except Exception:
        import yaml

        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            yaml.safe_dump(rules, fh, sort_keys=False)
        os.replace(tmp, path)
    # invalidate the loader cache so the next read sees the change
    try:
        from forecasting.hooks.loader import clear_cache

        clear_cache()
    except Exception:
        pass


def _validate_or_raise(spec_dict: dict, *, known_ids: set[str]) -> RuleSpec:
    spec = RuleSpec.from_dict(spec_dict)
    issues = validate_rule(spec, known_ids=known_ids)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        raise HookWriteError(f"rule {spec.id or '(no id)'} is invalid: {errors[0].message}", issues=issues)
    return spec


def save_rule(spec_dict: dict) -> dict[str, Any]:
    """Validate + APPEND a new user rule. Rejects an id that already exists
    (built-in or user) or a rule that fails validation."""
    rules = _read_rules()
    existing = {str(r.get("id") or "") for r in rules}
    spec = _validate_or_raise(spec_dict, known_ids=existing)
    if spec.id in existing or spec.id in BUILTIN_RULE_IDS:
        raise HookWriteError(f"rule id {spec.id!r} already exists; use edit instead")
    rules.append(spec_dict)
    _write_rules(rules)
    return {"id": spec.id, "saved": True}


def edit_rule(rule_id: str, spec_dict: dict) -> dict[str, Any]:
    """Validate + REPLACE an existing user rule (matched by id)."""
    rules = _read_rules()
    idx = next((i for i, r in enumerate(rules) if str(r.get("id") or "") == rule_id), None)
    if idx is None:
        raise HookWriteError(f"user rule {rule_id!r} not found")
    others = {str(r.get("id") or "") for i, r in enumerate(rules) if i != idx}
    _validate_or_raise({**spec_dict, "id": rule_id}, known_ids=others)
    rules[idx] = {**spec_dict, "id": rule_id}
    _write_rules(rules)
    return {"id": rule_id, "edited": True}


def remove_rule(rule_id: str) -> dict[str, Any]:
    rules = _read_rules()
    kept = [r for r in rules if str(r.get("id") or "") != rule_id]
    if len(kept) == len(rules):
        raise HookWriteError(f"user rule {rule_id!r} not found")
    _write_rules(kept)
    return {"id": rule_id, "removed": True}
