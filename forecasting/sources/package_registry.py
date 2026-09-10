"""Parse package-registry identifiers, endpoints, and release metadata."""

from __future__ import annotations

from urllib.parse import quote, unquote, urlparse

from forecasting.models import ValidationError, parse_timestamp
from .values import _first_present, _optional_str, _collapse_optional
from forecasting.sources.dates import _optional_iso_timestamp


def _pypi_package_name(source: str) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if len(parts) >= 2 and parts[0] == "project":
            package = parts[1]
        elif len(parts) >= 2 and parts[0] == "pypi":
            package = parts[1]
        else:
            raise ValidationError("pypi source URL must be a PyPI project or JSON API URL")
    else:
        package = value
    package = package.strip()
    if not package:
        raise ValidationError("pypi source must be a package name, pypi:<package>, or a PyPI project URL")
    if "/" in package or any(ch.isspace() for ch in package):
        raise ValidationError("pypi package names cannot contain slashes or whitespace")
    return package


def _pypi_project_endpoint(package: str, *, api_base_url: str) -> str:
    base = api_base_url.rstrip("/")
    if "{package}" in base:
        return base.format(package=quote(package, safe=""))
    if base.endswith("/json"):
        return base
    return f"{base}/{quote(package, safe='')}/json"


def _pypi_upload_timestamp(item: dict) -> str | None:
    value = _first_present(item.get("upload_time_iso_8601"), item.get("upload_time"))
    text = _optional_str(value)
    if not text:
        return None
    try:
        return parse_timestamp(text, field_name="pypi upload time")
    except ValidationError:
        return None


def _pypi_yanked_reason(files: list[dict]) -> str | None:
    for item in files:
        if not item.get("yanked"):
            continue
        reason = _collapse_optional(item.get("yanked_reason"))
        if reason:
            return reason
    return None


def _npm_package_name(source: str) -> str:
    value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source.strip()
    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        parts = [unquote(part) for part in parsed.path.strip("/").split("/") if part]
        if parsed.netloc.lower().endswith("npmjs.com") and len(parts) >= 2 and parts[0] == "package":
            package = "/".join(parts[1:3]) if parts[1].startswith("@") and len(parts) >= 3 else parts[1]
        elif parsed.netloc.lower().endswith("npmjs.org") or parsed.netloc.lower().endswith("npmjs.com"):
            package = unquote(parsed.path.strip("/"))
        else:
            package = unquote(parsed.path.strip("/"))
    else:
        package = value
    package = package.strip()
    if not package:
        raise ValidationError("npm source must be a package name, npm:<package>, or an npm package URL")
    if any(ch.isspace() for ch in package):
        raise ValidationError("npm package names cannot contain whitespace")
    if "/" in package and not (package.startswith("@") and package.count("/") == 1):
        raise ValidationError("npm scoped package names must look like @scope/name")
    return package


def _npm_package_endpoint(package: str, *, api_base_url: str) -> str:
    base = api_base_url.rstrip("/")
    if "{package}" in base:
        return base.format(package=quote(package, safe=""))
    return f"{base}/{quote(package, safe='')}"


def _npm_timestamp(value: object) -> str | None:
    return _optional_iso_timestamp(value, field_name='npm package time')


def _npm_license(value: object) -> str | None:
    if isinstance(value, dict):
        return _collapse_optional(value.get("type") or value.get("name"))
    return _collapse_optional(value)


def _npm_people(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    people: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _collapse_optional(item.get("name") or item.get("email"))
        else:
            name = _collapse_optional(item)
        if name:
            people.append(name)
    return people


def _npm_keywords(value: object) -> list[str]:
    if isinstance(value, list):
        return [text for item in value for text in [_collapse_optional(item)] if text]
    text = _collapse_optional(value)
    if not text:
        return []
    return [part.strip() for part in text.split(",") if part.strip()]


def _npm_dependency_count(row: dict) -> int:
    names: set[str] = set()
    for key in ("dependencies", "optionalDependencies", "peerDependencies"):
        value = row.get(key)
        if isinstance(value, dict):
            names.update(str(name) for name in value if name)
    return len(names)
