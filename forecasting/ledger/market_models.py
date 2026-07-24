"""Market-model + ingest-candidate domain (carved from core).

Carved verbatim out of :mod:`forecasting.ledger.core` behind the unchanged
``ForecastLedger`` façade. This leaf owns two authoring/intake table families:

* MARKET MODELS: the model CRUD (``create_market_model`` / ``update_market_model_spec``
  / ``get_`` / ``list_`` / ``delete_``), the presentation/message/data-series children
  (``add_market_presentation`` / ``get_`` / ``list_``; ``add_market_message`` /
  ``list_``; ``add_market_data_series`` / ``list_`` / ``replace_``), the export
  (``export_market_model``) and the row serializers (``_market_model_to_dict`` /
  ``_market_presentation_to_dict`` / ``_market_message_to_dict`` / ``_market_series_to_dict``);
* INGEST CANDIDATES: the candidate CRUD (``create_ingest_candidate`` / ``get_`` /
  ``list_`` / ``confirm_ingest_candidate`` / ``_row_to_ingest_candidate``) and the
  source-metadata extraction pipeline (``_infer_ingest_source_type`` /
  ``_extract_ingest_metadata`` / ``_extract_url_ingest_metadata`` /
  ``_metadata_from_ingest_payload`` / ``_metadata_from_text_source`` /
  ``_metadata_from_html_source`` / the baseline coercers /
  ``_candidate_title_from_source``).

Each function takes the ``ForecastLedger`` instance first; ``core`` keeps a
one-line delegate per method so no caller changed. The URL fetch reaches the
module-level ``urlopen`` (which tests monkeypatch on ``forecasting.ledger``) and
the core-owned ``_IngestHTMLParser`` via the ``_core.`` call-time hop so patches
land; ``_component_market_model_id`` (a classmethod) stays in core."""

from __future__ import annotations

from forecasting.ledger import core as _core
from typing import Any
from forecasting.models import ForecastQuestion
from forecasting.models import LedgerNotFoundError
from forecasting.models import OutcomeSpace
from pathlib import Path
from urllib.request import Request
from urllib.error import URLError
from forecasting.models import ValidationError
import csv
import json
from forecasting.models import json_dumps
from forecasting.models import json_loads
from forecasting.models import parse_timestamp
import sqlite3
from urllib.parse import urlparse
from forecasting.models import utc_now_iso
import uuid


