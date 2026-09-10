"""Load repository metadata using an explicitly supplied JSON reader."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .github_metadata import _github_repo_parts, _github_timestamp
from .technology_records import GitHubRepositorySnapshot
from .values import _optional_str, _optional_int, _collapse_ws

def load_github_repository_snapshots(
    source: str,
    *,
    limit: int = 1,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[GitHubRepositorySnapshot]:
    """Load a GitHub repository metadata snapshot as software adoption evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubrepo import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    endpoint = f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/{quote(repo_name, safe='')}"
    payload = _read_json_endpoint(endpoint, "github repository")
    if not isinstance(payload, dict):
        raise ValidationError("github repository response must be an object")

    updated_at = _github_timestamp(payload.get("updated_at"))
    pushed_at = _github_timestamp(payload.get("pushed_at"))
    created_at = _github_timestamp(payload.get("created_at"))
    available_at = updated_at or pushed_at or created_at
    available_dt = timestamp_to_datetime(available_at) if available_at else None
    if since_dt is not None and available_dt is not None and available_dt < since_dt:
        return []

    owner_payload = payload.get("owner") if isinstance(payload.get("owner"), dict) else {}
    license_payload = payload.get("license") if isinstance(payload.get("license"), dict) else {}
    topic_values = payload.get("topics") if isinstance(payload.get("topics"), list) else []
    topics = [str(topic) for topic in topic_values if isinstance(topic, str)]
    snapshot = GitHubRepositorySnapshot(
        repo=_optional_str(payload.get("full_name")) or repo,
        repo_id=_optional_str(payload.get("id")),
        owner_login=_optional_str(owner_payload.get("login")) or owner,
        description=_collapse_ws(_optional_str(payload.get("description")) or ""),
        language=_optional_str(payload.get("language")),
        default_branch=_optional_str(payload.get("default_branch")),
        visibility=_optional_str(payload.get("visibility")),
        license_spdx_id=_optional_str(license_payload.get("spdx_id")),
        topics=topics,
        archived=bool(payload.get("archived")),
        disabled=bool(payload.get("disabled")),
        fork=bool(payload.get("fork")),
        stargazers_count=_optional_int(payload.get("stargazers_count")),
        watchers_count=_optional_int(payload.get("watchers_count")),
        forks_count=_optional_int(payload.get("forks_count")),
        open_issues_count=_optional_int(payload.get("open_issues_count")),
        subscribers_count=_optional_int(payload.get("subscribers_count")),
        network_count=_optional_int(payload.get("network_count")),
        created_at=created_at,
        updated_at=updated_at,
        pushed_at=pushed_at,
        url=_optional_str(payload.get("url")),
        html_url=_optional_str(payload.get("html_url")),
        source_name="GitHub",
        entry_id=_optional_str(payload.get("node_id")) or _optional_str(payload.get("id")) or repo,
        raw={
            "id": payload.get("id"),
            "node_id": payload.get("node_id"),
            "full_name": payload.get("full_name"),
            "description": payload.get("description"),
            "language": payload.get("language"),
            "default_branch": payload.get("default_branch"),
            "visibility": payload.get("visibility"),
            "license_spdx_id": license_payload.get("spdx_id"),
            "topics": topics,
            "archived": payload.get("archived"),
            "disabled": payload.get("disabled"),
            "fork": payload.get("fork"),
            "stargazers_count": payload.get("stargazers_count"),
            "watchers_count": payload.get("watchers_count"),
            "forks_count": payload.get("forks_count"),
            "open_issues_count": payload.get("open_issues_count"),
            "subscribers_count": payload.get("subscribers_count"),
            "network_count": payload.get("network_count"),
            "created_at": created_at,
            "updated_at": updated_at,
            "pushed_at": pushed_at,
        },
    )
    return [snapshot][:limit]
