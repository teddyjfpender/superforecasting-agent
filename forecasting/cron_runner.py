"""No-agent cron runner for forecast scheduled reviews."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from forecasting.learning import is_learning_review_reason
from forecasting.ledger import ForecastLedger, allow_ledger_writes_decorator


def _env_flag(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


@allow_ledger_writes_decorator("cron_runner.run_due_reviews")
def run_due_reviews(
    *,
    db_path: str | None = None,
    now: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    thesis_aggregate: bool = False,
    synthesize_lessons: bool | None = None,
    obsidian_sync: bool = False,
    reconcile_alerts: bool = True,
    propose_resolutions: bool = True,
    score_market_nightly: bool = True,
    refresh: bool = True,
    check_triage_graduation: bool = True,
    saturation_sweep: bool = True,
    refresh_market_models_phase: bool = False,
    reforecast_runner: Callable[[list[str]], list[dict[str, Any]]] | None = None,
) -> str:
    """Run due forecast schedule rows and return a concise alert report.

    With ``thesis_aggregate`` (or ``FORECAST_THESIS_AGGREGATE``), a trailing
    phase re-aggregates every active thesis AFTER the review sweep — so theses +
    their entity suitabilities lag the members' fresh runs automatically.

    ``synthesize_lessons`` closes the calibration learning loop on a cadence:
    ``True`` runs :meth:`ForecastLedger.synthesize_bias_lessons` every sweep,
    ``False`` never, and the default ``None`` runs it exactly when this sweep
    minted new score records or postmortems (resolutions accrued, so the bias
    measurement has fresh data). Safe to run eagerly — synthesis is heavily
    gated internally (ESS, CI, FDR, shrinkage) and emits nothing on thin data.

    ``obsidian_sync`` (or ``FORECAST_OBSIDIAN_SYNC``) republishes the desk's
    learnings into the Obsidian vault after the sweep, so resolutions,
    postmortems, and fresh lessons land in the user's notes without a manual
    `obsidian sync`. Lazy plugin import + vault checks — a missing plugin or
    vault degrades to a no-op note, never an error.
    """

    ledger = ForecastLedger(db_path)

    # DETERMINISTIC self-refresh (no LLM): inject the watched-source fetcher so the
    # cadence sweep re-pulls + re-pools + auto-commits every refreshable due question.
    # The ledger (data layer) never imports the tool/adapter layer, so the fetcher is
    # built HERE and injected. A missing tool import degrades to "no refresh", not an
    # error — the alert self-check still runs.
    refresh_fetcher = None
    if refresh:
        try:
            from tools.forecasting_tool import fetch_watched_source_payloads

            refresh_fetcher = lambda specs: fetch_watched_source_payloads(specs, concurrency=4)  # noqa: E731
        except Exception:
            refresh_fetcher = None

    results = ledger.run_due_scheduled_reviews(
        now=now,
        auto_score=auto_score,
        auto_postmortem=auto_postmortem,
        refresh_fetcher=refresh_fetcher,
    )
    alert_rows = []
    for result in results:
        for alert in result["alerts"]:
            alert_rows.append(alert)

    sections: list[str] = []
    score_events = [alert for alert in alert_rows if alert.reason.startswith("score_created:")]
    postmortem_events = [alert for alert in alert_rows if alert.reason.startswith("postmortem_created:")]
    if results and alert_rows:
        learning_review_events = [
            alert for alert in alert_rows if is_learning_review_reason(alert.reason)
        ]
        lines = [
            "Forecast self-check alerts",
            f"scheduled_reviews: {len(results)}",
            "run_ids: " + ", ".join(result["run"]["id"] for result in results if result.get("run")),
            f"alerts: {len(alert_rows)}",
            f"scores_created: {len(score_events)}",
            f"postmortems_created: {len(postmortem_events)}",
            f"learning_reviews: {len(learning_review_events)}",
            "",
        ]
        for alert in alert_rows:
            lines.append(f"- {alert.severity} {alert.scope_ref}: {alert.reason}")
            lines.append(f"  action: {alert.recommended_action}")
        sections.append("\n".join(lines) + "\n")

    # Deterministic-refresh summary: how many due questions self-refreshed this
    # sweep (committed a fresh snapshot) and which errored. Emitted only when the
    # refresh pass actually did something, so a quiet cron stays quiet.
    if refresh_fetcher is not None:
        committed = 0
        no_change = 0
        refresh_errors: list[str] = []
        for result in results:
            ref = result.get("refresh")
            if isinstance(ref, dict):
                status = ref.get("status")
                if ref.get("forecast_id") or status == "committed":
                    committed += 1
                else:
                    no_change += 1
            err = result.get("refresh_error")
            if err:
                qid = (result.get("review") or {}).get("scope_ref") or "?"
                refresh_errors.append(f"{qid}: {err}")
        if committed or refresh_errors:
            lines = [
                "Deterministic refresh",
                f"committed: {committed}  no_change/skipped: {no_change}  errors: {len(refresh_errors)}",
                "",
            ]
            for row in refresh_errors:
                lines.append(f"- ERROR {row}")
            sections.append("\n".join(lines) + "\n")

    # Autonomous reforecast pass (opt-in via `cycle run --agent`): drive an LLM update
    # over the questions this sweep flagged, BEFORE thesis aggregation + lesson
    # synthesis so those phases reflect the fresh snapshots. The runner is INJECTED by
    # the CLI layer — cron_runner/ledger never import run_agent (layer purity). It
    # validates + gates each question itself and returns per-question result dicts.
    if reforecast_runner is not None:
        due_ids: list[str] = []
        seen: set[str] = set()
        for alert in alert_rows:
            qid = getattr(alert, "scope_ref", None)
            # only QUESTION-scoped alerts are reforecast targets — a domain / topic /
            # portfolio / global alert's scope_ref is not a question id.
            if getattr(alert, "scope_type", None) != "question" or not qid or qid in seen:
                continue
            reason = getattr(alert, "reason", "") or ""
            if reason.startswith(("score_created:", "postmortem_created:")):
                continue  # bookkeeping events, not reforecast triggers (a question-
                # scoped domain_error_profile_applies, by contrast, IS a real trigger)
            seen.add(qid)
            due_ids.append(qid)
        if due_ids:
            try:
                ref_results = reforecast_runner(due_ids)
            except Exception as exc:  # never break the sweep on the reforecast pass
                sections.append(f"Autonomous reforecast\nERROR: {exc}\n")
                ref_results = []
            if ref_results:
                by_status: dict[str, int] = {}
                for r in ref_results:
                    by_status[r.get("status", "?")] = by_status.get(r.get("status", "?"), 0) + 1
                lines = [
                    "Autonomous reforecast",
                    "reforecast " + str(len(ref_results)) + ": " + ", ".join(f"{k} {v}" for k, v in sorted(by_status.items())),
                    "",
                ]
                for r in ref_results:
                    lines.append(f"- {r.get('status')} {r.get('question_id')}: {r.get('detail', '')}")
                sections.append("\n".join(lines) + "\n")

    # Trailing thesis-aggregation phase: theses (+ their entity suitabilities)
    # re-aggregate after the member review sweep.
    if thesis_aggregate:
        try:
            summary = ledger.aggregate_all_theses(now=now)
        except Exception as exc:  # never break the unattended sweep on aggregation
            sections.append(f"Thesis aggregation\nERROR: {exc}\n")
            summary = {"count": 0, "results": []}
        if summary["count"]:
            rows = summary["results"]
            ok = [row for row in rows if row.get("ok")]
            withheld = [row for row in ok if row.get("withheld")]
            failed = [row for row in rows if not row.get("ok")]
            lines = [
                "Thesis aggregation",
                f"theses: {summary['count']}  committed: {len(ok) - len(withheld)}  "
                f"withheld: {len(withheld)}  failed: {len(failed)}",
                "",
            ]
            for row in rows:
                if not row.get("ok"):
                    lines.append(f"- {row['id']}: ERROR {row.get('error')}")
                    continue
                health = row.get("health")
                health_text = f"{health:.0%}" if isinstance(health, (int, float)) else "withheld"
                lines.append(
                    f"- {row['id']}: health {health_text} "
                    f"({row.get('entity_count', 0)} entities, {row.get('trigger_count', 0)} triggers)"
                )
            sections.append("\n".join(lines) + "\n")

    # Trailing lesson-synthesis phase: when this sweep minted scores or
    # postmortems (or the caller forced it), re-measure signed calibration
    # bias and update the lesson set. Internally gated — emits nothing on
    # thin/noisy data — so the cadence can be eager without over-biasing.
    run_synthesis = (
        synthesize_lessons
        if synthesize_lessons is not None
        else bool(score_events or postmortem_events)
    )
    if run_synthesis:
        try:
            synth_results = ledger.synthesize_bias_lessons(now=now)
        except Exception as exc:  # never break the cron sweep on synthesis
            sections.append(f"Lesson synthesis\nERROR: {exc}\n")
        else:
            acted = [
                row
                for row in synth_results
                if (row.get("action") or {}).get("written")
                or (row.get("action") or {}).get("retired")
            ]
            if acted:
                lines = ["Lesson synthesis", f"scopes_measured: {len(synth_results)}", ""]
                for row in acted:
                    scope_label = row.get("scope_ref") or row.get("scope_type") or "global"
                    action = row.get("action") or {}
                    bits = []
                    if action.get("written"):
                        bits.append(f"lesson {action.get('lesson_status', 'written')}")
                    if action.get("retired"):
                        bits.append(f"retired {len(action['retired'])}")
                    lines.append(f"- {scope_label}: {', '.join(bits)}")
                sections.append("\n".join(lines) + "\n")

    # Trailing vault-publish phase (opt-in): keep the user's Obsidian vault
    # tracking the desk. Plugin and vault are both optional — degrade quietly.
    if obsidian_sync:
        try:
            from plugins.obsidian.sync import sync_learnings
            from plugins.obsidian.vault import resolve_vault_path
        except ImportError:
            sections.append("Obsidian sync\nskipped: obsidian plugin not available\n")
        else:
            vault = resolve_vault_path()
            if vault is None:
                sections.append("Obsidian sync\nskipped: no vault (set OBSIDIAN_VAULT_PATH)\n")
            else:
                try:
                    summary = sync_learnings(vault, db=str(ledger.db_path))
                except Exception as exc:  # never break the cron sweep on publishing
                    sections.append(f"Obsidian sync\nERROR: {exc}\n")
                else:
                    sections.append(
                        "Obsidian sync\n"
                        f"published {summary['questions']} question dossier(s) and "
                        f"{summary['lessons']} lesson(s) -> {summary['vault']}\n"
                    )

    # Trailing alert-reconciliation phase: auto-acknowledge alerts whose
    # source-change has already been consumed (fresh evidence imported AND a
    # forecast committed since the alert fired), so the autonomous loop closes the
    # alert lifecycle instead of leaving the operator with stale, fatigue-inducing
    # alerts. Conservative — only clearly-consumed alerts are touched.
    if reconcile_alerts:
        try:
            recon = ledger.reconcile_alerts(now=now)
        except Exception as exc:  # never break the sweep on reconciliation
            sections.append(f"Alert reconciliation\nERROR: {exc}\n")
        else:
            if recon["reconciled_count"]:
                sections.append(
                    "Alert reconciliation\n"
                    f"acknowledged {recon['reconciled_count']} consumed alert(s); "
                    f"{len(recon['still_open'])} still open\n"
                )

    # Trailing resolver-proposal phase: run resolution rules + raise a confirm-me
    # alert for any question now DETERMINABLY resolvable from ingested data. The
    # resolver framework's autonomy — the desk surfaces "ready to resolve, YES"
    # itself (propose-only; the operator confirms). Deduped, so no re-alert spam.
    if propose_resolutions:
        try:
            proposed = ledger.propose_due_resolutions()
        except Exception as exc:  # never break the sweep on proposal
            sections.append(f"Resolution proposals\nERROR: {exc}\n")
        else:
            raised = [item for item in proposed if item.get("alerted")]
            if raised:
                sections.append(
                    "Resolution proposals\n"
                    f"proposed {len(raised)} resolution(s) for confirmation\n"
                )

    # Trailing market-nightly scoring phase (AIA P2.1): score any pending
    # foreknowledge-proof benchmark entry whose market has since RESOLVED. ONLY
    # scoring runs on the cycle — SAMPLING (which would hit a market source) stays
    # explicit/opt-in via the CLI, never the unattended sweep. Best-effort: a hiccup
    # must never break the cycle, and score_matured is idempotent.
    if score_market_nightly:
        try:
            from forecasting.market_nightly import score_matured

            matured = score_matured(ledger, now=now)
        except Exception as exc:  # never break the sweep on benchmark scoring
            sections.append(f"Market-nightly scoring\nERROR: {exc}\n")
        else:
            # Only announce what was NEWLY scored this sweep, so a fully-scored set
            # does not re-emit the same alert on every cron run.
            if matured.get("n_newly_scored"):
                # Surface the contemporaneous/frozen split: the agent-beats-market EDGE
                # only counts contemporaneous baselines (frozen ForecastBench priors are
                # scored but quarantined from the claim).
                sections.append(
                    "Market-nightly scoring\n"
                    f"scored {matured['n_newly_scored']} newly-matured benchmark entr(ies); "
                    f"{matured['n_still_pending']} still pending "
                    f"(contemporaneous: {matured.get('n_contemporaneous', 0)}, "
                    f"frozen-baseline excluded from edge: {matured.get('n_frozen_excluded', 0)})\n"
                )

    # Trailing triage trust-gate graduation phase (deterministic, no LLM): if the
    # cheap auto-labeler's held-out accuracy crossed the trust bar since the last
    # sweep (or dropped back below it), fire the one-time graduation/demotion INFO
    # alert. Idempotent — silent unless the mode actually TRANSITIONED — so it can
    # run every sweep. Best-effort: never break the sweep on it.
    if check_triage_graduation:
        try:
            transition = ledger.check_triage_gate_graduation(now=now)
        except Exception as exc:  # never break the sweep on the graduation check
            sections.append(f"Triage trust gate\nERROR: {exc}\n")
        else:
            if transition is not None and transition.get("alert") is not None:
                gate = transition.get("gate") or {}
                sections.append(
                    "Triage trust gate\n"
                    f"labeler {transition['transition']}: mode {transition.get('previous_mode')} -> "
                    f"{transition['mode']} (n={gate.get('n')}, accuracy={gate.get('observed_accuracy')})\n"
                )

    # Trailing saturation-sweep phase (Wave 3 H4): scan active LIVE forecasts and
    # open a deduped WARN alert for each whose STORED observe-mode saturation score
    # is below the bar (forecasting.hooks.sweep_alert_threshold, default 60). The
    # observe score is recorded on every commit but changes no behaviour; this makes
    # a chronically under-saturated forecast VISIBLE + actionable. Read-only over the
    # stored report (no hook recompute), deduped (fold like the neighbouring alert
    # kinds — never a bare re-alert), and best-effort (never breaks the sweep).
    if saturation_sweep:
        try:
            sat = ledger.sweep_saturation_alerts()
        except Exception as exc:  # never break the sweep on the saturation pass
            sections.append(f"Saturation sweep\nERROR: {exc}\n")
        else:
            if sat.get("alerted"):
                sections.append(
                    "Saturation sweep\n"
                    f"under-saturated: {sat['under_saturated']} of {sat['checked']} checked; "
                    f"opened {len(sat['alerted'])} WARN alert(s)\n"
                )

    # Trailing Market-Model refresh phase (M5, flag-gated OFF by default): re-pull +
    # recompute active Market Models linked to still-open questions and open a deduped
    # WARN alert when a linked model's projection moves materially, so a data-driven
    # forecast leg staying stale is VISIBLE. Deterministic recompute + best-effort
    # re-narration; never breaks the sweep.
    if refresh_market_models_phase:
        try:
            mm = refresh_market_models(ledger, now=now)
        except Exception as exc:  # never break the sweep on the model refresh
            sections.append(f"Market-model refresh\nERROR: {exc}\n")
        else:
            if mm.get("alerted"):
                sections.append(
                    "Market-model refresh\n"
                    f"moved: {mm['moved']} of {mm['refreshed']} refreshed ({mm['checked']} checked); "
                    f"opened {len(mm['alerted'])} WARN alert(s)\n"
                )

    return "\n".join(sections)


def gated_evidence_collection(
    led: ForecastLedger,
    warning: Any,
    *,
    evidence_search: Callable[[Any, Any], Any],
) -> dict[str, Any] | None:
    """Run an injected evidence search+import for a no-evidence question and ack
    ONLY when it actually imported NEW evidence.

    ``evidence_search`` is the AGENT-tier (LLM/web) pass: it researches the
    question and IMPORTS readings through the existing gated import path
    (``import_source_evidence`` / the research stage), which already dedupes a
    reading already on file. We measure the NET-NEW evidence rows it produced
    (mirroring the CLI dedupe gate's ``skipped_duplicates`` accounting) and return
    a truthy summary ONLY when ``>= 1`` genuinely-new row landed. An empty fetch or
    a dup-only fetch nets zero rows → ``None`` → the dispatcher leaves the alert
    OPEN (never a bare ack to drop the count).

    PARTIAL IMPORT: the search may raise (model/network failure) AFTER it already
    imported one or more readings — a multi-source research pass that lands a row
    and then drops mid-stream. The gated work is the row(s) that ACTUALLY landed,
    so we measure NET-NEW rows even on a raise: if ``>= 1`` row landed before the
    error we treat it as SUCCESS (the alert resolves cleanly — the question is now
    forecastable, and re-surfacing it would just re-research evidence we already
    hold). Only a genuinely ZERO-new-row outcome stays OPEN: an empty/dup-only
    fetch returns ``None``, and a raise that landed nothing is re-raised so the
    dispatcher catches it and re-surfaces the alert next pass. The ``>= 1``-row
    truthy gate is unchanged — no false-positive ack on a dup-only/empty fetch.
    """
    if warning.scope_type != "question" or not warning.scope_ref:
        return None
    qid = warning.scope_ref
    before = len(led.list_evidence(qid))
    search_error: Exception | None = None
    search_result: Any = None
    try:
        search_result = evidence_search(led, warning)
    except Exception as exc:  # may have landed rows before failing — measure below.
        search_error = exc
    new_rows = len(led.list_evidence(qid)) - before
    if new_rows < 1:
        # No NEW evidence (empty/dup-only fetch, or a raise that landed nothing) —
        # the question still cannot be forecast, so leave the alert OPEN rather than
        # acking on no real work. A genuine error re-raises so the dispatcher reports
        # it "failed" (and stamps the re-spend cooldown); an empty fetch returns None.
        if search_error is not None:
            raise search_error
        return None
    # >= 1 NEW row landed — real gated work happened (even if the search later
    # raised on a partial import), so ack the alert as the natural consequence.
    return {
        "question_id": qid,
        "new_evidence": new_rows,
        "search_result": search_result,
        "partial_import": search_error is not None,
    }


# Default cap on candidates pulled + triaged per material-change evidence-autopilot
# pass — bounds the cheap-model token spend to one small labeler call per change.
_EVIDENCE_AUTOPILOT_CANDIDATE_CAP_DEFAULT = 10


def run_evidence_autopilot(
    led: ForecastLedger,
    question_id: str,
    *,
    triage_runner: Callable[[str, str, str], str],
    triage_model: str,
    now: str | None = None,
    candidate_cap: int | None = None,
    trust_threshold: float = 0.8,
    trust_min_sample: int = 20,
) -> dict[str, Any] | None:
    """INGEST -> TRIAGE -> IMPORT the watched-source firehose for one question (S6.1).

    Pulls up to ``candidate_cap`` candidate readings from the question's watched
    text sources, labels them with the CHEAP auto-labeler (``triage_runner`` — the
    same injected ``(model, system, user) -> str`` shape the triage tool wires), and
    then branches on the held-out trust gate:

    * gate PASSES (``can_auto_filter``): auto-capture the keep/skim readings as
      evidence via :func:`capture_watched_text_candidates`, measuring NET-NEW rows
      exactly like :func:`gated_evidence_collection` so "imported" reflects real work;
      the existing autopilot reforecast proposal then rides the fresh evidence.
    * gate NOT passed: persist the labels as staging rows and open a SUGGEST-ONLY
      "N candidates triaged, M keeps await review" alert — NO auto-import.

    Cheap-model spend is bounded (one labeler call over <= cap candidates) and the
    caller invokes this only in a PAID context (an injected ``triage_runner``). The
    caller wraps this fail-open, so a broken pass degrades to the deterministic
    autopilot, never blocks.
    """
    from forecasting import triage as triage_mod
    from forecasting.source_search import (
        capture_watched_text_candidates,
        search_watched_text_sources,
    )

    cap = (
        _EVIDENCE_AUTOPILOT_CANDIDATE_CAP_DEFAULT
        if candidate_cap is None
        else max(int(candidate_cap), 0)
    )
    if cap <= 0:
        return None
    search = search_watched_text_sources(led, question_id, limit=cap)
    candidates = list(search.candidates)
    if not candidates:
        return {"candidates": 0, "triaged": 0, "imported": 0, "staged": 0, "mode": None}

    question = led.get_question(question_id)
    rubric = (
        triage_mod.active_rubric_for_question(led, question) if question is not None else None
    )
    # parse_triage_response guarantees one verdict per candidate index, in order.
    verdicts = triage_mod.triage_candidates(
        [candidate.to_dict() for candidate in candidates],
        runner=triage_runner,
        model=triage_model,
        rubric=rubric,
    )
    gate = triage_mod.build_triage_trust_gate(
        led, threshold=trust_threshold, min_sample=trust_min_sample
    )

    if gate.get("can_auto_filter"):
        keep_skim = [
            candidates[index]
            for index, verdict in enumerate(verdicts)
            if verdict.get("verdict") in ("keep", "skim")
        ]
        before = len(led.list_evidence(question_id))
        captured = (
            capture_watched_text_candidates(led, question_id, keep_skim, limit=cap)
            if keep_skim
            else []
        )
        imported = len(led.list_evidence(question_id)) - before
        # Persist the auto-labels as staging rows for provenance + trust-gate scoring.
        led.record_triage_labels(question_id=question_id, verdicts=verdicts)
        return {
            "candidates": len(candidates),
            "triaged": len(verdicts),
            "imported": imported,
            "captured": len([c for c in captured if c.evidence is not None]),
            "staged": len(verdicts),
            "mode": "auto",
            "gate": gate,
        }

    # Trust gate NOT passed — stage the labels and leave a SUGGEST-ONLY alert; the
    # keeps await human review. NEVER a bare ack, NEVER an auto-import.
    staged = led.record_triage_labels(question_id=question_id, verdicts=verdicts)
    keeps = sum(1 for verdict in verdicts if verdict.get("verdict") == "keep")
    reason = f"triage_suggest_review:{question_id}"
    # Dedup: don't stack a fresh suggest-review alert on top of an already-open one
    # for the same question (repeated material changes would otherwise spam it).
    already_open = any(
        a.reason == reason for a in led.list_alerts(unresolved_only=True)
    )
    alert = None
    if not already_open:
        alert = led.create_alert(
            severity="info",
            scope_type="question",
            scope_ref=question_id,
            reason=reason,
            recommended_action=(
                f"{len(verdicts)} candidates triaged, {keeps} keeps await review — the triage "
                "labeler is suggest-only (trust gate not cleared, so no auto-import). Review with "
                f"`forecast triage list --question {question_id}` and import the keeps, or adjudicate "
                "contested labels (`forecast triage relabel`) to graduate the labeler."
            ),
        )
    return {
        "candidates": len(candidates),
        "triaged": len(verdicts),
        "imported": 0,
        "staged": len(staged),
        "keeps": keeps,
        "mode": "suggest_only",
        "alert_id": alert.id if alert is not None else None,
        "gate": gate,
    }


def build_warning_runners(
    ledger: ForecastLedger,
    *,
    now: str | None = None,
    reforecast_runner: Callable[[Any, Any], Any] | None = None,
    evidence_search: Callable[[Any, Any], Any] | None = None,
    triage_runner: Callable[[str, str, str], str] | None = None,
    triage_model: str | None = None,
):
    """Wire the warning dispatcher's injected runners to the REAL gated paths.

    Shared by the CLI (`forecast warnings resolve/automode`), this cron phase,
    the gateway RPCs, and the agent tool so the "what counts as real gated work"
    judgment lives in exactly one place. Each runner performs genuine gated work
    and signals success by returning a truthy result; the dispatcher acks ONLY on
    that truthy result, so the load-bearing rule holds (no bare ack to drop the
    count).

    ``reforecast_runner`` (the LLM update-stage pass) is INJECTED by the caller:
    the CLI passes its `--agent` closure, while the cron/gateway/tool paths leave
    it ``None`` (so REFORECAST alerts are honestly reported "skipped" / left OPEN
    rather than bare-acked — the heavy LLM pass is opt-in, never automatic).

    ``evidence_search`` (the LLM/web EVIDENCE_COLLECTION pass for a no-evidence /
    no-snapshot question) is likewise opt-in and injected only under the paid
    `--agent` tier. When supplied it is wrapped by :func:`gated_evidence_collection`
    so the alert is acked ONLY when the search imported >= 1 NEW evidence row;
    when ``None`` the EVIDENCE_COLLECTION runner is left unwired, so those alerts
    are honestly reported "skipped" / left OPEN, never bare-acked.
    """
    from forecasting.warnings import ResolutionRunners

    evidence_runner = None
    if evidence_search is not None:
        def evidence_runner(led, warning):  # EVIDENCE_COLLECTION
            return gated_evidence_collection(led, warning, evidence_search=evidence_search)

    def autopilot_runner(led, warning):  # MATERIAL_CHANGE
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        result = led.run_autopilot(
            warning.scope_ref,
            now=now,
            trigger_reason=f"warnings:{warning.reason}"[:120],
        )
        # Real gated work = autopilot re-checked the watched source(s), recorded a
        # source snapshot, and possibly proposed/committed an update. A hard
        # "failed" status (required source down) leaves the alert OPEN to resurface.
        if not result or result.get("status") == "failed":
            return None
        # PAID evidence-autopilot (S6.1): only when a cheap-model labeler is wired
        # (opt-in --agent tier — the free continuous tick leaves triage_runner None,
        # so this never fires there and the free tier stays zero-spend). INGEST ->
        # TRIAGE -> IMPORT the watched-source firehose so the reforecast proposal
        # rides fresh, triaged evidence. Fail-open per source: a broken labeler pass
        # degrades to the deterministic autopilot result above, never blocks the ack.
        if triage_runner is not None:
            try:
                result["evidence_autopilot"] = run_evidence_autopilot(
                    led,
                    warning.scope_ref,
                    triage_runner=triage_runner,
                    triage_model=triage_model or "",
                    now=now,
                )
            except Exception as exc:  # degrade to the deterministic autopilot result
                result["evidence_autopilot_error"] = f"{exc.__class__.__name__}: {exc}"
        return result

    def score_runner(led, warning):  # SCORE
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        # The gated work for a score_due alert: compute + persist the resolved
        # question's Brier/log score. score_question writes a real score record
        # (SQLite write-gated) and returns a truthy ScoreRecord; it raises if the
        # question can't be scored yet (no snapshot / unconfirmed resolution) ->
        # the dispatcher catches it and leaves the alert OPEN. Idempotent: an
        # already-scored question returns its existing score (truthy), so acking
        # reflects real scoring work that exists, never a bare close to drop the
        # count.
        return led.score_question(warning.scope_ref)

    def postmortem_runner(led, warning):  # POSTMORTEM
        if warning.scope_type != "question" or not warning.scope_ref:
            return None
        # The gated work for a postmortem_due alert: score the resolved question
        # and write a *real* postmortem record. Mirror self_check's auto_postmortem
        # path (ledger.self_check ... auto_postmortem=True) so the automode-written
        # postmortem carries the same deterministic structured signal — the
        # derived lesson + calibration adjustment — instead of a shallow
        # hard-coded placeholder. Both helpers are non-LLM: they key off the
        # score's Brier / calibration-eligibility / sharpness, returning "" / {}
        # when no real lesson is warranted (so create_postmortem only creates a
        # tentative calibration lesson when the score actually justifies one).
        # create_postmortem raises if the question can't yet be scored -> the
        # dispatcher catches it and leaves the alert OPEN.
        score = led.score_question(warning.scope_ref)
        question = led.get_question(warning.scope_ref)
        return led.create_postmortem(
            question_id=warning.scope_ref,
            summary="Auto-created by warnings resolution after confirmed resolution and scoring.",
            what_happened="The forecast resolved and was scored while draining the open-warning backlog.",
            what_was_expected="See the linked forecast snapshot and score record for the prior probability.",
            lesson=led._auto_postmortem_lesson(question, score),
            calibration_adjustment=led._auto_postmortem_adjustment(question, score),
        )

    return ResolutionRunners(
        reforecast_runner=reforecast_runner,
        evidence_runner=evidence_runner,
        autopilot_runner=autopilot_runner,
        score_runner=score_runner,
        postmortem_runner=postmortem_runner,
    )


def run_warning_resolution(
    *,
    db_path: str | None = None,
    ledger: ForecastLedger | None = None,
    now: str | None = None,
    limit: int | None = None,
    reason: str | None = None,
    scope: str | None = None,
    kinds: Any = None,
    tier: str | None = None,
    dry_run: bool = False,
    reconcile: bool = True,
    runners: Any = None,
    reforecast_runner: Callable[[Any, Any], Any] | None = None,
    evidence_search: Callable[[Any, Any], Any] | None = None,
    triage_runner: Callable[[str, str, str], str] | None = None,
    triage_model: str | None = None,
    cooldown: bool = False,
    spend_cap: int | None = None,
    progress: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Drain the open ``alert_events`` backlog as a reusable, GATED, INTERRUPTIBLE
    phase — the factored loop behind `forecast warnings automode`, the
    ``forecast.warnings.automode.run`` background job, and the agent tool.

    * GATED: every mutating pass runs inside :func:`allow_ledger_writes`; the
      injected runners (autopilot / score / optional reforecast) are the only
      things that move a forecast, and the dispatcher acks ONLY on their truthy
      result. ``dry_run=True`` opens NO write context and acks NOTHING — it just
      returns the per-alert plan via :func:`forecasting.warnings.plan_alert`.
    * INTERRUPTIBLE: ``should_cancel`` is polled before each alert; on a set flag
      the loop stops cleanly and returns ``cancelled=True`` with the partial
      tally (the alerts already resolved stay resolved — real work is durable).
    * RE-SPEND SAFE (Slice 8): with ``cooldown=True`` a spendy AGENT-tier alert
      still inside its post-failure backoff window is excluded from selection (so
      the paid tier never re-spends on the same gated/failing alert every cycle),
      and a paid attempt that does NOT resolve the alert is stamped via
      :meth:`ForecastLedger.record_alert_attempt` (it stays OPEN — never a bare-ack
      — but is now COOLED DOWN with a doubled next window). ``spend_cap`` is the
      authoritative per-cycle agent-run ceiling: it is enforced IN THE LOOP
      (counting only attempts that actually fired a runner), so the sweep halts
      with ``budget_exhausted=True`` the moment the cap is reached, regardless of
      how many alerts selection delivered.
    * STREAMING: ``progress`` receives a dict per phase
      (``{"phase": "start"|"alert"|"reconcile"|"done", "done", "total",
      "remaining", "alert_id", "reason", "status"}``) so a caller can render a
      live heartbeat (the gateway turns these into events).

    Returns a structured summary dict.
    """
    from forecasting import warnings as fwarn
    from forecasting.ledger import allow_ledger_writes

    led = ledger if ledger is not None else ForecastLedger(db_path)
    if runners is None:
        runners = build_warning_runners(
            led,
            now=now,
            reforecast_runner=reforecast_runner,
            evidence_search=evidence_search,
            triage_runner=triage_runner,
            triage_model=triage_model,
        )

    open_warnings = fwarn.select_open_warnings(
        led, scope=scope, reason=reason, limit=limit, kinds=kinds, tier=tier,
        cooldown=cooldown, now=now,
    )
    total = len(open_warnings)

    def _emit(payload: dict[str, Any]) -> None:
        if progress is not None:
            try:
                progress(payload)
            except Exception:  # a progress sink must never break the sweep
                pass

    def _is_cancelled() -> bool:
        if should_cancel is None:
            return False
        try:
            return bool(should_cancel())
        except Exception:
            return False

    _emit({"phase": "start", "done": 0, "total": total, "remaining": total, "dry_run": dry_run})

    results: list[dict[str, Any]] = []
    cancelled = False

    if dry_run:
        # Pure preview: no write context, no acks, no runner spend.
        for index, warning in enumerate(open_warnings, start=1):
            if _is_cancelled():
                cancelled = True
                break
            entry = fwarn.plan_alert(warning, runners)
            results.append(entry)
            _emit({
                "phase": "alert", "done": index, "total": total,
                "remaining": total - index, "alert_id": warning.id,
                "reason": warning.reason, "status": entry["planned"],
            })
        tally: dict[str, int] = {}
        for entry in results:
            tally[entry["planned"]] = tally.get(entry["planned"], 0) + 1
        _emit({"phase": "done", "done": len(results), "total": total, "remaining": 0,
               "cancelled": cancelled, "dry_run": True})
        return {
            "dry_run": True,
            "cancelled": cancelled,
            "processed": len(results),
            "total": total,
            "results": results,
            "tally": tally,
            "reconcile": None,
        }

    reconcile_result: dict[str, Any] | None = None
    spent = 0  # actual agent-runner invocations this cycle (the spend_cap counter)
    budget_exhausted = False
    with allow_ledger_writes(reason="forecast_warnings_resolution"):
        for index, warning in enumerate(open_warnings, start=1):
            if _is_cancelled():
                cancelled = True
                break
            # Per-cycle agent-spend cap (Slice 8): halt the sweep BEFORE attempting
            # another alert once we have already spent the budget this cycle. A
            # cooldown-skipped alert never reaches here (filtered at selection), so
            # the cap counts only real runner invocations.
            if spend_cap is not None and spent >= spend_cap:
                budget_exhausted = True
                break
            result = fwarn.resolve_alert(led, warning, runners=runners, now=now)
            results.append(result)
            status = result.get("status")
            # A "resolved"/"failed" on an auto-resolvable (non-bookkeeping) kind means
            # the injected runner actually fired — i.e. a real (paid) spend.
            ran_runner = (
                status in {"resolved", "failed"}
                and warning.kind is not fwarn.ResolutionKind.BOOKKEEPING
            )
            if ran_runner:
                spent += 1
            # Re-spend cooldown stamp: a paid attempt that did NOT resolve the alert
            # opens/extends its exponential backoff so we do not retry it next cycle.
            # It stays OPEN (never bare-acked) — this is the opposite of an ack.
            if cooldown and status == "failed" and warning.kind in fwarn.RESPEND_COOLDOWN_KINDS:
                try:
                    led.record_alert_attempt(warning.id, now=now)
                except Exception:  # a cooldown-stamp failure must never break the sweep
                    pass
            _emit({
                "phase": "alert", "done": index, "total": total,
                "remaining": total - index, "alert_id": warning.id,
                "reason": warning.reason, "status": status,
            })
        # Reconcile unless a cooperative CANCEL stopped us mid-flight (an explicit
        # abort: do not touch alerts we never inspected). A BUDGET halt is different
        # — it only caps the PAID agent sweep; reconcile is cheap, free, non-agent
        # bookkeeping that closes already-consumed/condition-resolved alerts, and it
        # keys off persisted evidence+snapshot state (NOT on which alerts this sweep
        # processed), so it is safe and correct to run even when the spend cap halted
        # the paid pass — a budget-capped cycle still closes its resolved backlog.
        if reconcile and not cancelled:
            _emit({"phase": "reconcile", "done": len(results), "total": total, "remaining": 0})
            reconcile_result = led.reconcile_alerts(now=now)

    tally = {}
    for result in results:
        status = result.get("status", "?")
        tally[status] = tally.get(status, 0) + 1
    _emit({"phase": "done", "done": len(results), "total": total, "remaining": 0,
           "cancelled": cancelled, "budget_exhausted": budget_exhausted, "dry_run": False})
    return {
        "dry_run": False,
        "cancelled": cancelled,
        "budget_exhausted": budget_exhausted,
        "spent": spent,
        "processed": len(results),
        "total": total,
        "results": results,
        "tally": tally,
        "reconcile": reconcile_result,
    }


# ---------------------------------------------------------------------------
# Continuous warning-automode (slice 7): a FREE-tier sweep on every cron tick at
# ZERO token spend + a BOUNDED PAID tier (reforecast + evidence_collection) gated
# by a per-cycle agent-run BUDGET and a MINIMUM INTERVAL, both config-tunable.
#
# This is the unattended counterpart to `forecast warnings automode`. The free
# tier ({bookkeeping, score, postmortem, material_change}) wires only the non-LLM
# gated runners, so it is safe to run every tick. The paid tier
# ({reforecast, evidence_collection}) is the heavy LLM pass — it ALSO runs, but is
# bounded two ways so an unattended loop cannot run away with the token budget:
#   * BUDGET  — the paid pass is capped at N alerts via run_warning_resolution's
#               ``limit`` (the tier filter is applied BEFORE the limit, so the cap
#               bounds the PAID backlog, not the whole one). Each capped alert is
#               at most one agent run, so N = max agent runs per cycle.
#   * INTERVAL — the paid pass runs at most once per ``min_interval_hours``,
#               tracked by a tiny state file (last paid-run timestamp). The free
#               tier is unaffected — it runs every tick regardless.
#
# The load-bearing no-bare-ack invariant is fully preserved: this only orchestrates
# WHICH gated sweep runs WHEN; the dispatcher still acks ONLY on real gated work.
# ---------------------------------------------------------------------------

_AUTOMODE_PAID_BUDGET_DEFAULT = 3
_AUTOMODE_PAID_MIN_INTERVAL_HOURS_DEFAULT = 6.0

_AUTOMODE_BUDGET_ENV_NAMES = (
    "FORECAST_WARNINGS_PAID_BUDGET",
    "SUPERFORECASTING_AGENT_WARNINGS_PAID_BUDGET",
)
_AUTOMODE_INTERVAL_ENV_NAMES = (
    "FORECAST_WARNINGS_PAID_MIN_INTERVAL_HOURS",
    "SUPERFORECASTING_AGENT_WARNINGS_PAID_MIN_INTERVAL_HOURS",
)


def _first_env_value(names: tuple[str, ...]) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return ""


def _automode_config() -> dict[str, Any]:
    """Read the optional ``cron.warning_automode`` config block (best-effort)."""
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
        cron_cfg = cfg.get("cron", {}) if isinstance(cfg, dict) else {}
        block = cron_cfg.get("warning_automode", {}) if isinstance(cron_cfg, dict) else {}
        return block if isinstance(block, dict) else {}
    except Exception:
        return {}


def resolve_paid_budget(explicit: int | None = None) -> int:
    """Resolve the per-cycle paid-tier agent-run budget.

    Precedence: explicit arg > env (``FORECAST_WARNINGS_PAID_BUDGET``) >
    ``cron.warning_automode.paid_budget`` in config > default (3). A value of 0
    disables the paid tier entirely (free-tier-only continuous mode).
    """
    if explicit is not None:
        try:
            value = int(explicit)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    raw = _first_env_value(_AUTOMODE_BUDGET_ENV_NAMES)
    if raw:
        try:
            value = int(float(raw))
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    cfg_val = _automode_config().get("paid_budget")
    if cfg_val is not None:
        try:
            value = int(cfg_val)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return _AUTOMODE_PAID_BUDGET_DEFAULT


def resolve_paid_min_interval_hours(explicit: float | None = None) -> float:
    """Resolve the minimum hours between paid-tier passes (default 6h).

    Precedence: explicit arg > env > ``cron.warning_automode.paid_min_interval_hours``
    in config > default. A value of 0 means "no interval gate" (paid runs every
    tick, still budget-capped)."""
    if explicit is not None:
        try:
            value = float(explicit)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    raw = _first_env_value(_AUTOMODE_INTERVAL_ENV_NAMES)
    if raw:
        try:
            value = float(raw)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    cfg_val = _automode_config().get("paid_min_interval_hours")
    if cfg_val is not None:
        try:
            value = float(cfg_val)
            if value >= 0:
                return value
        except (TypeError, ValueError):
            pass
    return _AUTOMODE_PAID_MIN_INTERVAL_HOURS_DEFAULT


def _automode_state_path(state_path: str | Path | None = None) -> Path:
    if state_path is not None:
        return Path(state_path)
    from hermes_constants import get_hermes_home

    return get_hermes_home() / "cron" / "warning_automode_state.json"


def _read_automode_state(state_path: str | Path | None = None) -> dict[str, Any]:
    path = _automode_state_path(state_path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_automode_state(state: dict[str, Any], state_path: str | Path | None = None) -> None:
    path = _automode_state_path(state_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    except OSError:
        pass  # a state-write failure must never break the sweep — worst case we run paid again sooner


def _now_dt(now: str | None = None) -> datetime:
    if isinstance(now, str) and now.strip():
        try:
            return datetime.fromisoformat(now.strip())
        except ValueError:
            pass
    from hermes_time import now as hermes_now

    return hermes_now()


def _paid_interval_elapsed(last_iso: Any, now_dt: datetime, min_interval_hours: float) -> bool:
    """Whether enough time has elapsed since the last paid run to run it again.

    Fail-open: a missing or unparseable last-run timestamp is treated as eligible
    (running the paid tier again is not an invariant breach — it only spends the
    budget the operator explicitly opted into)."""
    if min_interval_hours <= 0:
        return True
    if not last_iso:
        return True
    try:
        last_dt = datetime.fromisoformat(str(last_iso))
    except (TypeError, ValueError):
        return True
    try:
        a, b = last_dt, now_dt
        if (a.tzinfo is None) != (b.tzinfo is None):
            # Normalise an awareness mismatch by dropping tzinfo from both so the
            # subtraction never raises (the interval gate is coarse, hours-scale).
            a = a.replace(tzinfo=None)
            b = b.replace(tzinfo=None)
        elapsed = (b - a).total_seconds()
    except Exception:
        return True
    return elapsed >= min_interval_hours * 3600.0


def run_warning_automode(
    *,
    db_path: str | None = None,
    ledger: ForecastLedger | None = None,
    now: str | None = None,
    paid_budget: int | None = None,
    paid_min_interval_hours: float | None = None,
    state_path: str | Path | None = None,
    runners: Any = None,
    reforecast_runner: Callable[[Any, Any], Any] | None = None,
    evidence_search: Callable[[Any, Any], Any] | None = None,
    force_paid: bool = False,
    reconcile: bool = True,
    progress: Callable[[dict[str, Any]], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """One continuous-automode cycle: an unbudgeted FREE-tier sweep followed by a
    BOUNDED PAID-tier sweep (budget cap + min-interval gate).

    The FREE tier ({bookkeeping, score, postmortem, material_change}) runs every
    call at zero token spend — its tier filter excludes the LLM kinds, so the
    injected agent closures are never invoked there. The PAID tier
    ({reforecast, evidence_collection}) runs ONLY when agent runners are wired AND
    the min interval has elapsed (or ``force_paid``); it is capped at ``paid_budget``
    alerts via ``run_warning_resolution``'s ``limit`` (one agent run per alert).

    Returns a structured summary with the per-tier ``run_warning_resolution``
    results plus the paid gating decision.
    """
    led = ledger if ledger is not None else ForecastLedger(db_path)
    budget = resolve_paid_budget(paid_budget)
    interval = resolve_paid_min_interval_hours(paid_min_interval_hours)

    if runners is None:
        runners = build_warning_runners(
            led, now=now, reforecast_runner=reforecast_runner, evidence_search=evidence_search
        )

    # FREE tier — every tick, unbudgeted, zero token spend (the tier filter keeps
    # the agent closures out of this pass). Reconcile is deferred so we run it once
    # at the end of the cycle, after whichever tier ran last.
    free = run_warning_resolution(
        ledger=led,
        now=now,
        tier="free",
        reconcile=False,
        runners=runners,
        progress=progress,
        should_cancel=should_cancel,
    )

    has_agent = (
        getattr(runners, "reforecast_runner", None) is not None
        or getattr(runners, "evidence_runner", None) is not None
    )
    state = _read_automode_state(state_path)
    last_iso = state.get("last_paid_run_at")
    now_dt = _now_dt(now)
    interval_ok = force_paid or _paid_interval_elapsed(last_iso, now_dt, interval)

    paid: dict[str, Any] | None = None
    paid_ran = False
    paid_skipped_reason: str | None = None
    if not has_agent:
        paid_skipped_reason = "no agent runners wired (free-tier-only continuous mode)"
    elif budget <= 0:
        paid_skipped_reason = "paid budget is 0 (paid tier disabled)"
    elif not interval_ok:
        paid_skipped_reason = (
            f"min interval {interval}h not elapsed since last paid run {last_iso}"
        )
    else:
        # BOUNDED paid pass: the tier filter restricts to the LLM kinds. The cap is
        # enforced two ways that agree at ``budget``: ``limit`` bounds the SELECTED
        # backlog (keeps the page small) while ``spend_cap`` is the authoritative
        # per-cycle agent-run ceiling enforced IN THE LOOP (so even if selection ever
        # over-delivers, actual runs never exceed ``budget``). ``cooldown=True`` drops
        # any spendy alert still inside its post-failure backoff window — so this pass
        # never re-spends on the same gated/failing alert every cycle. This pass owns
        # the cycle's reconcile.
        paid = run_warning_resolution(
            ledger=led,
            now=now,
            tier="reforecast",
            limit=budget,
            spend_cap=budget,
            cooldown=True,
            reconcile=reconcile,
            runners=runners,
            progress=progress,
            should_cancel=should_cancel,
        )
        paid_ran = True
        state["last_paid_run_at"] = now_dt.isoformat()
        _write_automode_state(state, state_path)

    # When the paid tier did NOT run (so it could not reconcile), still close the
    # alert lifecycle once after the free sweep — auto-ack any already-consumed
    # alert. Conservative: reconcile_alerts only touches clearly-consumed alerts.
    reconcile_result: dict[str, Any] | None = None
    if paid is not None:
        reconcile_result = paid.get("reconcile")
    elif reconcile:
        from forecasting.ledger import allow_ledger_writes

        with allow_ledger_writes(reason="forecast_warning_automode_reconcile"):
            try:
                reconcile_result = led.reconcile_alerts(now=now)
            except Exception:
                reconcile_result = None

    return {
        "free": free,
        "paid": paid,
        "paid_ran": paid_ran,
        "paid_skipped_reason": paid_skipped_reason,
        "paid_budget": budget,
        "paid_min_interval_hours": interval,
        "last_paid_run_at": state.get("last_paid_run_at"),
        "reconcile": reconcile_result,
    }


def _fmt_tally(tally: dict[str, int]) -> str:
    if not tally:
        return "nothing"
    return ", ".join(f"{status} {count}" for status, count in sorted(tally.items()))


def _automode_report(result: dict[str, Any]) -> str:
    """Concise human report for the cron delivery. Returns "" (silent) when the
    cycle did nothing worth surfacing, so the no_agent cron stays quiet."""
    free = result.get("free") or {}
    paid = result.get("paid")
    reconcile = result.get("reconcile") or {}
    free_processed = int(free.get("processed", 0) or 0)
    reconciled = int(reconcile.get("reconciled_count", 0) or 0)
    if free_processed == 0 and not result.get("paid_ran") and reconciled == 0:
        return ""  # nothing happened — stay silent

    lines = ["Warning automode"]
    lines.append(
        f"free: processed {free_processed}/{int(free.get('total', 0) or 0)} "
        f"({_fmt_tally(free.get('tally', {}))})"
    )
    if result.get("paid_ran") and paid is not None:
        lines.append(
            f"paid: processed {int(paid.get('processed', 0) or 0)}/"
            f"{int(paid.get('total', 0) or 0)} "
            f"(budget {result.get('paid_budget')}; {_fmt_tally(paid.get('tally', {}))})"
        )
    else:
        lines.append(f"paid: skipped — {result.get('paid_skipped_reason')}")
    if reconciled:
        lines.append(f"reconcile: acknowledged {reconciled} consumed alert(s)")
    return "\n".join(lines) + "\n"


def main_warning_automode(argv: list[str] | None = None) -> int:
    """argparse entrypoint for the continuous warning-automode cron job.

    Drives :func:`run_warning_automode`. The paid (LLM) tier is wired only under
    ``--agent`` (or ``FORECAST_WARNINGS_AUTOMODE_AGENT``); the agent closures are
    built lazily via the CLI layer so run_agent is never imported by this module.
    """
    parser = argparse.ArgumentParser(
        description="Run a continuous warning-automode cycle (free tier + bounded paid tier)"
    )
    parser.add_argument("--db")
    parser.add_argument("--now")
    parser.add_argument("--paid-budget", type=int)
    parser.add_argument("--paid-min-interval-hours", type=float)
    parser.add_argument(
        "--agent",
        action="store_true",
        help="Wire the paid-tier LLM runners (reforecast + evidence collection). "
        "Without it, only the free tier runs.",
    )
    parser.add_argument(
        "--force-paid",
        action="store_true",
        help="Ignore the min-interval gate and run the paid tier this cycle (still budget-capped).",
    )
    parser.add_argument("--model")
    parser.add_argument("--provider")
    parser.add_argument("--max-iterations", type=int)
    args = parser.parse_args(argv)
    db_path = args.db or os.getenv("FORECAST_LEDGER_DB") or None

    reforecast_runner = None
    evidence_search = None
    if args.agent or _env_flag("FORECAST_WARNINGS_AUTOMODE_AGENT"):
        try:
            from forecasting.cli import build_cron_warning_agent_runners

            reforecast_runner, evidence_search = build_cron_warning_agent_runners(
                db_path=db_path,
                model=args.model,
                provider=args.provider,
                max_iterations=args.max_iterations,
                now=args.now,
            )
        except Exception as exc:  # never let an agent-wiring failure kill the free tier
            print(
                f"Warning automode: failed to build paid-tier agent runners "
                f"({exc!r}); running FREE tier only.",
                file=sys.stderr,
            )

    result = run_warning_automode(
        db_path=db_path,
        now=args.now,
        paid_budget=args.paid_budget,
        paid_min_interval_hours=args.paid_min_interval_hours,
        reforecast_runner=reforecast_runner,
        evidence_search=evidence_search,
        force_paid=args.force_paid,
    )
    text = _automode_report(result)
    if text:
        print(text, end="")
    return 0


def install_warning_automode_script(
    script_path: Path,
    *,
    db_path: str | None = None,
    agent: bool = False,
    paid_budget: int | None = None,
    paid_min_interval_hours: float | None = None,
    model: str | None = None,
    provider: str | None = None,
    max_iterations: int | None = None,
) -> None:
    """Install the small script used by the continuous warning-automode cron job."""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    args: list[str] = []
    if db_path:
        args.extend(["--db", db_path])
    if agent:
        args.append("--agent")
    if paid_budget is not None:
        args.extend(["--paid-budget", str(int(paid_budget))])
    if paid_min_interval_hours is not None:
        args.extend(["--paid-min-interval-hours", str(float(paid_min_interval_hours))])
    if model:
        args.extend(["--model", model])
    if provider:
        args.extend(["--provider", provider])
    if max_iterations is not None:
        args.extend(["--max-iterations", str(int(max_iterations))])
    script_path.write_text(
        "\n".join(
            [
                "from forecasting.cron_runner import main_warning_automode",
                "",
                "if __name__ == '__main__':",
                f"    raise SystemExit(main_warning_automode({args!r}))",
                "",
            ]
        ),
        encoding="utf-8",
    )


# Default relative-move threshold for a "material" Market Model projection move.
# A refreshed projection that moves more than this fraction of the prior value (or
# whose fresh interval no longer contains the prior point) opens a deduped alert.
_MARKET_MODEL_MOVE_REL_DEFAULT = 0.10
_MARKET_MODEL_MOVE_ALERT_REASON = "market_model_moved"


def _projection_value_interval(primary: dict | None) -> tuple[float | None, float | None, float | None]:
    """Pull (projected_value, lo, hi) from a market_model._primary_projection result."""
    if not isinstance(primary, dict):
        return None, None, None
    out = primary.get("output") or {}
    pv = out.get("projected_value")
    pv = pv if isinstance(pv, (int, float)) else (out.get("value") if isinstance(out.get("value"), (int, float)) else None)
    lo = out.get("lo") if isinstance(out.get("lo"), (int, float)) else None
    hi = out.get("hi") if isinstance(out.get("hi"), (int, float)) else None
    return pv, lo, hi


def _projection_moved(prior: dict | None, fresh: dict | None, *, rel_threshold: float) -> tuple[bool, str]:
    """Material-move test between two primary projections.

    Material when the fresh projected value moves more than ``rel_threshold`` of the
    prior value, OR the fresh prediction interval no longer contains the prior point
    (a distribution shift even without a big central move). Returns ``(moved, detail)``."""
    p_val, _p_lo, _p_hi = _projection_value_interval(prior)
    f_val, f_lo, f_hi = _projection_value_interval(fresh)
    if p_val is None or f_val is None:
        return False, ""
    denom = max(abs(p_val), 1e-9)
    rel = abs(f_val - p_val) / denom
    if rel > rel_threshold:
        return True, f"projection moved {rel*100:.0f}% ({p_val:.4g} -> {f_val:.4g}, bar {rel_threshold*100:.0f}%)"
    if f_lo is not None and f_hi is not None and not (f_lo <= p_val <= f_hi):
        return True, f"prior point {p_val:.4g} is outside the fresh interval [{f_lo:.4g}, {f_hi:.4g}]"
    return False, ""


def refresh_market_models(
    ledger: ForecastLedger,
    *,
    now: str | None = None,
    rel_threshold: float | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Re-pull + recompute active Market Models linked to still-OPEN questions and
    alert on a material projection move (M5).

    Iterates active market models whose ``spec['forecast_question_id']`` points at a
    still-active forecast, re-runs the deterministic recompute (``open_market_model``
    — re-pull + recompute, keeping the timestamped writeup), and when the projection
    moves materially vs the stored presentation: re-narrates the prose against the
    fresh numbers (``renarrate_market_model``) and opens a deduped WARN alert on the
    linked question. Never a bare ack; deduped by reason+scope so it does not
    re-alert every sweep. Best-effort per model — one failure never aborts the sweep.
    Returns ``{checked, refreshed, moved, alerted:[question_id]}``.
    """
    from forecasting import market_model as MM

    bar = _MARKET_MODEL_MOVE_REL_DEFAULT if rel_threshold is None else float(rel_threshold)
    checked = refreshed = moved = 0
    alerted: list[str] = []
    try:
        models = ledger.list_market_models(status="active", limit=limit)
    except Exception:
        models = []
    for model in models:
        spec = model.get("spec") or {}
        qid = spec.get("forecast_question_id")
        model_id = model.get("id")
        if not qid or not model_id:
            continue
        # Only still-OPEN questions are worth refreshing.
        try:
            question = ledger.get_question(qid)
        except Exception:
            continue
        if getattr(question, "status", None) not in (None, "active"):
            continue
        checked += 1
        try:
            prior_pres = ledger.get_market_presentation(model_id)["presentation"]
        except Exception:
            prior_pres = {}
        prior_primary = MM._primary_projection(prior_pres)
        try:
            opened = MM.open_market_model(model_id, ledger=ledger)
        except Exception:
            continue
        if not opened.get("refreshed"):
            continue
        refreshed += 1
        fresh_primary = MM._primary_projection(opened.get("presentation") or {})
        did_move, detail = _projection_moved(prior_primary, fresh_primary, rel_threshold=bar)
        if not did_move:
            continue
        moved += 1
        # Re-narrate the prose against the fresh numbers (best-effort — degrades to
        # the prior prose if the aux LLM is unavailable).
        try:
            MM.renarrate_market_model(model_id, ledger=ledger)
        except Exception:
            pass
        if ledger._has_open_alert(
            reason=_MARKET_MODEL_MOVE_ALERT_REASON, scope_type="question", scope_ref=qid
        ):
            continue
        try:
            ledger.create_alert(
                severity="warning",
                scope_type="question",
                scope_ref=qid,
                reason=_MARKET_MODEL_MOVE_ALERT_REASON,
                recommended_action=(
                    f"Linked Market Model {model_id} moved: {detail}. Re-check the forecast — "
                    "re-open the model (`forecast model` / Markets tab) and re-run the update stage "
                    "if the driver shift changes your number."
                ),
            )
            alerted.append(qid)
        except Exception:
            pass
    return {"checked": checked, "refreshed": refreshed, "moved": moved, "alerted": alerted}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run due forecast scheduled reviews")
    parser.add_argument("--db")
    parser.add_argument("--now")
    parser.add_argument("--auto-score", action="store_true")
    parser.add_argument("--auto-postmortem", action="store_true")
    parser.add_argument("--thesis-aggregate", action="store_true")
    parser.add_argument(
        "--synthesize-lessons", action="store_true",
        help="Force calibration-lesson synthesis every sweep (default: runs when new scores/postmortems accrue)",
    )
    parser.add_argument(
        "--no-synthesize-lessons", action="store_true",
        help="Never run lesson synthesis from this cron sweep",
    )
    parser.add_argument(
        "--obsidian-sync", action="store_true",
        help="Republish lessons + question dossiers to the Obsidian vault after the sweep",
    )
    parser.add_argument(
        "--refresh-market-models", action="store_true",
        help="Re-pull + recompute Market Models linked to open questions; alert on a material projection move",
    )
    args = parser.parse_args(argv)
    db_path = args.db or os.getenv("FORECAST_LEDGER_DB") or None
    synthesize: bool | None = None
    if args.no_synthesize_lessons or _env_flag("FORECAST_NO_LESSON_SYNTHESIS"):
        synthesize = False
    elif args.synthesize_lessons or _env_flag("FORECAST_SYNTHESIZE_LESSONS"):
        synthesize = True
    text = run_due_reviews(
        db_path=db_path,
        now=args.now,
        auto_score=args.auto_score or _env_flag("FORECAST_AUTO_SCORE"),
        auto_postmortem=args.auto_postmortem or _env_flag("FORECAST_AUTO_POSTMORTEM"),
        thesis_aggregate=args.thesis_aggregate or _env_flag("FORECAST_THESIS_AGGREGATE"),
        synthesize_lessons=synthesize,
        obsidian_sync=args.obsidian_sync or _env_flag("FORECAST_OBSIDIAN_SYNC"),
        refresh_market_models_phase=(
            args.refresh_market_models or _env_flag("FORECAST_MARKET_MODEL_REFRESH")
        ),
    )
    if text:
        print(text, end="")
    return 0


def install_script(
    script_path: Path,
    *,
    db_path: str | None = None,
    auto_score: bool = False,
    auto_postmortem: bool = False,
    thesis_aggregate: bool = False,
    synthesize_lessons: bool = False,
    refresh_market_models: bool = False,
) -> None:
    """Install the small script used by no-agent forecast cron jobs."""

    script_path.parent.mkdir(parents=True, exist_ok=True)
    args = []
    if db_path:
        args.extend(["--db", db_path])
    if auto_score:
        args.append("--auto-score")
    if auto_postmortem:
        args.append("--auto-postmortem")
    if thesis_aggregate:
        args.append("--thesis-aggregate")
    if synthesize_lessons:
        args.append("--synthesize-lessons")
    if refresh_market_models:
        args.append("--refresh-market-models")
    script_path.write_text(
        "\n".join(
            [
                "from forecasting.cron_runner import main",
                "",
                "if __name__ == '__main__':",
                f"    raise SystemExit(main({args!r}))",
                "",
            ]
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    raise SystemExit(main())
