"""Load CKAN open-data evidence records."""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse

from forecasting.models import ValidationError, parse_timestamp, timestamp_to_datetime
from .dates import _optional_epoch_or_iso_timestamp
from .economic_records import CkanDataset
from .values import _collapse_ws, _first_present, _optional_str

def load_ckan_datasets(
    source: str,
    *,
    limit: int = 10,
    since: str | None = None,
    api_base_url: str = "https://{domain}/api/3/action/package_search",
    _read_json_endpoint: Callable[[str, str], object],
) -> list[CkanDataset]:
    """Load CKAN open-data package metadata as timestamped evidence."""

    if limit <= 0:
        raise ValidationError("ckan import --limit must be positive")
    since_ts = parse_timestamp(since, field_name="since") if since else None
    since_dt = timestamp_to_datetime(since_ts) if since_ts else None
    portal, _query, endpoint = _ckan_endpoint(source, api_base_url=api_base_url, limit=limit)
    payload = _read_json_endpoint(endpoint, "ckan package search")
    rows = _ckan_package_results(payload)

    datasets: list[CkanDataset] = []
    for index, row in enumerate(rows):
        package_id = _optional_str(_first_present(row.get("id"), row.get("package_id")))
        name = _optional_str(row.get("name"))
        fallback_title = name or package_id or "Untitled CKAN dataset"
        title = _collapse_ws(
            _optional_str(_first_present(row.get("title"), row.get("display_name"))) or fallback_title
        )
        notes = _collapse_ws(_optional_str(_first_present(row.get("notes"), row.get("description"))) or "")
        metadata_created = _ckan_timestamp(
            _first_present(row.get("metadata_created"), row.get("metadata_created_at"), row.get("created"))
        )
        metadata_modified = _ckan_timestamp(
            _first_present(
                row.get("metadata_modified"),
                row.get("metadata_modified_at"),
                row.get("modified"),
                row.get("last_modified"),
            )
        )
        available_at = metadata_modified or metadata_created
        if since_dt is not None and available_at:
            available_dt = timestamp_to_datetime(available_at)
            if available_dt is not None and available_dt < since_dt:
                continue
        url = _optional_str(row.get("url"))
        source_url = (
            _optional_str(_first_present(row.get("metadata_url"), row.get("ckan_url")))
            or _ckan_public_dataset_url(portal, name or package_id, endpoint)
            or url
        )
        organization = _ckan_organization(row.get("organization")) or _optional_str(
            _first_present(row.get("organization_title"), row.get("organization"))
        )
        datasets.append(
            CkanDataset(
                portal=portal,
                package_id=package_id,
                name=name,
                title=title,
                notes=notes,
                url=url,
                organization=organization,
                groups=_ckan_names(row.get("groups")),
                tags=_ckan_names(row.get("tags")),
                license_title=_optional_str(_first_present(row.get("license_title"), row.get("license_id"))),
                metadata_created=metadata_created,
                metadata_modified=metadata_modified,
                resources=_ckan_resources(row.get("resources")),
                source_url=source_url,
                source_name=f"CKAN:{portal}",
                entry_id=f"{portal}:{name or package_id or index}",
                raw={"row_index": index, **dict(row)},
            )
        )
        if len(datasets) >= limit:
            break
    return datasets


