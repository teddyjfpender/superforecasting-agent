"""Watched-source domain (D1 carve — the pattern-prover for Arc D).

Carved verbatim out of ``forecasting/ledger/core.py``: the watched-source
lifecycle (add / get / list / check), scope validation, source-type inference,
change-detection signatures, and recommended-action text — plus the
``WATCH_*`` constants. Each function takes the ``ForecastLedger`` instance as
its first argument; ``ForecastLedger`` keeps one-line delegates so no caller
changed.

Dependency direction (no cycle): this leaf module owns the ``WATCH_*``
constants and imports only ``forecasting.models`` + stdlib at load time. The
sole ``core`` dependency (the write gate) is reached via the module handle
``_core`` at call time, so importing ``core`` here binds a (possibly partial)
module object without touching its attributes during load.
"""

from __future__ import annotations

import hashlib
import sqlite3
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl

from forecasting.ledger import core as _core
from forecasting.models import (
    AlertEvent,
    LedgerNotFoundError,
    ValidationError,
    json_dumps,
    json_loads,
    parse_timestamp,
    utc_now_iso,
)


WATCH_SCOPE_TYPES = {"question", "domain", "topic", "domain_topic", "portfolio"}

# Typed roles for a watched source — lets the desk distinguish resolution-critical
# sources from background context so it can stop treating broad RSS the same as the
# source that actually resolves/anchors the question.
WATCH_SOURCE_ROLES = {
    "resolver",            # the source the question RESOLVES against
    "consensus",           # the consensus/estimate the question is measured vs
    "official_primary",    # the authoritative primary record (filing, press release)
    "leading_indicator",   # an early signal that moves before resolution
    "market_price",        # a market/price signal (prediction market, ticker)
    "background_context",  # broad context (general RSS/news); not resolution-critical
}

WATCH_SOURCE_TYPES = {
    "file",
    "url",
    "manual",
    "rss",
    "gdelt",
    "fivethirtyeight",
    "github",
    "githubrepo",
    "githubissues",
    "githubcommits",
    "githubactions",
    "coingecko",
    "hackernews",
    "reddit",
    "bluesky",
    "mastodon",
    "reliefweb",
    "federalregister",
    "courtlistener",
    "nvd",
    "cisakev",
    "openmeteo",
    "airquality",
    "weatherhistory",
    "usgs",
    "eonet",
    "nws",
    "clinicaltrials",
    "openfda",
    "pubmed",
    "pypi",
    "npm",
    "owid",
    "whogho",
    "fema",
    "fred",
    "eia",
    "treasury",
    "bls",
    "worldbank",
    "imf",
    "census",
    "socrata",
    "ckan",
    "stooq",
    "yahoo",
    "sec",
    "secfacts",
    "arxiv",
    "openalex",
    "crossref",
    "wikipedia",
    "wikipediapageviews",
    "manifold",
    "metaculus",
    "polymarket",
    "kalshi",
}


def active_watched_source_counts(ledger, question_ids: list[str]) -> dict[str, int]:
    """question_id -> count of its ACTIVE question-scoped watched sources.

    ONE batched ``GROUP BY`` per id-chunk (the desk N+1 lesson is law) — the
    batched equivalent of ``len(list_watched_sources(scope_type='question',
    scope_ref=qid, status='active'))``. Ids with no active watch are absent
    (caller defaults to 0)."""
    out: dict[str, int] = {}
    for chunk in ledger._chunk_ids(question_ids):
        if not chunk:
            continue
        placeholders = ",".join("?" for _ in chunk)
        with ledger._connect() as conn:
            rows = conn.execute(
                f"SELECT scope_ref, COUNT(*) AS n FROM watched_sources "
                f"WHERE scope_type = 'question' AND status = 'active' "
                f"AND scope_ref IN ({placeholders}) GROUP BY scope_ref",
                chunk,
            ).fetchall()
        for row in rows:
            if row["scope_ref"] is not None:
                out[row["scope_ref"]] = int(row["n"])
    return out


