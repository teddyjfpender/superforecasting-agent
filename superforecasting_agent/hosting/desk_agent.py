"""Forecast desk construction from a captured profile and launch overrides.

The transport reads environment/session aliases and supplies callbacks. This owner
never imports a transport, reads its globals, or opens replacement session storage.
"""

from collections.abc import Callable, Mapping
from typing import Any

from superforecasting_agent.configuration import resolve_config
from superforecasting_agent.configuration.agent_limits import agent_turn_budget
from superforecasting_agent.constants import parse_reasoning_effort, parse_service_tier
from superforecasting_agent.environment import is_truthy_value


def selected_model(config: Mapping[str, Any], override: str = "") -> str:
    if override:
        return override
    model = config.get("model", "")
    if isinstance(model, dict):
        return str(model.get("default", "") or "").strip()
    if isinstance(model, str) and model:
        return model.strip()
    return "anthropic/claude-sonnet-4"


def startup_runtime(
    config: Mapping[str, Any], overrides: Mapping[str, str]
) -> tuple[str, str | None]:
    explicit_model = overrides.get("model", "")
    model = selected_model(config, explicit_model)
    explicit_provider = overrides.get("provider", "").strip()
    if explicit_provider:
        return model, explicit_provider
    if not explicit_model:
        return model, None
    try:
        from superforecasting_agent.runtime.models import (
            detect_static_provider_for_model,
        )

        section = config.get("model") or {}
        current_provider = (
            (
                str(section.get("provider") or "").strip().lower()
                if isinstance(section, dict)
                else ""
            )
            or overrides.get("inference_provider", "").lower()
            or "auto"
        )
        detected = detect_static_provider_for_model(explicit_model, current_provider)
        if detected:
            provider, detected_model = detected
            return detected_model, provider
    except Exception:
        # Static detection is best effort; the provider factory resolves later.
        pass
    return model, None


def reasoning_config(config: Mapping[str, Any]) -> dict | None:
    effort = str((config.get("agent") or {}).get("reasoning_effort", "") or "").strip()
    return parse_reasoning_effort(effort)


def service_tier(config: Mapping[str, Any]) -> str | None:
    return parse_service_tier((config.get("agent") or {}).get("service_tier"))


def tool_progress_mode(config: Mapping[str, Any], override: str = "") -> str:
    mode = override.strip().lower()
    if mode in {"off", "new", "all", "verbose"}:
        return mode
    raw = (config.get("display") or {}).get("tool_progress", "all")
    if raw is False:
        return "off"
    if raw is True:
        return "all"
    mode = str(raw or "all").strip().lower()
    return mode if mode in {"off", "new", "all", "verbose"} else "all"


def startup_skills(raw: str) -> list[str]:
    return list(
        dict.fromkeys(
            item for part in raw.replace("\n", ",").split(",") if (item := part.strip())
        )
    )


def build_desk_agent(
    config: dict[str, Any],
    *,
    overrides: Mapping[str, str],
    session_id: str,
    session_db: Any,
    callbacks: Mapping[str, Any],
    warn: Callable[[str], None],
) -> Any:
    """Build a hosted terminal desk using caller-owned session resources."""
    from agent.agent_factory import build_forecast_agent
    from superforecasting_agent.tooling.startup_selection import (
        resolve_startup_toolsets,
    )

    cfg = resolve_config(config)
    model, provider = startup_runtime(cfg, overrides)
    ignore_rules = is_truthy_value(overrides.get("ignore_rules", ""))
    return build_forecast_agent(
        system_prompt=(cfg.get("agent") or {}).get("system_prompt"),
        startup_skills=startup_skills(overrides.get("skills", "")),
        model=model,
        requested_provider=provider,
        configuration=cfg,
        max_iterations=agent_turn_budget(cfg, override=overrides.get("max_turns")),
        quiet_mode=True,
        verbose_logging=tool_progress_mode(cfg, overrides.get("tool_progress", ""))
        == "verbose",
        reasoning_config=reasoning_config(cfg),
        service_tier=service_tier(cfg),
        enabled_toolsets=resolve_startup_toolsets(
            overrides.get("toolsets", ""),
            setting_label="SUPERFORECASTING_AGENT_TUI_TOOLSETS",
            config=cfg,
            warn=warn,
        ),
        platform="tui",
        session_id=session_id,
        session_db=session_db,
        checkpoints_enabled=is_truthy_value(overrides.get("checkpoints", "")),
        pass_session_id=is_truthy_value(overrides.get("pass_session_id", "")),
        skip_context_files=ignore_rules,
        skip_memory=ignore_rules,
        **callbacks,
    )
