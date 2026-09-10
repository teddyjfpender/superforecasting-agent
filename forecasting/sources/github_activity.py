"""Load GitHub release and activity evidence through a supplied JSON reader."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import quote, urlencode

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .github_metadata import _github_repo_parts, _github_timestamp, _github_label_names
from .technology_records import GitHubRelease, GitHubIssue, GitHubCommit, GitHubWorkflowRun
from .values import _optional_str, _optional_int, _collapse_ws

def load_github_releases(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[GitHubRelease]:
    """Load GitHub repository releases as timestamped software evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("github import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/releases?{urlencode({'per_page': min(limit, 100)})}"
    )
    payload = _read_json_endpoint(endpoint, "github releases")
    if not isinstance(payload, list):
        raise ValidationError("github releases response must be an array")

    releases: list[GitHubRelease] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        published_at = _github_timestamp(row.get("published_at"))
        created_at = _github_timestamp(row.get("created_at"))
        available_at = published_at or created_at
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        tag_name = _optional_str(row.get("tag_name")) or _optional_str(row.get("name")) or "untagged"
        name = _optional_str(row.get("name")) or tag_name
        release_id = _optional_str(row.get("id"))
        releases.append(
            GitHubRelease(
                repo=repo,
                release_id=release_id,
                tag_name=tag_name,
                name=_collapse_ws(name),
                body=_collapse_ws(_optional_str(row.get("body")) or ""),
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                created_at=created_at,
                published_at=published_at,
                draft=bool(row.get("draft")),
                prerelease=bool(row.get("prerelease")),
                source_name="GitHub",
                entry_id=release_id or tag_name,
                raw={
                    "id": row.get("id"),
                    "tag_name": row.get("tag_name"),
                    "name": row.get("name"),
                    "draft": row.get("draft"),
                    "prerelease": row.get("prerelease"),
                    "repo": repo,
                },
            )
        )
        if len(releases) >= limit:
            break
    return releases


def load_github_issues(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    state: str = "all",
    api_base_url: str = "https://api.github.com",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[GitHubIssue]:
    """Load GitHub repository issues and pull requests as timestamped software evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubissues import --limit must be positive")
    normalized_state = state.strip().lower()
    if normalized_state not in {"open", "closed", "all"}:
        raise ValidationError("githubissues import --state must be open, closed, or all")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    params: dict[str, object] = {
        "state": normalized_state,
        "per_page": min(limit, 100),
        "sort": "updated",
        "direction": "desc",
    }
    if since_ts:
        params["since"] = since_ts
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/issues?{urlencode(params)}"
    )
    payload = _read_json_endpoint(endpoint, "github issues")
    if not isinstance(payload, list):
        raise ValidationError("github issues response must be an array")

    issues: list[GitHubIssue] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        updated_at = _github_timestamp(row.get("updated_at"))
        created_at = _github_timestamp(row.get("created_at"))
        closed_at = _github_timestamp(row.get("closed_at"))
        available_at = updated_at or created_at
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        title = _collapse_ws(_optional_str(row.get("title")) or "Untitled GitHub issue")
        issue_number = _optional_int(row.get("number"))
        labels = _github_label_names(row.get("labels"))
        user = row.get("user")
        author = _optional_str(user.get("login")) if isinstance(user, dict) else None
        is_pull_request = isinstance(row.get("pull_request"), dict)
        issues.append(
            GitHubIssue(
                repo=repo,
                issue_number=issue_number,
                title=title,
                state=_optional_str(row.get("state")),
                is_pull_request=is_pull_request,
                author=author,
                labels=labels,
                created_at=created_at,
                updated_at=updated_at,
                closed_at=closed_at,
                comments=_optional_int(row.get("comments")),
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                source_name="GitHub",
                entry_id=f"{repo}#{issue_number}" if issue_number is not None else _optional_str(row.get("id")),
                raw={
                    "id": row.get("id"),
                    "number": row.get("number"),
                    "state": row.get("state"),
                    "title": row.get("title"),
                    "repo": repo,
                    "is_pull_request": is_pull_request,
                    "labels": labels,
                },
            )
        )
        if len(issues) >= limit:
            break
    return issues


def load_github_commits(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[GitHubCommit]:
    """Load GitHub repository commits as timestamped software activity evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubcommits import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    params: dict[str, object] = {"per_page": min(limit, 100)}
    if since_ts:
        params["since"] = since_ts
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/commits?{urlencode(params)}"
    )
    payload = _read_json_endpoint(endpoint, "github commits")
    if not isinstance(payload, list):
        raise ValidationError("github commits response must be an array")

    commits: list[GitHubCommit] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        sha = _optional_str(row.get("sha"))
        if not sha:
            continue
        commit = row.get("commit") if isinstance(row.get("commit"), dict) else {}
        author = commit.get("author") if isinstance(commit.get("author"), dict) else {}
        committer = commit.get("committer") if isinstance(commit.get("committer"), dict) else {}
        github_author = row.get("author") if isinstance(row.get("author"), dict) else {}
        authored_at = _github_timestamp(author.get("date"))
        committed_at = _github_timestamp(committer.get("date")) or authored_at
        available_dt = timestamp_to_datetime(committed_at or authored_at) if committed_at or authored_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        message = _collapse_ws(_optional_str(commit.get("message")) or "Untitled GitHub commit")
        commits.append(
            GitHubCommit(
                repo=repo,
                sha=sha,
                short_sha=sha[:7],
                message=message,
                author_name=_optional_str(author.get("name")),
                author_login=_optional_str(github_author.get("login")),
                authored_at=authored_at,
                committed_at=committed_at,
                comments=_optional_int(commit.get("comment_count")),
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                source_name="GitHub",
                entry_id=f"{repo}@{sha}",
                raw={
                    "sha": sha,
                    "repo": repo,
                    "message": commit.get("message"),
                    "author_name": author.get("name"),
                    "author_login": github_author.get("login"),
                    "authored_at": authored_at,
                    "committed_at": committed_at,
                },
            )
        )
        if len(commits) >= limit:
            break
    return commits