def add_watched_source(
    ledger,
    *,
    scope_type: str,
    scope_ref: str | None,
    source: str,
    source_type: str | None = None,
    role: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ledger._validate_watch_scope(scope_type, scope_ref)
    source = source.strip()
    if not source:
        raise ValidationError("watched source is required")
    if role is not None and role not in WATCH_SOURCE_ROLES:
        raise ValidationError(
            "role must be one of: " + ", ".join(sorted(WATCH_SOURCE_ROLES))
        )
    inferred_type = source_type or ledger._infer_watch_source_type(source)
    if inferred_type == "manual_note":
        inferred_type = "manual"
    if inferred_type not in WATCH_SOURCE_TYPES:
        raise ValidationError(
            "source_type must be file, url, manual, rss, gdelt, fivethirtyeight, github, githubrepo, githubissues, githubcommits, githubactions, coingecko, pypi, npm, hackernews, reddit, bluesky, mastodon, reliefweb, federalregister, courtlistener, nvd, cisakev, openmeteo, airquality, weatherhistory, usgs, eonet, nws, clinicaltrials, openfda, pubmed, owid, whogho, fema, fred, eia, treasury, bls, worldbank, imf, census, socrata, ckan, stooq, yahoo, "
            "sec, secfacts, arxiv, openalex, crossref, wikipedia, wikipediapageviews, manifold, metaculus, polymarket, or kalshi"
        )

    watch_id = f"ws_{uuid.uuid4().hex[:12]}"
    created_at = utc_now_iso()
    signature = ledger._source_signature(source, inferred_type, metadata=metadata)
    # The METHOD is the blessed write path (validation above earns it), so it
    # opens the commit context itself: every legitimate caller (tool, CLI,
    # auto-watch, cron, gateway) keeps working with zero call-site churn,
    # while a raw `sqlite3 ... INSERT INTO watched_sources` from an ad-hoc
    # script — the observed bypass — is refused by the authorizer.
    with _core.allow_ledger_writes("add_watched_source"), ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO watched_sources (
                id, scope_type, scope_ref, source, source_type, created_at,
                last_checked_at, last_seen_signature, status, metadata, role
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                watch_id,
                scope_type,
                scope_ref,
                source,
                inferred_type,
                created_at,
                created_at if signature is not None else None,
                signature,
                "active",
                json_dumps(metadata or {}),
                role,
            ),
        )
    return ledger.get_watched_source(watch_id)


def get_watched_source(ledger, watch_id: str) -> dict[str, Any]:
    with ledger._connect() as conn:
        row = conn.execute("SELECT * FROM watched_sources WHERE id = ?", (watch_id,)).fetchone()
    if row is None:
        raise LedgerNotFoundError(f"watched source not found: {watch_id}")
    return ledger._row_to_watched_source(row)


def list_watched_sources(
    ledger,
    *,
    scope_type: str | None = None,
    scope_ref: str | None = None,
    status: str | None = "active",
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if scope_type:
        clauses.append("scope_type = ?")
        params.append(scope_type)
    if scope_ref:
        clauses.append("scope_ref = ?")
        params.append(scope_ref)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM watched_sources {where} ORDER BY created_at DESC",
            params,
        ).fetchall()
    return [ledger._row_to_watched_source(row) for row in rows]


