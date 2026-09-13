"""Shared provider quota inspection for command consumers."""


def google_quota_lines(argument: str = "") -> list[str]:
    """Inspect the active account without constructing an agent or CLI runtime."""
    if argument.strip():
        raise ValueError("Usage: /gquota")
    try:
        from agent.google_code_assist import CodeAssistError, retrieve_user_quota
        from agent.google_oauth import (
            GoogleOAuthError,
            get_valid_access_token,
            load_credentials,
        )
    except ImportError as exc:
        return [f"Gemini modules unavailable: {exc}"]
    try:
        access_token = get_valid_access_token()
    except GoogleOAuthError as exc:
        return [str(exc), "Run /model and pick 'Google Gemini (OAuth)' to sign in."]
    credentials = load_credentials()
    project_id = (credentials.project_id if credentials else "") or ""
    try:
        buckets = retrieve_user_quota(access_token, project_id=project_id)
    except CodeAssistError as exc:
        return [f"Quota lookup failed: {exc}"]
    if not buckets:
        return ["No quota buckets reported (account may be on legacy/unmetered tier)."]
    lines = [
        f"Gemini Code Assist quota (project: {project_id or '(auto / free-tier)'})",
        "",
    ]
    for bucket in sorted(buckets, key=lambda item: (item.model_id, item.token_type)):
        fraction = max(0.0, min(1.0, bucket.remaining_fraction))
        filled = int(round(fraction * 20))
        bar = "▓" * filled + "░" * (20 - filled)
        header = bucket.model_id
        if bucket.token_type:
            header += f" [{bucket.token_type}]"
        lines.append(f"{header:40s}  {bar}  {int(fraction * 100):3d}%")
    return lines