def load_github_workflow_runs(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://api.github.com",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[GitHubWorkflowRun]:
    """Load GitHub Actions workflow runs as timestamped operational evidence."""

    owner, repo_name = _github_repo_parts(source)
    if limit <= 0:
        raise ValidationError("githubactions import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    repo = f"{owner}/{repo_name}"
    endpoint = (
        f"{api_base_url.rstrip('/')}/repos/{quote(owner, safe='')}/"
        f"{quote(repo_name, safe='')}/actions/runs?{urlencode({'per_page': min(limit, 100)})}"
    )
    payload = _read_json_endpoint(endpoint, "github actions workflow runs")
    if not isinstance(payload, dict):
        raise ValidationError("github actions workflow runs response must be an object")
    rows = payload.get("workflow_runs")
    if not isinstance(rows, list):
        raise ValidationError("github actions workflow runs response must include workflow_runs array")

    runs: list[GitHubWorkflowRun] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        run_id = _optional_str(row.get("id"))
        if not run_id:
            continue
        created_at = _github_timestamp(row.get("created_at"))
        updated_at = _github_timestamp(row.get("updated_at"))
        run_started_at = _github_timestamp(row.get("run_started_at"))
        available_at = updated_at or run_started_at or created_at
        available_dt = timestamp_to_datetime(available_at) if available_at else None
        if since_dt is not None and available_dt is not None and available_dt < since_dt:
            continue
        actor = row.get("actor") if isinstance(row.get("actor"), dict) else {}
        triggering_actor = row.get("triggering_actor") if isinstance(row.get("triggering_actor"), dict) else {}
        head_sha = _optional_str(row.get("head_sha"))
        name = _collapse_ws(_optional_str(row.get("name")) or "GitHub Actions workflow")
        display_title = _collapse_ws(_optional_str(row.get("display_title")) or name)
        runs.append(
            GitHubWorkflowRun(
                repo=repo,
                run_id=run_id,
                name=name,
                display_title=display_title,
                status=_optional_str(row.get("status")),
                conclusion=_optional_str(row.get("conclusion")),
                event=_optional_str(row.get("event")),
                head_branch=_optional_str(row.get("head_branch")),
                head_sha=head_sha,
                short_sha=head_sha[:7] if head_sha else None,
                workflow_id=_optional_str(row.get("workflow_id")),
                workflow_url=_optional_str(row.get("workflow_url")),
                actor_login=_optional_str(actor.get("login")),
                triggering_actor_login=_optional_str(triggering_actor.get("login")),
                run_started_at=run_started_at,
                created_at=created_at,
                updated_at=updated_at,
                url=_optional_str(row.get("url")),
                html_url=_optional_str(row.get("html_url")),
                source_name="GitHub",
                entry_id=f"{repo}/actions/runs/{run_id}",
                raw={
                    "id": row.get("id"),
                    "repo": repo,
                    "name": row.get("name"),
                    "display_title": row.get("display_title"),
                    "status": row.get("status"),
                    "conclusion": row.get("conclusion"),
                    "event": row.get("event"),
                    "head_branch": row.get("head_branch"),
                    "head_sha": head_sha,
                    "workflow_id": row.get("workflow_id"),
                    "actor_login": actor.get("login"),
                    "triggering_actor_login": triggering_actor.get("login"),
                    "run_started_at": run_started_at,
                    "created_at": created_at,
                    "updated_at": updated_at,
                },
            )
        )
        if len(runs) >= limit:
            break
    return runs