def check_watched_sources(
    ledger,
    *,
    scope_type: str | None = None,
    scope_ref: str | None = None,
    now: str | None = None,
) -> list[AlertEvent]:
    now_ts = parse_timestamp(now, field_name="now") or utc_now_iso()
    watches = ledger.list_watched_sources(scope_type=scope_type, scope_ref=scope_ref, status="active")
    alerts: list[AlertEvent] = []
    for watch in watches:
        source_type = watch["source_type"]
        current_signature = ledger._source_signature(
            watch["source"],
            source_type,
            metadata=watch.get("metadata"),
        )
        previous_signature = watch.get("last_seen_signature")
        should_alert = (
            source_type
            in {
                "file",
                "url",
                "rss",
                "gdelt",
                "fivethirtyeight",
                "github",
                "githubrepo",
                "githubissues",
                "githubcommits",
                "githubactions",
                "coingecko",
                "pypi",
                "npm",
                "hackernews",
                "reddit",
                "bluesky",
                "mastodon",
                "reliefweb",
                "federalregister",
                "courtlistener",
                "nvd",
                "cisakev",
                "openmeteo",
                "airquality",
                "weatherhistory",
                "usgs",
                "eonet",
                "nws",
                "clinicaltrials",
                "openfda",
                "pubmed",
                "owid",
                "whogho",
                "fema",
                "fred",
                "eia",
                "treasury",
                "bls",
                "worldbank",
                "imf",
                "census",
                "socrata",
                "ckan",
                "stooq",
                "yahoo",
                "sec",
                "secfacts",
                "arxiv",
                "openalex",
                "crossref",
                "wikipedia",
                "wikipediapageviews",
                "manifold",
                "metaculus",
                "polymarket",
                "kalshi",
            }
            and previous_signature is not None
            and current_signature is not None
            and current_signature != previous_signature
        )
        if should_alert:
            reason = "watched_source_unavailable" if current_signature.startswith("missing:") else "watched_source_changed"
            alerts.append(
                ledger.create_alert(
                    severity="warning" if reason == "watched_source_unavailable" else "info",
                    scope_type=watch["scope_type"],
                    scope_ref=watch["scope_ref"] or watch["id"],
                    reason=f"{reason}:{watch['id']}",
                    recommended_action=ledger._watched_source_action(watch),
                )
            )
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE watched_sources
                SET last_checked_at = ?, last_seen_signature = ?
                WHERE id = ?
                """,
                (now_ts, current_signature, watch["id"]),
            )
    # Executable update_triggers: compare the question's triggers against the
    # latest imported values and emit `trigger_fired` alerts. Scoped to the
    # questions whose watched sources we just checked.
    for question_id in {
        watch["scope_ref"]
        for watch in watches
        if watch.get("scope_type") == "question" and watch.get("scope_ref")
    }:
        alerts.extend(ledger.check_update_triggers(question_id=question_id))
    return alerts


def _row_to_watched_source(ledger, row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["metadata"] = json_loads(data["metadata"], {})
    return data


def _infer_watch_source_type(ledger, source: str) -> str:
    if source.startswith(("rss:", "atom:")):
        return "rss"
    if source.startswith("gdelt:"):
        return "gdelt"
    if source.startswith(("fivethirtyeight:", "538:")):
        return "fivethirtyeight"
    if source.startswith("github:"):
        return "github"
    if source.startswith("githubrepo:"):
        return "githubrepo"
    if source.startswith("githubissues:"):
        return "githubissues"
    if source.startswith("githubcommits:"):
        return "githubcommits"
    if source.startswith("githubactions:"):
        return "githubactions"
    if source.startswith("coingecko:"):
        return "coingecko"
    if source.startswith("pypi:"):
        return "pypi"
    if source.startswith("npm:"):
        return "npm"
    if source.startswith("hackernews:"):
        return "hackernews"
    if source.startswith("reddit:"):
        return "reddit"
    if source.startswith("bluesky:"):
        return "bluesky"
    if source.startswith("mastodon:"):
        return "mastodon"
    if source.startswith("federalregister:"):
        return "federalregister"
    if source.startswith("courtlistener:"):
        return "courtlistener"
    if source.startswith("nvd:"):
        return "nvd"
    if source.startswith("cisakev:"):
        return "cisakev"
    if source.startswith("openmeteo:"):
        return "openmeteo"
    if source.startswith("airquality:"):
        return "airquality"
    if source.startswith("weatherhistory:"):
        return "weatherhistory"
    if source.startswith("usgs:"):
        return "usgs"
    if source.startswith("eonet:"):
        return "eonet"
    if source.startswith("nws:"):
        return "nws"
    if source.startswith("clinicaltrials:"):
        return "clinicaltrials"
    if source.startswith("openfda:"):
        return "openfda"
    if source.startswith("pubmed:"):
        return "pubmed"
    if source.startswith("owid:"):
        return "owid"
    if source.startswith("whogho:"):
        return "whogho"
    if source.startswith("fema:"):
        return "fema"
    if source.startswith("fred:"):
        return "fred"
    if source.startswith("eia:"):
        return "eia"
    if source.startswith("treasury:"):
        return "treasury"
    if source.startswith("bls:"):
        return "bls"
    if source.startswith("worldbank:"):
        return "worldbank"
    if source.startswith("imf:"):
        return "imf"
    if source.startswith("census:"):
        return "census"
    if source.startswith("socrata:"):
        return "socrata"
    if source.startswith("ckan:"):
        return "ckan"
    if source.startswith("stooq:"):
        return "stooq"
    if source.startswith("yahoo:"):
        return "yahoo"
    if source.startswith("sec:"):
        return "sec"
    if source.startswith("secfacts:"):
        return "secfacts"
    if source.startswith("arxiv:"):
        return "arxiv"
    if source.startswith("openalex:"):
        return "openalex"
    if source.startswith("crossref:"):
        return "crossref"
    if source.startswith("reliefweb:"):
        return "reliefweb"
    if source.startswith("wikipedia:"):
        return "wikipedia"
    if source.startswith("wikipediapageviews:"):
        return "wikipediapageviews"
    if source.startswith("manifold:"):
        return "manifold"
    if source.startswith("metaculus:"):
        return "metaculus"
    if source.startswith("polymarket:"):
        return "polymarket"
    if source.startswith("kalshi:"):
        return "kalshi"
    source_type = ledger._infer_ingest_source_type(source)
    return "manual" if source_type == "manual_note" else source_type


def _source_signature(
    ledger,
    source: str,
    source_type: str,
    *,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    if source_type == "rss":
        return ledger._rss_source_signature(source, metadata=metadata)
    if source_type == "gdelt":
        return ledger._gdelt_source_signature(source)
    if source_type == "fivethirtyeight":
        return ledger._fivethirtyeight_source_signature(source)
    if source_type == "github":
        return ledger._github_source_signature(source)
    if source_type == "githubrepo":
        return ledger._github_repo_metadata_source_signature(source)
    if source_type == "githubissues":
        return ledger._github_issues_source_signature(source)
    if source_type == "githubcommits":
        return ledger._github_commits_source_signature(source)
    if source_type == "githubactions":
        return ledger._github_actions_source_signature(source)
    if source_type == "coingecko":
        return ledger._coingecko_source_signature(source)
    if source_type == "pypi":
        return ledger._pypi_source_signature(source)
    if source_type == "npm":
        return ledger._npm_source_signature(source)
    if source_type == "hackernews":
        return ledger._hackernews_source_signature(source)
    if source_type == "reddit":
        return ledger._reddit_source_signature(source)
    if source_type == "bluesky":
        return ledger._bluesky_source_signature(source)
    if source_type == "mastodon":
        return ledger._mastodon_source_signature(source)
    if source_type == "federalregister":
        return ledger._federalregister_source_signature(source)
    if source_type == "courtlistener":
        return ledger._courtlistener_source_signature(source)
    if source_type == "nvd":
        return ledger._nvd_source_signature(source)
    if source_type == "cisakev":
        return ledger._cisa_kev_source_signature(source)
    if source_type == "openmeteo":
        return ledger._openmeteo_source_signature(source)
    if source_type == "airquality":
        return ledger._airquality_source_signature(source)
    if source_type == "weatherhistory":
        return ledger._weatherhistory_source_signature(source)
    if source_type == "usgs":
        return ledger._usgs_source_signature(source)
    if source_type == "eonet":
        return ledger._eonet_source_signature(source)
    if source_type == "nws":
        return ledger._nws_source_signature(source)
    if source_type == "clinicaltrials":
        return ledger._clinicaltrials_source_signature(source)
    if source_type == "openfda":
        return ledger._openfda_source_signature(source)
    if source_type == "pubmed":
        return ledger._pubmed_source_signature(source)
    if source_type == "owid":
        return ledger._owid_source_signature(source)
    if source_type == "whogho":
        return ledger._who_gho_source_signature(source)
    if source_type == "fema":
        return ledger._fema_source_signature(source)
    if source_type == "fred":
        return ledger._fred_source_signature(source)
    if source_type == "eia":
        return ledger._eia_source_signature(source)
    if source_type == "treasury":
        return ledger._treasury_source_signature(source)
    if source_type == "bls":
        return ledger._bls_source_signature(source)
    if source_type == "worldbank":
        return ledger._worldbank_source_signature(source)
    if source_type == "imf":
        return ledger._imf_source_signature(source)
    if source_type == "census":
        return ledger._census_source_signature(source)
    if source_type == "socrata":
        return ledger._socrata_source_signature(source)
    if source_type == "ckan":
        return ledger._ckan_source_signature(source)
    if source_type == "stooq":
        return ledger._stooq_source_signature(source)
    if source_type == "yahoo":
        return ledger._yahoo_source_signature(source)
    if source_type == "sec":
        return ledger._sec_source_signature(source)
    if source_type == "secfacts":
        return ledger._sec_company_facts_source_signature(source)
    if source_type == "arxiv":
        return ledger._arxiv_source_signature(source)
    if source_type == "openalex":
        return ledger._openalex_source_signature(source)
    if source_type == "crossref":
        return ledger._crossref_source_signature(source)
    if source_type == "reliefweb":
        return ledger._reliefweb_source_signature(source)
    if source_type == "wikipedia":
        return ledger._wikipedia_source_signature(source)
    if source_type == "wikipediapageviews":
        return ledger._wikipediapageviews_source_signature(source)
    if source_type == "manifold":
        return ledger._manifold_source_signature(source)
    if source_type == "metaculus":
        return ledger._metaculus_source_signature(source)
    if source_type == "polymarket":
        return ledger._polymarket_source_signature(source)
    if source_type == "kalshi":
        return ledger._kalshi_source_signature(source)
    if source_type == "url":
        return ledger._url_source_signature(source)
    if source_type != "file":
        return None
    path = Path(source).expanduser()
    if not path.is_file():
        return f"missing:{path}"
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        return f"missing:{path}"
    stat = path.stat()
    return f"file:{stat.st_size}:{digest.hexdigest()}"


def _validate_watch_scope(ledger, scope_type: str, scope_ref: str | None) -> None:
    if scope_type not in WATCH_SCOPE_TYPES:
        raise ValidationError("scope_type must be question, domain, topic, domain_topic, or portfolio")
    if not scope_ref:
        raise ValidationError("scope_ref is required for watched sources")
    if scope_type == "question":
        ledger.get_question(scope_ref)
    if scope_type == "domain_topic":
        payload = json_loads(scope_ref, {})
        if not payload.get("domain") or not payload.get("topic"):
            raise ValidationError("domain_topic watched sources require domain and topic")


def _self_check_watch_scope(
    ledger,
    *,
    question_id: str | None,
    domain: str | None,
    topic: str | None,
    portfolio: str | None,
) -> tuple[str | None, str | None]:
    if question_id:
        return "question", question_id
    if portfolio:
        return "portfolio", portfolio
    if domain and topic:
        return "domain_topic", json_dumps({"domain": domain, "topic": topic})
    if domain:
        return "domain", domain
    if topic:
        return "topic", topic
    return None, None


def _watched_source_action(ledger, watch: dict[str, Any]) -> str:
    source = watch["source"]
    scope_type = watch["scope_type"]
    scope_ref = watch["scope_ref"]
    if watch["source_type"] == "rss" and scope_type == "question" and scope_ref:
        feed_source = source.split(":", 1)[1] if source.startswith(("rss:", "atom:")) else source
        filters = ledger._rss_relevance_filters(watch.get("metadata") or {})
        filter_args = ledger._rss_filter_cli_args(filters)
        since_arg = f" --since {watch['last_checked_at']}" if watch.get("last_checked_at") else ""
        return (
            f"Run `forecast import news {ledger._shell_arg(feed_source)} --question {scope_ref}"
            f"{since_arg}{filter_args}` to capture filtered RSS evidence candidates, "
            "then review the evidence and update only if the probability should move."
        )
    if watch["source_type"] == "gdelt" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("gdelt:") else source
        return (
            f"Run `forecast import gdelt \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "fivethirtyeight" and scope_type == "question" and scope_ref:
        source_value = (
            source.split(":", 1)[1].strip()
            if source.startswith(("fivethirtyeight:", "538:"))
            else source
        )
        return (
            f"Run `forecast import fivethirtyeight {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "github" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("github:") else source
        return (
            f"Run `forecast import github {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "githubrepo" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubrepo:") else source
        return (
            f"Run `forecast import githubrepo {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "githubissues" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubissues:") else source
        return (
            f"Run `forecast import githubissues {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "githubcommits" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubcommits:") else source
        return (
            f"Run `forecast import githubcommits {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "githubactions" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("githubactions:") else source
        return (
            f"Run `forecast import githubactions {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "coingecko" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("coingecko:") else source
        return (
            f"Run `forecast import coingecko {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "pypi" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("pypi:") else source
        return (
            f"Run `forecast import pypi {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "npm" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("npm:") else source
        return (
            f"Run `forecast import npm {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "hackernews" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("hackernews:") else source
        return (
            f"Run `forecast import hackernews \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "reddit" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("reddit:") else source
        return (
            f"Run `forecast import reddit \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "bluesky" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("bluesky:") else source
        return (
            f"Run `forecast import bluesky \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "mastodon" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("mastodon:") else source
        return (
            f"Run `forecast import mastodon \"{source_value}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "reliefweb" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("reliefweb:") else source
        return (
            f"Run `forecast import reliefweb \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "federalregister" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("federalregister:") else source
        return (
            f"Run `forecast import federalregister \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "courtlistener" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("courtlistener:") else source
        return (
            f"Run `forecast import courtlistener \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "nvd" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("nvd:") else source
        return (
            f"Run `forecast import nvd \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "cisakev" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("cisakev:") else source
        return (
            f"Run `forecast import cisakev \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "openmeteo" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("openmeteo:") else source
        return (
            f"Run `forecast import openmeteo {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "airquality" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("airquality:") else source
        return (
            f"Run `forecast import airquality {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "weatherhistory" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("weatherhistory:") else source
        location, query = (source_value.split("?", 1) + [""])[:2] if "?" in source_value else (source_value, "")
        params = dict(parse_qsl(query, keep_blank_values=False))
        start_date = params.get("start") or params.get("start_date")
        end_date = params.get("end") or params.get("end_date")
        date_args = f" --start-date {start_date} --end-date {end_date}" if start_date and end_date else ""
        return (
            f"Run `forecast import weatherhistory {location}{date_args} --question {scope_ref}` and then append "
            "a forecast update if the historical base rate should move."
        )
    if watch["source_type"] == "usgs" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("usgs:") else source
        return (
            f"Run `forecast import usgs \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "eonet" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("eonet:") else source
        return (
            f"Run `forecast import eonet \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "nws" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("nws:") else source
        return (
            f"Run `forecast import nws \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "clinicaltrials" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("clinicaltrials:") else source
        return (
            f"Run `forecast import clinicaltrials \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "openfda" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("openfda:") else source
        return (
            f"Run `forecast import openfda \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "pubmed" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("pubmed:") else source
        return (
            f"Run `forecast import pubmed \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "owid" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("owid:") else source
        return (
            f"Run `forecast import owid {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "whogho" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("whogho:") else source
        return (
            f"Run `forecast import whogho {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "fema" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("fema:") else source
        return (
            f"Run `forecast import fema {ledger._cli_arg(source_value)} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "fred" and scope_type == "question" and scope_ref:
        series_id = source.split(":", 1)[1].strip() if source.startswith("fred:") else source
        return (
            f"Run `forecast import fred {series_id} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "eia" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("eia:") else source
        return (
            f"Run `forecast import eia {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "treasury" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("treasury:") else source
        return (
            f"Run `forecast import treasury {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "bls" and scope_type == "question" and scope_ref:
        series_id = source.split(":", 1)[1].strip() if source.startswith("bls:") else source
        return (
            f"Run `forecast import bls {series_id} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "worldbank" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("worldbank:") else source
        return (
            f"Run `forecast import worldbank {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "imf" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("imf:") else source
        return (
            f"Run `forecast import imf {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "census" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("census:") else source
        return (
            f"Run `forecast import census \"{source_value}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "socrata" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("socrata:") else source
        return (
            f"Run `forecast import socrata \"{source_value}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "ckan" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("ckan:") else source
        return (
            f"Run `forecast import ckan {ledger._cli_arg(source_value)} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "stooq" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("stooq:") else source
        return (
            f"Run `forecast import stooq {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "yahoo" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("yahoo:") else source
        return (
            f"Run `forecast import yahoo {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "sec" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("sec:") else source
        return (
            f"Run `forecast import sec {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "secfacts" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("secfacts:") else source
        return (
            f"Run `forecast import secfacts {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "arxiv" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("arxiv:") else source
        return (
            f"Run `forecast import arxiv \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "openalex" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("openalex:") else source
        return (
            f"Run `forecast import openalex \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "crossref" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("crossref:") else source
        return (
            f"Run `forecast import crossref \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "wikipedia" and scope_type == "question" and scope_ref:
        query = source.split(":", 1)[1].strip() if source.startswith("wikipedia:") else source
        return (
            f"Run `forecast import wikipedia \"{query}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] == "wikipediapageviews" and scope_type == "question" and scope_ref:
        source_value = source.split(":", 1)[1].strip() if source.startswith("wikipediapageviews:") else source
        return (
            f"Run `forecast import wikipediapageviews {source_value} --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if watch["source_type"] in {"manifold", "metaculus", "polymarket", "kalshi"} and scope_type == "question" and scope_ref:
        source_type = watch["source_type"]
        source_value = source.split(":", 1)[1].strip() if source.startswith(f"{source_type}:") else source
        return (
            f"Run `forecast import {source_type} \"{source_value}\" --question {scope_ref}` and then append "
            "a forecast update if the probability should move."
        )
    if scope_type == "question" and scope_ref:
        return (
            f"Run `forecast research {scope_ref} {source}` and then append "
            "a forecast update if the probability should move."
        )
    if scope_type == "domain":
        domain_arg = ledger._cli_arg(scope_ref)
        return (
            f"Run `forecast self-check --domain {domain_arg} --auto-score --auto-postmortem`, "
            f"then run `forecast review --domain {domain_arg}` and update affected forecasts explicitly."
        )
    if scope_type == "topic":
        topic_arg = ledger._cli_arg(scope_ref)
        return (
            f"Run `forecast self-check --topic {topic_arg} --auto-score --auto-postmortem`, "
            "then review impacted active questions and calibration lessons."
        )
    if scope_type == "portfolio":
        portfolio_arg = ledger._cli_arg(scope_ref)
        return (
            f"Run `forecast self-check --portfolio {portfolio_arg} --auto-score --auto-postmortem`, "
            "then review impacted active questions and calibration lessons."
        )
    if scope_type == "domain_topic":
        payload = json_loads(scope_ref, {})
        domain_arg = ledger._cli_arg(str(payload.get("domain", "")))
        topic_arg = ledger._cli_arg(str(payload.get("topic", "")))
        return (
            f"Run `forecast self-check --domain {domain_arg} --topic {topic_arg} "
            "--auto-score --auto-postmortem`, then review impacted active questions and calibration lessons."
        )
    return "Review the watched source and update affected forecasts explicitly."
