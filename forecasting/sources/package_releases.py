"""Load package release evidence through an explicitly supplied JSON reader."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from urllib.parse import quote

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .technology_records import PypiRelease, NpmPackageVersion
from .values import _optional_str, _collapse_ws, _collapse_optional
from .package_registry import (
    _pypi_package_name, _pypi_project_endpoint, _pypi_upload_timestamp, _pypi_yanked_reason,
    _npm_package_name, _npm_package_endpoint, _npm_timestamp, _npm_license,
    _npm_people, _npm_keywords, _npm_dependency_count,
)

def load_pypi_releases(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://pypi.org/pypi",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[PypiRelease]:
    """Load PyPI package releases as timestamped software ecosystem evidence."""

    package = _pypi_package_name(source)
    if limit <= 0:
        raise ValidationError("pypi import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _pypi_project_endpoint(package, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "pypi package")
    if not isinstance(payload, dict):
        raise ValidationError("pypi package response must be a JSON object")
    info = payload.get("info") if isinstance(payload.get("info"), dict) else {}
    releases_payload = payload.get("releases")
    if not isinstance(releases_payload, dict):
        raise ValidationError("pypi package response must include a releases object")

    package_name = _collapse_ws(_optional_str(info.get("name")) or package)
    summary = _collapse_ws(_optional_str(info.get("summary")) or "")
    project_url = _optional_str(info.get("package_url")) or f"https://pypi.org/project/{quote(package_name, safe='')}/"
    rows: list[PypiRelease] = []
    for version, files_value in releases_payload.items():
        version_text = _optional_str(version)
        if not version_text:
            continue
        files = [item for item in files_value if isinstance(item, dict)] if isinstance(files_value, list) else []
        upload_times = [
            uploaded_at
            for item in files
            for uploaded_at in [_pypi_upload_timestamp(item)]
            if uploaded_at is not None
        ]
        uploaded_at = min(upload_times) if upload_times else None
        latest_upload_at = max(upload_times) if upload_times else None
        available_dt = timestamp_to_datetime(latest_upload_at or uploaded_at) if latest_upload_at or uploaded_at else None
        if since_dt is not None and (available_dt is None or available_dt < since_dt):
            continue
        package_types = sorted(
            {
                text
                for item in files
                for text in [_collapse_optional(item.get("packagetype"))]
                if text
            }
        )
        python_versions = sorted(
            {
                text
                for item in files
                for text in [_collapse_optional(item.get("python_version"))]
                if text
            }
        )
        yanked_reason = _pypi_yanked_reason(files)
        rows.append(
            PypiRelease(
                package=package_name,
                version=version_text,
                summary=summary,
                url=f"https://pypi.org/project/{quote(package_name, safe='')}/{quote(version_text, safe='')}/",
                project_url=project_url,
                uploaded_at=uploaded_at,
                latest_upload_at=latest_upload_at,
                file_count=len(files),
                package_types=package_types,
                python_versions=python_versions,
                yanked=any(bool(item.get("yanked")) for item in files),
                yanked_reason=yanked_reason,
                source_name="PyPI",
                entry_id=f"{package_name}:{version_text}",
                raw={
                    "package": package_name,
                    "version": version_text,
                    "summary": summary,
                    "latest_version": info.get("version"),
                    "uploaded_at": uploaded_at,
                    "latest_upload_at": latest_upload_at,
                    "file_count": len(files),
                    "package_types": package_types,
                    "python_versions": python_versions,
                    "yanked": any(bool(item.get("yanked")) for item in files),
                    "yanked_reason": yanked_reason,
                },
            )
        )

    rows.sort(
        key=lambda item: (
            timestamp_to_datetime(item.latest_upload_at or item.uploaded_at)
            or datetime.min.replace(tzinfo=timezone.utc),
            item.version,
        ),
        reverse=True,
    )
    return rows[:limit]


def load_npm_package_versions(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://registry.npmjs.org",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[NpmPackageVersion]:
    """Load npm package versions as timestamped software ecosystem evidence."""

    package = _npm_package_name(source)
    if limit <= 0:
        raise ValidationError("npm import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    endpoint = _npm_package_endpoint(package, api_base_url=api_base_url)
    payload = _read_json_endpoint(endpoint, "npm package")
    if not isinstance(payload, dict):
        raise ValidationError("npm package response must be a JSON object")
    versions_payload = payload.get("versions")
    if not isinstance(versions_payload, dict):
        raise ValidationError("npm package response must include a versions object")
    times = payload.get("time") if isinstance(payload.get("time"), dict) else {}
    package_name = _collapse_ws(_optional_str(payload.get("name")) or package)
    package_description = _collapse_ws(_optional_str(payload.get("description")) or "")

    rows: list[NpmPackageVersion] = []
    for version, row in versions_payload.items():
        if not isinstance(row, dict):
            continue
        version_text = _optional_str(version)
        if not version_text:
            continue
        published_at = _npm_timestamp(times.get(version_text))
        published_dt = timestamp_to_datetime(published_at) if published_at else None
        if since_dt is not None and (published_dt is None or published_dt < since_dt):
            continue
        description = _collapse_ws(_optional_str(row.get("description")) or package_description)
        dist = row.get("dist") if isinstance(row.get("dist"), dict) else {}
        rows.append(
            NpmPackageVersion(
                package=package_name,
                version=version_text,
                description=description,
                url=f"https://www.npmjs.com/package/{quote(package_name, safe='@/')}/v/{quote(version_text, safe='')}",
                tarball_url=_optional_str(dist.get("tarball")),
                published_at=published_at,
                license=_npm_license(row.get("license")),
                maintainers=_npm_people(row.get("maintainers")),
                keywords=_npm_keywords(row.get("keywords")),
                deprecated=_collapse_optional(row.get("deprecated")),
                dependency_count=_npm_dependency_count(row),
                source_name="npm",
                entry_id=f"{package_name}:{version_text}",
                raw={
                    "package": package_name,
                    "version": version_text,
                    "description": description,
                    "dist_tags": payload.get("dist-tags") if isinstance(payload.get("dist-tags"), dict) else {},
                    "published_at": published_at,
                    "tarball_url": _optional_str(dist.get("tarball")),
                    "license": _npm_license(row.get("license")),
                    "deprecated": _collapse_optional(row.get("deprecated")),
                    "dependency_count": _npm_dependency_count(row),
                },
            )
        )

    rows.sort(
        key=lambda item: (
            timestamp_to_datetime(item.published_at) or datetime.min.replace(tzinfo=timezone.utc),
            item.version,
        ),
        reverse=True,
    )
    return rows[:limit]