def _ckan_endpoint(source: str, *, api_base_url: str, limit: int) -> tuple[str, str, str]:
    raw = source.split(":", 1)[1].strip() if source.startswith("ckan:") else source.strip()
    if not raw:
        raise ValidationError("ckan source must include a portal domain and search query")

    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        portal = parsed.netloc
        query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
        if "package_search" in parsed.path:
            endpoint_base = parsed._replace(query="").geturl()
            search_query = _ckan_query_param(query_pairs) or _ckan_query_from_path(parsed.path) or raw
        else:
            endpoint_base = _ckan_api_base(portal, api_base_url)
            search_query = _ckan_query_param(query_pairs) or _ckan_query_from_path(parsed.path) or raw
            query_pairs = [(name, value) for name, value in query_pairs if name == "q"]
    else:
        path, query = raw.split("?", 1) if "?" in raw else (raw, "")
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            raise ValidationError("ckan source must be domain/query or a CKAN package_search URL")
        portal = parts[0]
        query_pairs = parse_qsl(query, keep_blank_values=True)
        search_query = _ckan_query_param(query_pairs) or unquote("/".join(parts[1:])).strip()
        endpoint_base = _ckan_api_base(portal, api_base_url)

    if not portal:
        raise ValidationError("ckan source must include a portal domain")
    if not search_query:
        raise ValidationError("ckan source must include a package search query")
    existing = {name for name, _ in query_pairs}
    if "q" not in existing:
        query_pairs.append(("q", search_query))
    if "rows" not in existing:
        query_pairs.append(("rows", str(min(limit, 1000))))
    if "sort" not in existing:
        query_pairs.append(("sort", "metadata_modified desc"))
    separator = "&" if "?" in endpoint_base else "?"
    endpoint = f"{endpoint_base}{separator}{urlencode(query_pairs)}" if query_pairs else endpoint_base
    return portal, search_query, endpoint


def _ckan_api_base(portal: str, api_base_url: str) -> str:
    base = api_base_url.strip()
    if not base:
        raise ValidationError("ckan import --api-base-url cannot be empty")
    if "{domain}" in base:
        return base.format(domain=quote(portal, safe=".:-"))
    if "package_search" in base:
        return base
    return f"{base.rstrip('/')}/api/3/action/package_search"


def _ckan_query_param(query_pairs: list[tuple[str, str]]) -> str | None:
    for name, value in query_pairs:
        if name == "q":
            return value.strip() or None
    return None


def _ckan_query_from_path(path: str) -> str | None:
    parts = [unquote(part) for part in path.strip("/").split("/") if part]
    if not parts:
        return None
    if "package_search" in parts:
        return None
    if "dataset" in parts:
        index = parts.index("dataset")
        if index + 1 < len(parts):
            return parts[index + 1].strip() or None
    return parts[-1].strip() or None


def _ckan_package_results(payload: object) -> list[dict]:
    if isinstance(payload, list):
        raw_rows = payload
    elif isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, dict):
            raw_rows = result.get("results") or result.get("packages")
        else:
            raw_rows = payload.get("results") or payload.get("packages")
    else:
        raw_rows = None
    if not isinstance(raw_rows, list):
        raise ValidationError("ckan response must include a result.results array")
    return [dict(row) for row in raw_rows if isinstance(row, dict)]


def _ckan_organization(value: object) -> str | None:
    if isinstance(value, dict):
        return _optional_str(
            _first_present(value.get("title"), value.get("display_name"), value.get("name"), value.get("id"))
        )
    return _optional_str(value)


def _ckan_names(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    names: list[str] = []
    for item in value:
        if isinstance(item, dict):
            name = _optional_str(
                _first_present(item.get("display_name"), item.get("title"), item.get("name"), item.get("id"))
            )
        else:
            name = _optional_str(item)
        if name and name not in names:
            names.append(name)
    return names


def _ckan_resources(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    resources: list[dict[str, object]] = []
    for item in value[:20]:
        if not isinstance(item, dict):
            continue
        resource = {
            key: item.get(key)
            for key in (
                "id",
                "name",
                "description",
                "url",
                "format",
                "mimetype",
                "created",
                "last_modified",
                "cache_last_updated",
            )
            if item.get(key) not in (None, "")
        }
        if resource:
            resources.append(resource)
    return resources


def _ckan_public_dataset_url(portal: str, package_name: str | None, endpoint: str) -> str | None:
    name = _optional_str(package_name)
    if not portal or not name:
        return None
    parsed = urlparse(endpoint)
    scheme = parsed.scheme or "https"
    return f"{scheme}://{portal}/dataset/{quote(name, safe='')}"


def _ckan_timestamp(value: object) -> str | None:
    return _optional_epoch_or_iso_timestamp(value, field_name="ckan timestamp")
