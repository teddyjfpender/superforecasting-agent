"""Benchmark evidence provenance helpers."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


PROFILE_VERSION = "benchmark-evidence-v1"

KNOWN_EXTERNAL_FAMILIES = {
    "kalshi",
    "manifold",
    "metaculus",
    "polymarket",
}

EXTERNAL_DOMAINS = {
    "kalshi": ("kalshi.com",),
    "manifold": ("manifold.markets",),
    "metaculus": ("metaculus.com",),
    "polymarket": ("polymarket.com",),
}

BUILTIN_DATASET_PROFILES: dict[str, dict[str, Any]] = {
    "mini-binary": {
        "provenance": "fixture",
        "source_families": [],
        "source_types": ["builtin_fixture"],
    },
    "synthetic-100-binary": {
        "provenance": "synthetic",
        "source_families": [],
        "source_types": ["synthetic_fixture"],
    },
    "heldout-120-binary": {
        "provenance": "packaged_heldout",
        "source_families": [],
        "source_types": ["packaged_heldout"],
    },
    "manifold-public-120-binary": {
        "provenance": "public_external",
        "source_families": ["manifold"],
        "source_types": ["adapter:manifold", "public_market"],
    },
    "kalshi-public-120-binary": {
        "provenance": "public_external",
        "source_families": ["kalshi"],
        "source_types": ["adapter:kalshi", "public_market"],
    },
}


def build_benchmark_evidence_profile(
    dataset: str,
    cases: list[dict[str, Any]] | None = None,
    *,
    result_summary: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify whether a backtest run uses external resolved-question evidence."""

    existing = (result_summary or {}).get("benchmark_evidence")
    if isinstance(existing, dict) and existing.get("profile_version") == PROFILE_VERSION:
        return _normalize_existing_profile(existing)

    dataset_key = str(dataset).removeprefix("builtin:")
    builtin_profile = BUILTIN_DATASET_PROFILES.get(dataset_key, {})
    families = set(builtin_profile.get("source_families") or [])
    source_types = set(builtin_profile.get("source_types") or [])
    case_count = len(cases or [])
    public_external_case_count = 0

    if cases:
        for case in cases:
            case_families, case_source_types = _case_external_sources(case)
            if case_families:
                public_external_case_count += 1
            families.update(case_families)
            source_types.update(case_source_types)

    result_case_count = int((result_summary or {}).get("case_count") or 0)
    if not case_count and result_case_count:
        case_count = result_case_count
    if not public_external_case_count and families:
        public_external_case_count = case_count

    provenance = str(builtin_profile.get("provenance") or "")
    if families:
        provenance = "public_external"
    elif dataset_key.startswith("synthetic"):
        provenance = "synthetic"
    elif dataset_key.startswith("mini"):
        provenance = "fixture"
    elif dataset_key.startswith("heldout"):
        provenance = "packaged_heldout"
    elif str(dataset).startswith("imported:"):
        provenance = "imported_local"
    elif str(dataset).startswith(("http://", "https://")):
        provenance = "remote_dataset"
        source_types.add("remote_dataset")
    elif not provenance:
        provenance = "local_dataset"

    synthetic_case_count = case_count if provenance == "synthetic" else 0
    fixture_case_count = case_count if provenance in {"fixture", "local_dataset"} else 0

    return {
        "profile_version": PROFILE_VERSION,
        "provenance": provenance,
        "source_families": sorted(families),
        "source_types": sorted(source_types),
        "case_count": case_count,
        "public_external_case_count": public_external_case_count,
        "synthetic_case_count": synthetic_case_count,
        "fixture_case_count": fixture_case_count,
        "has_public_external_source": bool(families),
        "has_only_generated_or_local_fixture": not bool(families),
    }


def _normalize_existing_profile(profile: dict[str, Any]) -> dict[str, Any]:
    families = sorted(str(item) for item in profile.get("source_families") or [])
    source_types = sorted(str(item) for item in profile.get("source_types") or [])
    public_count = int(profile.get("public_external_case_count") or 0)
    return {
        "profile_version": PROFILE_VERSION,
        "provenance": str(profile.get("provenance") or "unknown"),
        "source_families": families,
        "source_types": source_types,
        "case_count": int(profile.get("case_count") or 0),
        "public_external_case_count": public_count,
        "synthetic_case_count": int(profile.get("synthetic_case_count") or 0),
        "fixture_case_count": int(profile.get("fixture_case_count") or 0),
        "has_public_external_source": bool(profile.get("has_public_external_source")) or bool(families),
        "has_only_generated_or_local_fixture": not (bool(profile.get("has_public_external_source")) or bool(families)),
    }


def _case_external_sources(case: dict[str, Any]) -> tuple[set[str], set[str]]:
    families: set[str] = set()
    source_types: set[str] = set()

    for evidence in case.get("evidence") or []:
        if not isinstance(evidence, dict):
            continue
        _collect_family_from_source_type(evidence.get("source_type"), families, source_types)
        _collect_family_from_text(evidence.get("source_name"), families)
        _collect_family_from_url(evidence.get("source") or evidence.get("url"), families, source_types)

    for baseline in case.get("baselines") or []:
        if not isinstance(baseline, dict):
            continue
        source = str(baseline.get("source") or "").lower()
        if source in KNOWN_EXTERNAL_FAMILIES:
            families.add(source)
            source_types.add(f"baseline:{source}")
        _collect_family_from_source_type(baseline.get("source_type"), families, source_types)
        _collect_family_from_url(baseline.get("url"), families, source_types)

    metadata = case.get("metadata") if isinstance(case.get("metadata"), dict) else {}
    for value in (
        metadata.get("source_dataset"),
        metadata.get("adapter"),
        metadata.get("source"),
        case.get("resolution_source"),
        case.get("source"),
        case.get("url"),
    ):
        _collect_family_from_text(value, families)
        _collect_family_from_url(value, families, source_types)

    return families, source_types


def _collect_family_from_source_type(
    value: Any,
    families: set[str],
    source_types: set[str],
) -> None:
    if not isinstance(value, str):
        return
    source_type = value.strip().lower()
    if not source_type:
        return
    source_types.add(source_type)
    if source_type.startswith("adapter:"):
        family = source_type.split(":", 1)[1].split(".", 1)[0]
        if family in KNOWN_EXTERNAL_FAMILIES:
            families.add(family)


def _collect_family_from_text(value: Any, families: set[str]) -> None:
    if not isinstance(value, str):
        return
    lowered = value.lower()
    for family in KNOWN_EXTERNAL_FAMILIES:
        if family in lowered:
            families.add(family)


def _collect_family_from_url(
    value: Any,
    families: set[str],
    source_types: set[str],
) -> None:
    if not isinstance(value, str) or "://" not in value:
        return
    host = urlparse(value).netloc.lower()
    for family, domains in EXTERNAL_DOMAINS.items():
        if any(host == domain or host.endswith(f".{domain}") for domain in domains):
            families.add(family)
            source_types.add(f"url:{family}")