def create_market_model(
    ledger,
    *,
    title: str,
    question: str,
    depth: str = "standard",
    spec: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    agent_model: str | None = None,
    prompt_version: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not (title or "").strip():
        raise ValidationError("market model title is required")
    if not (question or "").strip():
        raise ValidationError("market model question is required")
    now = utc_now_iso()
    model_id = f"mm_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO market_models (
                id, created_at, updated_at, title, question, depth, spec,
                status, current_version, tags, agent_model, prompt_version, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', 0, ?, ?, ?, ?)
            """,
            (
                model_id, now, now, title.strip(), question.strip(), depth,
                json_dumps(dict(spec or {})), json_dumps(list(tags or [])),
                agent_model, prompt_version, json_dumps(dict(metadata or {})),
            ),
        )
    return ledger.get_market_model(model_id)


def update_market_model_spec(ledger, model_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    with ledger._connect() as conn:
        cur = conn.execute(
            "UPDATE market_models SET spec = ?, updated_at = ? WHERE id = ?",
            (json_dumps(dict(spec or {})), utc_now_iso(), model_id),
        )
        if cur.rowcount == 0:
            raise LedgerNotFoundError(f"market model not found: {model_id}")
    return ledger.get_market_model(model_id)


def get_market_model(ledger, model_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM market_models WHERE id = ?", (model_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"market model not found: {model_id}")
    return ledger._market_model_to_dict(row)


def list_market_models(ledger, *, status: str | None = "active", limit: int | None = None) -> list[dict[str, Any]]:
    # Join the latest presentation's build status (complete/partial/failed) so
    # the list can show a failure/ready icon without an N+1 per-row fetch.
    sql = (
        "SELECT mm.*, ("
        " SELECT p.status FROM market_model_presentations p"
        " WHERE p.model_id = mm.id ORDER BY p.version DESC LIMIT 1"
        ") AS last_status FROM market_models mm"
    )
    params: list[Any] = []
    if status is not None:
        sql += " WHERE mm.status = ?"
        params.append(status)
    sql += " ORDER BY updated_at DESC, rowid DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with ledger._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [ledger._market_model_to_dict(r) for r in rows]


def delete_market_model(ledger, model_id: str) -> bool:
    with ledger._connect() as conn:
        cur = conn.execute("DELETE FROM market_models WHERE id = ?", (model_id,))
    return cur.rowcount > 0


def add_market_presentation(
    ledger,
    *,
    model_id: str,
    presentation: dict[str, Any],
    status: str = "complete",
    summary: str = "",
    as_of_analysis: str | None = None,
    as_of_data: str | None = None,
    refine_instruction: str | None = None,
    diagnostics: dict[str, Any] | None = None,
    agent_model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """Append a new presentation version and advance the model's current_version."""
    ledger.get_market_model(model_id)
    now = utc_now_iso()
    pres_id = f"mmp_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(version), 0) AS v FROM market_model_presentations WHERE model_id = ?",
            (model_id,),
        ).fetchone()
        version = int(row["v"]) + 1
        pres = dict(presentation or {})
        pres["version"] = version
        pres["model_id"] = model_id
        conn.execute(
            """
            INSERT INTO market_model_presentations (
                id, model_id, version, created_at, as_of_analysis, as_of_data,
                schema_version, status, summary, presentation, refine_instruction,
                diagnostics, agent_model, prompt_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                pres_id, model_id, version, now, as_of_analysis or now, as_of_data or now,
                str(pres.get("schema_version") or ""), status, summary,
                json_dumps(pres), refine_instruction, json_dumps(dict(diagnostics or {})),
                agent_model, prompt_version,
            ),
        )
        conn.execute(
            "UPDATE market_models SET current_version = ?, updated_at = ? WHERE id = ?",
            (version, now, model_id),
        )
    return ledger.get_market_presentation(model_id, version=version)


def get_market_presentation(ledger, model_id: str, *, version: int | None = None) -> dict[str, Any]:
    with ledger._connect() as conn:
        if version is None:
            row = conn.execute(
                "SELECT * FROM market_model_presentations WHERE model_id = ? ORDER BY version DESC LIMIT 1",
                (model_id,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM market_model_presentations WHERE model_id = ? AND version = ?",
                (model_id, int(version)),
            ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"no presentation for market model {model_id} (version={version})")
    return ledger._market_presentation_to_dict(row)


def list_market_presentations(ledger, model_id: str) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM market_model_presentations WHERE model_id = ? ORDER BY version ASC",
            (model_id,),
        ).fetchall()
    return [ledger._market_presentation_to_dict(r) for r in rows]


def add_market_message(
    ledger, *, model_id: str, role: str, content: str, version_ref: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger.get_market_model(model_id)
    now = utc_now_iso()
    msg_id = f"mmsg_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO market_model_messages (id, model_id, role, created_at, content, version_ref, metadata)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (msg_id, model_id, role, now, content, version_ref, json_dumps(dict(metadata or {}))),
        )
    with ledger._connect() as conn:
        r = conn.execute("SELECT * FROM market_model_messages WHERE id = ?", (msg_id,)).fetchone()
    return ledger._market_message_to_dict(r)


def list_market_messages(ledger, model_id: str, *, limit: int | None = None) -> list[dict[str, Any]]:
    sql = "SELECT * FROM market_model_messages WHERE model_id = ? ORDER BY created_at ASC, rowid ASC"
    params: list[Any] = [model_id]
    if limit is not None:
        sql += " LIMIT ?"
        params.append(int(limit))
    with ledger._connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [ledger._market_message_to_dict(r) for r in rows]


def add_market_data_series(
    ledger, *, model_id: str, name: str, points: list[Any], source_type: str | None = None,
    source: str | None = None, unit: str | None = None, as_of: str | None = None,
    evidence_refs: list[str] | None = None, metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger.get_market_model(model_id)
    now = utc_now_iso()
    series_id = f"mds_{uuid.uuid4().hex[:12]}"
    with ledger._connect() as conn:
        conn.execute(
            """INSERT INTO market_data_series (
                id, model_id, created_at, name, source_type, source, unit, points,
                as_of, evidence_refs, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                series_id, model_id, now, name, source_type, source, unit,
                json_dumps(list(points or [])), as_of or now,
                json_dumps(list(evidence_refs or [])), json_dumps(dict(metadata or {})),
            ),
        )
    with ledger._connect() as conn:
        r = conn.execute("SELECT * FROM market_data_series WHERE id = ?", (series_id,)).fetchone()
    return ledger._market_series_to_dict(r)


