"""Parse shared GitHub source identifiers and metadata."""

from __future__ import annotations

from urllib.parse import urlparse

from forecasting.models import ValidationError, parse_timestamp
from .values import _optional_str, _collapse_optional
from forecasting.sources.dates import _optional_iso_timestamp

def _github_repo_parts(source: str) -> tuple[str, str]:
    value = (
        source.split(":", 1)[1].strip()
        if source.startswith(("github:", "githubrepo:", "githubissues:", "githubcommits:", "githubactions:"))
        else source.strip()
    )
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc.lower() == "github.com":
        parts = [part for part in parsed.path.strip("/").split("/") if part]
    else:
        parts = [part for part in value.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValidationError(
            "github source must be owner/repo, github:owner/repo, githubrepo:owner/repo, "
            "githubissues:owner/repo, githubcommits:owner/repo, githubactions:owner/repo, "
            "or a GitHub repository URL"
        )
    owner, repo = parts[0], parts[1]
    if not owner or not repo:
        raise ValidationError("github source must include owner and repo")
    return owner, repo.removesuffix(".git")


def _github_label_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    labels: list[str] = []
    for item in value:
        if isinstance(item, dict):
            label = _collapse_optional(item.get("name"))
        else:
            label = _collapse_optional(item)
        if label:
            labels.append(label)
    return labels


def _github_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='github timestamp')
