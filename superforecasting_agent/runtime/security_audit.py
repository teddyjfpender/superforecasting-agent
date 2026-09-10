"""On-demand supply-chain audit for Superforecasting Agent installs.

Scans three surfaces an operator controls and we can map to
upstream advisories without auth or extra binaries:

1. The active Python environment (every PyPI dist via ``importlib.metadata``).
2. Python deps declared by user-installed plugins under ``~/.superforecasting-agent/plugins``
   (``requirements.txt`` + ``pyproject.toml`` best-effort pin extraction).
3. MCP servers wired in ``config.yaml`` whose ``command/args`` look like
   ``npx -y <pkg>@<ver>`` or ``uvx <pkg>==<ver>``.

Vulnerabilities are looked up against OSV.dev (``api.osv.dev/v1/querybatch``
+ ``/v1/vulns/{id}``). Single-shot and on-demand; it does not schedule background scans.

Out of scope on purpose: global pip/npm, editor/browser extensions,
daily background scans, auto-blocking installs.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Iterable, Optional

from superforecasting_agent.constants import get_agent_home

OSV_BATCH_URL = "https://api.osv.dev/v1/querybatch"
OSV_VULN_URL = "https://api.osv.dev/v1/vulns/{vid}"
OSV_BATCH_MAX = 1000  # OSV documented hard cap per request
HTTP_TIMEOUT = 20
DETAIL_PARALLELISM = 8

# Severity ordering for --fail-on gating. UNKNOWN sits below LOW so it
# never blocks unless --fail-on is passed something even lower (we don't
# expose that).
SEVERITY_ORDER = {
    "UNKNOWN": 0,
    "LOW": 1,
    "MODERATE": 2,
    "MEDIUM": 2,
    "HIGH": 3,
    "CRITICAL": 4,
}


# ─── Data shapes ──────────────────────────────────────────────────────────────


from .audit_types import Component as Component, Vulnerability as Vulnerability, Finding as Finding


# ─── Component discovery ──────────────────────────────────────────────────────


from .audit_discovery import (
    _REQ_LINE as _REQ_LINE,
    _NPX_PKG as _NPX_PKG,
    _UVX_PKG as _UVX_PKG,
    _discover_venv as _discover_venv,
    _parse_requirements as _parse_requirements,
    _parse_pyproject_pins as _parse_pyproject_pins,
    _discover_plugins as _discover_plugins,
    _extract_mcp_component as _extract_mcp_component,
    _discover_mcp as _discover_mcp,
)


# ─── OSV client ───────────────────────────────────────────────────────────────


def _http_post_json(url: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_get_json(url: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _osv_query_batch(components: list[Component]) -> dict[Component, list[str]]:
    """Return {component -> [osv_id, ...]} for components with any vulns.

    Components without findings are omitted from the result dict.
    """
    if not components:
        return {}
    findings: dict[Component, list[str]] = {}
    for chunk_start in range(0, len(components), OSV_BATCH_MAX):
        chunk = components[chunk_start:chunk_start + OSV_BATCH_MAX]
        payload = {
            "queries": [
                {
                    "package": {"name": c.name, "ecosystem": c.ecosystem},
                    "version": c.version,
                }
                for c in chunk
            ]
        }
        try:
            resp = _http_post_json(OSV_BATCH_URL, payload)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise RuntimeError(f"OSV batch query failed: {exc}") from exc
        results = resp.get("results") or []
        for comp, result in zip(chunk, results):
            vulns = (result or {}).get("vulns") or []
            ids = [v.get("id") for v in vulns if v.get("id")]
            if ids:
                findings[comp] = ids
    return findings


def _osv_severity_from_record(record: dict) -> str:
    """Extract CVSS-derived severity tier from an OSV vuln record."""
    # OSV puts CVSS in `severity` (top-level or per-affected) and a
    # human-readable bucket in `database_specific.severity` for GHSAs.
    db_specific = record.get("database_specific") or {}
    raw = db_specific.get("severity")
    if isinstance(raw, str) and raw.strip():
        upper = raw.strip().upper()
        if upper in SEVERITY_ORDER:
            return upper
    # Fall back to CVSS score → tier
    score: Optional[float] = None
    for sev_entry in record.get("severity") or []:
        s = sev_entry.get("score")
        if isinstance(s, str):
            # CVSS vector strings look like "CVSS:3.1/AV:N/..." — we can't
            # parse without a lib. Look for an explicit numeric in
            # affected[].ecosystem_specific later if present.
            continue
    affected = record.get("affected") or []
    for entry in affected:
        eco_spec = entry.get("ecosystem_specific") or {}
        sev = eco_spec.get("severity")
        if isinstance(sev, str) and sev.strip().upper() in SEVERITY_ORDER:
            return sev.strip().upper()
    if score is not None:
        if score >= 9.0:
            return "CRITICAL"
        if score >= 7.0:
            return "HIGH"
        if score >= 4.0:
            return "MODERATE"
        if score > 0:
            return "LOW"
    return "UNKNOWN"


def _osv_fixed_versions(record: dict) -> list[str]:
    fixes: list[str] = []
    for entry in record.get("affected") or []:
        for rng in entry.get("ranges") or []:
            for event in rng.get("events") or []:
                if "fixed" in event:
                    fixes.append(str(event["fixed"]))
    # Dedupe, preserve order
    seen: set[str] = set()
    out: list[str] = []
    for f in fixes:
        if f not in seen:
            seen.add(f)
            out.append(f)
    return out


def _osv_fetch_details(vuln_ids: Iterable[str]) -> dict[str, Vulnerability]:
    """Fetch summary/severity for each unique vuln id, in parallel."""
    unique = sorted({vid for vid in vuln_ids if vid})
    if not unique:
        return {}
    out: dict[str, Vulnerability] = {}

    def _fetch_one(vid: str) -> Vulnerability:
        try:
            rec = _http_get_json(OSV_VULN_URL.format(vid=vid))
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            return Vulnerability(osv_id=vid)
        return Vulnerability(
            osv_id=vid,
            severity=_osv_severity_from_record(rec),
            summary=(rec.get("summary") or "").strip(),
            fixed_versions=_osv_fixed_versions(rec),
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=DETAIL_PARALLELISM) as pool:
        for vuln in pool.map(_fetch_one, unique):
            out[vuln.osv_id] = vuln
    return out


# ─── Orchestration ────────────────────────────────────────────────────────────


def run_audit(
    *,
    skip_venv: bool = False,
    skip_plugins: bool = False,
    skip_mcp: bool = False,
    hermes_home: Optional[Path] = None,
) -> list[Finding]:
    """Discover components, query OSV, return findings sorted by severity desc."""
    components = _discover_components(
        skip_venv=skip_venv, skip_plugins=skip_plugins, skip_mcp=skip_mcp,
        hermes_home=hermes_home,
    )
    return _audit_components(components)


def _discover_components(
    *, skip_venv: bool, skip_plugins: bool, skip_mcp: bool,
    hermes_home: Optional[Path] = None,
) -> list[Component]:
    home = hermes_home or Path(get_agent_home())
    components: list[Component] = []
    if not skip_venv:
        components.extend(_discover_venv())
    if not skip_plugins:
        components.extend(_discover_plugins(home))
    if not skip_mcp:
        components.extend(_discover_mcp())

    return components


def _audit_components(components: list[Component]) -> list[Finding]:
    if not components:
        return []

    raw = _osv_query_batch(components)
    if not raw:
        return []

    all_ids: list[str] = []
    for ids in raw.values():
        all_ids.extend(ids)
    details = _osv_fetch_details(all_ids)

    findings: list[Finding] = []
    for comp, ids in raw.items():
        for vid in ids:
            vuln = details.get(vid) or Vulnerability(osv_id=vid)
            findings.append(Finding(component=comp, vuln=vuln))

    findings.sort(
        key=lambda f: (
            -SEVERITY_ORDER.get(f.vuln.severity, 0),
            f.component.source,
            f.component.name.lower(),
            f.vuln.osv_id,
        )
    )
    return findings


# ─── Rendering ────────────────────────────────────────────────────────────────


def _render_human(findings: list[Finding], total_components: int) -> str:
    if not findings:
        return f"No known vulnerabilities found across {total_components} component(s)."

    lines: list[str] = []
    lines.append(
        f"Found {len(findings)} known vulnerability finding(s) "
        f"across {total_components} component(s):"
    )
    lines.append("")
    last_source = None
    for f in findings:
        if f.component.source != last_source:
            lines.append(f"[{f.component.source}]")
            last_source = f.component.source
        sev = f.vuln.severity.ljust(8)
        head = f"  {sev}  {f.component.name}=={f.component.version}  {f.vuln.osv_id}"
        lines.append(head)
        if f.vuln.summary:
            summary = f.vuln.summary
            if len(summary) > 100:
                summary = summary[:97] + "..."
            lines.append(f"           {summary}")
        if f.vuln.fixed_versions:
            lines.append(f"           fixed in: {', '.join(f.vuln.fixed_versions[:3])}")
    return "\n".join(lines)


def _render_json(findings: list[Finding], total_components: int) -> str:
    payload = {
        "total_components_scanned": total_components,
        "finding_count": len(findings),
        "findings": [
            {
                "package": f.component.name,
                "version": f.component.version,
                "ecosystem": f.component.ecosystem,
                "source": f.component.source,
                "vuln_id": f.vuln.osv_id,
                "severity": f.vuln.severity,
                "summary": f.vuln.summary,
                "fixed_versions": f.vuln.fixed_versions,
            }
            for f in findings
        ],
    }
    return json.dumps(payload, indent=2)





# ─── CLI entrypoint ───────────────────────────────────────────────────────────


def cmd_security_audit(args: argparse.Namespace) -> int:
    """Implementation of `superforecasting-agent security audit`."""
    home = Path(get_agent_home())
    skip_venv = bool(getattr(args, "skip_venv", False))
    skip_plugins = bool(getattr(args, "skip_plugins", False))
    skip_mcp = bool(getattr(args, "skip_mcp", False))
    output_json = bool(getattr(args, "json", False))
    fail_on = (getattr(args, "fail_on", None) or "critical").upper()
    if fail_on not in SEVERITY_ORDER:
        print(
            f"unknown --fail-on value: {fail_on.lower()} "
            f"(choose from: low, moderate, high, critical)",
            file=sys.stderr,
        )
        return 2

    components = _discover_components(
        skip_venv=skip_venv, skip_plugins=skip_plugins, skip_mcp=skip_mcp, hermes_home=home
    )
    total = len(components)
    if total == 0:
        msg = "No components discovered (everything skipped, or empty environment)."
        if output_json:
            print(json.dumps({"total_components_scanned": 0, "finding_count": 0, "findings": []}))
        else:
            print(msg)
        return 0

    try:
        findings = _audit_components(components)
    except RuntimeError as exc:
        print(f"audit failed: {exc}", file=sys.stderr)
        return 2

    if output_json:
        print(_render_json(findings, total))
    else:
        print(_render_human(findings, total))

    # Exit code: 1 iff any finding meets or exceeds the --fail-on threshold.
    threshold = SEVERITY_ORDER[fail_on]
    for f in findings:
        if SEVERITY_ORDER.get(f.vuln.severity, 0) >= threshold:
            return 1
    return 0