def list_market_data_series(ledger, model_id: str) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM market_data_series WHERE model_id = ? ORDER BY created_at ASC, rowid ASC",
            (model_id,),
        ).fetchall()
    return [ledger._market_series_to_dict(r) for r in rows]


def replace_market_data_series(ledger, model_id: str, series: list[dict[str, Any]]) -> None:
    """Replace all stored series for a model (used by re-pull on open)."""
    ledger.get_market_model(model_id)
    now = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute("DELETE FROM market_data_series WHERE model_id = ?", (model_id,))
        for s in series or []:
            conn.execute(
                """INSERT INTO market_data_series (
                    id, model_id, created_at, name, source_type, source, unit, points,
                    as_of, evidence_refs, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    f"mds_{uuid.uuid4().hex[:12]}", model_id, now, str(s.get("name") or ""),
                    s.get("source_type"), s.get("source"), s.get("unit"),
                    json_dumps(list(s.get("points") or [])), s.get("as_of") or now,
                    json_dumps(list(s.get("evidence_refs") or [])), json_dumps(dict(s.get("metadata") or {})),
                ),
            )


def export_market_model(ledger, model_id: str, *, fmt: str = "json") -> dict[str, Any]:
    """Full packet: model + current presentation + all versions + series + thread."""
    model = ledger.get_market_model(model_id)
    try:
        current = ledger.get_market_presentation(model_id)
    except LedgerNotFoundError:
        current = None
    return {
        "product": "market-models",
        "generated_at": utc_now_iso(),
        "model": model,
        "presentation": current,
        "versions": ledger.list_market_presentations(model_id),
        "series": ledger.list_market_data_series(model_id),
        "messages": ledger.list_market_messages(model_id),
    }


def _market_model_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["spec"] = json_loads(d.get("spec"), {})
    d["tags"] = json_loads(d.get("tags"), [])
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def _market_presentation_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["presentation"] = json_loads(d.get("presentation"), {})
    d["diagnostics"] = json_loads(d.get("diagnostics"), {})
    return d


def _market_message_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def _market_series_to_dict(ledger, row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    d["points"] = json_loads(d.get("points"), [])
    d["evidence_refs"] = json_loads(d.get("evidence_refs"), [])
    d["metadata"] = json_loads(d.get("metadata"), {})
    return d


def create_ingest_candidate(
    ledger,
    *,
    source: str,
    title: str | None = None,
    description: str = "",
    resolution_criteria: str = "",
    resolution_source: str | None = None,
    outcome_space: OutcomeSpace | None = None,
    close_time: str | None = None,
    resolution_time: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    source = source.strip()
    if not source:
        raise ValidationError("ingest source is required")
    candidate_id = f"ic_{uuid.uuid4().hex[:12]}"
    source_type = ledger._infer_ingest_source_type(source)
    extracted = ledger._extract_ingest_metadata(source, source_type)
    candidate_title = (
        title
        or extracted.get("title")
        or ledger._candidate_title_from_source(source, source_type)
    ).strip()
    candidate_description = description or str(extracted.get("description") or "")
    candidate_resolution_criteria = resolution_criteria or str(extracted.get("resolution_criteria") or "")
    candidate_resolution_source = resolution_source or extracted.get("resolution_source")
    candidate_close_time = close_time or extracted.get("close_time")
    candidate_resolution_time = resolution_time or extracted.get("resolution_time")
    extracted_outcome = extracted.get("outcome_space")
    outcome = outcome_space or (
        OutcomeSpace.from_dict(extracted_outcome) if isinstance(extracted_outcome, dict) else OutcomeSpace()
    )
    candidate_metadata = dict(extracted.get("metadata") or {})
    candidate_metadata.update(metadata or {})
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO ingest_candidates (
                id, source, source_type, created_at, candidate_title,
                description, resolution_criteria, resolution_source,
                close_time, resolution_time, outcome_space, metadata
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                candidate_id,
                source,
                source_type,
                utc_now_iso(),
                candidate_title,
                candidate_description,
                candidate_resolution_criteria,
                candidate_resolution_source,
                parse_timestamp(candidate_close_time, field_name="close_time"),
                parse_timestamp(candidate_resolution_time, field_name="resolution_time"),
                outcome.to_json(),
                json_dumps(candidate_metadata),
            ),
        )
    return ledger.get_ingest_candidate(candidate_id)


def get_ingest_candidate(ledger, candidate_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM ingest_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"ingest candidate not found: {candidate_id}")
    return ledger._row_to_ingest_candidate(row)


def list_ingest_candidates(ledger, *, status: str | None = None) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM ingest_candidates {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [ledger._row_to_ingest_candidate(row) for row in rows]


def confirm_ingest_candidate(
    ledger,
    candidate_id: str,
    *,
    title: str | None = None,
    resolution_criteria: str | None = None,
    domain: str | None = None,
    tags: list[str] | None = None,
    topics: list[str] | None = None,
) -> ForecastQuestion:
    candidate = ledger.get_ingest_candidate(candidate_id)
    if candidate["status"] != "proposed":
        raise ValidationError("only proposed ingest candidates can be confirmed")
    final_title = title or candidate["candidate_title"]
    final_criteria = resolution_criteria if resolution_criteria is not None else candidate["resolution_criteria"]
    if not final_criteria.strip():
        raise ValidationError("confirmation requires resolution criteria")
    outcome_space = OutcomeSpace.from_dict(candidate["outcome_space"])
    baseline_payloads = ledger._candidate_baseline_payloads(candidate["metadata"])
    for baseline in baseline_payloads:
        ledger._validate_probability_payload(ledger._baseline_probability_value(baseline), outcome_space)
    question = ledger.create_question(
        title=final_title,
        description=candidate["description"],
        resolution_criteria=final_criteria,
        resolution_source=candidate["resolution_source"],
        outcome_space=outcome_space,
        close_time=candidate["close_time"],
        resolution_time=candidate["resolution_time"],
        tags=tags or ["ingested"],
        domain=domain,
        topics=topics or [],
        metadata={"ingest_candidate_id": candidate_id, "ingest_source": candidate["source"]},
    )
    ledger.add_evidence(
        question_id=question.id,
        source_or_note=candidate["source"],
        claim="Original ingest source for forecast question.",
        source_type=candidate["source_type"],
        metadata={"ingest_candidate_id": candidate_id},
    )
    for baseline in baseline_payloads:
        ledger.add_baseline_comparison(
            question_id=question.id,
            source=str(baseline.get("source") or candidate["source_type"]),
            baseline_type=str(baseline.get("baseline_type") or "imported"),
            probability_or_distribution=ledger._baseline_probability_value(baseline),
            as_of=baseline.get("as_of"),
            metadata={"ingest_candidate_id": candidate_id, "ingest_source": candidate["source"]},
        )
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE ingest_candidates
            SET status = 'confirmed', confirmed_question_id = ?
            WHERE id = ?
            """,
            (question.id, candidate_id),
        )
    return question


