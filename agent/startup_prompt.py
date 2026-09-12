"""Shared startup prompt assembly for interactive forecasting clients."""


def prepare_startup_prompt(
    system_prompt: str | None, skills: list[str], *, session_id: str
) -> tuple[str, list[str]]:
    """Validate and append startup skills before constructing a model runtime."""
    if system_prompt is not None and not isinstance(system_prompt, str):
        raise ValueError("Agent system_prompt must be a string")
    prompt = (system_prompt or "").strip()
    if not skills:
        return prompt, []
    from agent.skill_commands import build_preloaded_skills_prompt

    skill_prompt, loaded, missing = build_preloaded_skills_prompt(
        skills, task_id=session_id
    )
    if missing:
        raise ValueError(f"Unknown skill(s): {', '.join(missing)}")
    if skill_prompt:
        prompt = "\n\n".join(part for part in (prompt, skill_prompt) if part).strip()
    return prompt, loaded