def _row_to_ingest_candidate(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["outcome_space"] = json_loads(data["outcome_space"], {})
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def _infer_ingest_source_type(ledger, source: str) -> str:
    if source.startswith(("http://", "https://")):
        return "url"
    if Path(source).expanduser().is_file():
        return "file"
    return "manual_note"


def _extract_ingest_metadata(ledger, source: str, source_type: str) -> dict[str, Any]:
    if source_type == "url":
        return ledger._extract_url_ingest_metadata(source)
    if source_type != "file":
        return {}
    path = Path(source).expanduser()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValidationError(f"could not read ingest file: {path}") from exc
    suffix = path.suffix.lower()
    if suffix == ".json":
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValidationError(f"ingest file is not valid JSON: {path}") from exc
        if not isinstance(payload, dict):
            raise ValidationError("ingest JSON file must contain an object")
        return ledger._metadata_from_ingest_payload(payload)
    if suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        if not rows:
            raise ValidationError("ingest CSV file must contain at least one row")
        return ledger._metadata_from_ingest_payload(rows[0])
    return ledger._metadata_from_text_source(text)


def _extract_url_ingest_metadata(ledger, source: str) -> dict[str, Any]:
    parsed = urlparse(source)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or any(ord(char) < 33 for char in source)
        or source.count("http://") + source.count("https://") != 1
    ):
        raise ValidationError(
            "ingest source must be one absolute HTTP(S) URL with no spaces or control characters"
        )
    request = Request(source, headers={"User-Agent": "superforecasting-agent/0.1"})
    try:
        with _core.urlopen(request, timeout=8) as response:
            content_type = response.headers.get("content-type", "")
            raw = response.read(512 * 1024)
    except (OSError, URLError, ValueError) as exc:
        return {"metadata": {"source_fetch_error": str(exc)}}
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("utf-8", errors="replace")
    if "json" in content_type.lower() or urlparse(source).path.lower().endswith(".json"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return {"metadata": {"source_fetch_error": f"invalid JSON response: {exc}"}}
        if isinstance(payload, dict):
            return ledger._metadata_from_ingest_payload(payload)
        return {"metadata": {"source_fetch_error": "JSON response was not an object"}}
    html_metadata = ledger._metadata_from_html_source(text)
    html_metadata.setdefault("metadata", {})
    html_metadata["metadata"]["source_content_type"] = content_type
    return html_metadata


def _metadata_from_ingest_payload(ledger, payload: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    baselines: list[dict[str, Any]] = []
    raw_baselines = payload.get("baselines")
    if isinstance(raw_baselines, list):
        baselines.extend(ledger._normalize_ingest_baseline(item) for item in raw_baselines if isinstance(item, dict))
    baseline = payload.get("baseline")
    if isinstance(baseline, dict):
        baselines.append(ledger._normalize_ingest_baseline(baseline))
    explicit_probability_fields = (
        ("baseline_probability", payload.get("baseline_type") or "imported", "baseline"),
        ("crowd_probability", "crowd", "crowd"),
        ("market_probability", "market", "market"),
        ("prior_probability", "prior", "prior"),
        ("posterior_probability", "posterior", "posterior"),
        ("forecast_probability", "imported_forecast", "forecast"),
    )
    for field, baseline_type, prefix in explicit_probability_fields:
        if payload.get(field) is None:
            continue
        baselines.append(
            {
                "source": (
                    payload.get(f"{prefix}_source")
                    or payload.get("baseline_source")
                    or payload.get("source_name")
                    or payload.get("platform")
                    or "ingest_file"
                ),
                "baseline_type": baseline_type,
                "probability_or_distribution": ledger._coerce_ingest_probability(payload[field]),
                "as_of": payload.get(f"{prefix}_as_of") or payload.get("baseline_as_of") or payload.get("as_of"),
            }
        )
    if not baselines and payload.get("probability") is not None:
        baselines.append(
            {
                "source": payload.get("baseline_source") or payload.get("source_name") or "ingest_file",
                "baseline_type": payload.get("baseline_type") or "imported",
                "probability_or_distribution": ledger._coerce_ingest_probability(payload["probability"]),
                "as_of": payload.get("baseline_as_of") or payload.get("as_of"),
            }
        )
    baselines = ledger._dedupe_ingest_baselines(baselines)
    if baselines:
        metadata["baselines"] = baselines
        metadata["baseline"] = baselines[0]
    result = {
        "title": payload.get("title") or payload.get("question") or payload.get("question_title"),
        "description": payload.get("description") or payload.get("body") or "",
        "resolution_criteria": payload.get("resolution_criteria") or payload.get("criteria") or "",
        "resolution_source": payload.get("resolution_source"),
        "close_time": payload.get("close_time") or payload.get("close_date"),
        "resolution_time": payload.get("resolution_time") or payload.get("resolution_date"),
        "outcome_space": payload.get("outcome_space"),
        "metadata": metadata,
    }
    return {key: value for key, value in result.items() if value not in (None, "")}


def _coerce_ingest_probability(ledger, value: Any) -> Any:
    if isinstance(value, str):
        raw = value.strip()
        if raw == "":
            return value
        if raw.endswith("%"):
            try:
                return float(raw[:-1].strip()) / 100.0
            except ValueError:
                return value
        try:
            return float(raw)
        except ValueError:
            return value
    return value


def _dedupe_ingest_baselines(ledger, baselines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for baseline in baselines:
        if "probability_or_distribution" not in baseline and "probability" not in baseline:
            continue
        key = json_dumps(
            {
                "source": baseline.get("source"),
                "baseline_type": baseline.get("baseline_type"),
                "as_of": baseline.get("as_of"),
                "probability": ledger._baseline_probability_value(baseline),
            }
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(dict(baseline))
    return deduped


def _candidate_baseline_payloads(ledger, metadata: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict):
        return []
    baselines: list[dict[str, Any]] = []
    raw_baselines = metadata.get("baselines")
    if isinstance(raw_baselines, list):
        baselines.extend(ledger._normalize_ingest_baseline(item) for item in raw_baselines if isinstance(item, dict))
    baseline = metadata.get("baseline")
    if isinstance(baseline, dict):
        baselines.append(ledger._normalize_ingest_baseline(baseline))
    return ledger._dedupe_ingest_baselines(baselines)


def _baseline_probability_value(ledger, baseline: dict[str, Any]) -> Any:
    return baseline.get("probability_or_distribution", baseline.get("probability"))


def _normalize_ingest_baseline(ledger, baseline: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(baseline)
    if "probability_or_distribution" in normalized:
        normalized["probability_or_distribution"] = ledger._coerce_ingest_probability(
            normalized["probability_or_distribution"]
        )
    if "probability" in normalized:
        normalized["probability"] = ledger._coerce_ingest_probability(normalized["probability"])
    return normalized


def _metadata_from_text_source(ledger, text: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    description_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if line.startswith("#") and "title" not in result:
            result["title"] = line.lstrip("#").strip()
            continue
        for label, field in (
            ("title:", "title"),
            ("question:", "title"),
            ("resolution criteria:", "resolution_criteria"),
            ("criteria:", "resolution_criteria"),
            ("resolution source:", "resolution_source"),
            ("close time:", "close_time"),
            ("close date:", "close_time"),
            ("resolution time:", "resolution_time"),
            ("resolution date:", "resolution_time"),
        ):
            if lowered.startswith(label):
                result[field] = line[len(label):].strip()
                break
        else:
            if len(description_lines) < 3:
                description_lines.append(line)
    if "description" not in result and description_lines:
        result["description"] = "\n".join(description_lines)
    return result


def _metadata_from_html_source(ledger, text: str) -> dict[str, Any]:
    parser = _core._IngestHTMLParser()
    try:
        parser.feed(text)
    except Exception:
        return ledger._metadata_from_text_source(text)
    result = ledger._metadata_from_text_source("\n".join(parser.text_lines))
    if parser.title and "title" not in result:
        result["title"] = parser.title.strip()
    description = parser.meta.get("description") or parser.meta.get("og:description")
    if description and not result.get("description"):
        result["description"] = description.strip()
    og_title = parser.meta.get("og:title")
    if og_title and not result.get("title"):
        result["title"] = og_title.strip()
    return result


def _candidate_title_from_source(ledger, source: str, source_type: str) -> str:
    if source_type == "url":
        parsed = urlparse(source)
        path = parsed.path.strip("/").split("/")[-1]
        label = path.replace("-", " ").replace("_", " ").strip()
        return label or parsed.netloc or "Ingested forecast candidate"
    if source_type == "file":
        return Path(source).expanduser().stem.replace("-", " ").replace("_", " ") or "Ingested forecast candidate"
    return source[:80] or "Ingested forecast candidate"
