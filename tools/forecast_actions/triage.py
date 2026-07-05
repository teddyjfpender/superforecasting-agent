"""Information-triage subsystem actions.

Carved from ``tools/forecasting_tool.py`` (Arc D tool-registry slice); each handler
takes ``(args, ledger)`` and returns the tool-result JSON string.  Bodies are moved
verbatim behind the unchanged ``forecast_ledger_tool`` facade; the only body edit is
the ``_ft.`` monkeypatch-forwarding hop for names tests patch on the facade module.
"""
from __future__ import annotations

import os

from forecasting.models import utc_now_iso
from forecasting.source_search import search_watched_text_sources
from tools.registry import tool_error, tool_result
from typing import Any

def label_score(args: dict[str, Any], ledger) -> str:
    from forecasting.label_scoring import LABEL_TASK_TYPES, score_labels

    predictions = args.get("predictions")
    gold = args.get("gold")
    if not isinstance(predictions, list) or not isinstance(gold, list):
        return tool_error(
            "label_score requires `predictions` and `gold` arrays of {id, label} objects",
            success=False,
        )
    task_type = (args.get("task_type") or "relevance").strip().lower()
    if task_type not in LABEL_TASK_TYPES:
        return tool_error(
            f"label_score task_type must be one of {sorted(LABEL_TASK_TYPES)}",
            success=False,
        )
    positive_class = args.get("positive_class")
    cost = args.get("cost")
    try:
        score = score_labels(
            predictions,
            gold,
            task_type=task_type,
            positive_class=str(positive_class) if positive_class else None,
            cost=float(cost) if cost is not None else None,
        )
    except (TypeError, ValueError) as exc:
        return tool_error(f"label_score: {exc}", success=False)
    return tool_result(
        success=True,
        label_score=score.to_dict(),
        note=(
            "Classification scoreboard for triage/relevance labels (the label analog of `score`, "
            "which only does Brier/log proper-scoring). 'accuracy'/'exact_match' is the headline; "
            "'positive_f1' + 'confusion' need a positive_class; 'macro_f1' averages per-class F1. "
            "Only ids present in BOTH predictions and gold are scored; the rest are counted 'skipped'."
        ),
    )

def set_label_rubric(args: dict[str, Any], ledger) -> str:
    scope_type = (args.get("scope_type") or "global").strip().lower()
    rubric = args.get("rubric")
    if not isinstance(rubric, dict):
        return tool_error(
            "set_label_rubric requires a `rubric` object "
            "{interesting_criteria (required), uninteresting_criteria?, "
            "irrelevant_criteria?, examples?, notes?}",
            success=False,
        )
    interesting = (rubric.get("interesting_criteria") or "").strip()
    if not interesting:
        return tool_error(
            "set_label_rubric: rubric.interesting_criteria is required "
            "(what counts as INTERESTING to this desk — the relevant-vs-interesting reframe)",
            success=False,
        )
    stored = ledger.set_triage_rubric(
        scope_type=scope_type,
        scope_ref=args.get("scope_ref"),
        interesting_criteria=interesting,
        uninteresting_criteria=(rubric.get("uninteresting_criteria") or ""),
        irrelevant_criteria=(rubric.get("irrelevant_criteria") or ""),
        examples=rubric.get("examples") if isinstance(rubric.get("examples"), list) else None,
        notes=(rubric.get("notes") or ""),
        metadata=rubric.get("metadata") if isinstance(rubric.get("metadata"), dict) else None,
    )
    return tool_result(
        success=True,
        rubric=stored,
        note=(
            "Desk triage rubric stored, scoped like a calibration lesson. The triage labeler "
            "retrieves the most-specific active rubric per question (domain_topic -> domain -> "
            "topic -> question_type -> global), so the 'what's interesting here' taste is explicit "
            "and versioned, not re-improvised each run."
        ),
    )

def list_label_rubrics(args: dict[str, Any], ledger) -> str:
    rubrics = ledger.list_triage_rubrics(
        scope_type=args.get("scope_type"),
        scope_ref=args.get("scope_ref"),
        active_only=args.get("active_only", True) is not False,
    )
    return tool_result(success=True, rubrics=rubrics, count=len(rubrics))

def triage_label(args: dict[str, Any], ledger) -> str:
    from forecasting import triage as triage_mod

    question_id = args.get("question_id")
    candidates = args.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        candidates = []
        if args.get("use_watched") and question_id:
            try:
                result = search_watched_text_sources(
                    ledger,
                    question_id,
                    query=args.get("query"),
                    limit=int(args.get("limit") or 20),
                )
                candidates = [c.to_dict() for c in result.candidates]
            except Exception as exc:
                return tool_error(
                    f"triage_label: could not pull watched-source candidates: {exc}",
                    success=False,
                )
        if not candidates:
            return tool_error(
                "triage_label requires a non-empty `candidates` array of "
                "{title, summary?, source_type?, source?, url?} objects "
                "(or use_watched=true with a question_id that has watched sources)",
                success=False,
            )

    rubric = None
    rubric_ref = args.get("rubric_ref")
    if rubric_ref:
        rubric = ledger.get_triage_rubric(rubric_ref)
        if rubric is None:
            return tool_error(
                f"triage_label: rubric_ref '{rubric_ref}' not found", success=False
            )
    elif question_id:
        question = ledger.get_question(question_id)
        if question is not None:
            rubric = triage_mod.active_rubric_for_question(ledger, question)

    from forecasting.quorum import DEFAULT_JUDGE_MODEL, make_aiagent_runner

    model = (
        args.get("model")
        or os.getenv("FORECAST_TRIAGE_MODEL")
        or DEFAULT_JUDGE_MODEL
    )
    runner = make_aiagent_runner(
        toolsets=(), max_iterations=2, quiet=True, timeout=180
    )
    try:
        verdicts = triage_mod.triage_candidates(
            candidates, runner=runner, model=model, rubric=rubric
        )
    except Exception as exc:
        return tool_error(f"triage_label: labeler failed: {exc}", success=False)

    persist = args.get("persist", True) is not False
    stored = (
        ledger.record_triage_labels(question_id=question_id, verdicts=verdicts)
        if persist
        else None
    )
    summary = {"keep": 0, "skim": 0, "skip": 0, "n": len(verdicts)}
    for verdict in verdicts:
        key = verdict.get("verdict")
        if key in summary:
            summary[key] += 1
    return tool_result(
        success=True,
        verdicts=(stored if stored is not None else verdicts),
        summary=summary,
        rubric_id=(rubric or {}).get("id"),
        model=model,
        note=(
            "Cheap three-way triage labels "
            "(relevant_interesting/relevant_uninteresting/irrelevant -> keep/skim/skip). "
            "Import only the keep/skim readings as evidence. Run triage_contested to route "
            "auto-labels you disagree with to operator review (label_source='expert')."
        ),
    )

def triage_contested(args: dict[str, Any], ledger) -> str:
    from forecasting.triage import IRRELEVANT, normalize_label

    question_id = args.get("question_id")
    label_ids = args.get("label_ids")
    if isinstance(label_ids, list) and label_ids:
        rows = [
            r
            for r in (ledger.get_triage_label(str(i)) for i in label_ids)
            if r is not None
        ]
    elif question_id:
        rows = ledger.list_triage_labels(
            question_id=question_id, label_source="auto", adjudicated=False
        )
    else:
        return tool_error(
            "triage_contested requires `label_ids` or a `question_id` to select auto-labeled rows",
            success=False,
        )
    if not rows:
        return tool_error(
            "triage_contested: no auto-labeled rows to check", success=False
        )

    verifier_labels = args.get("verifier_labels")
    verifier_by_ref: dict[str, str] = {}
    if isinstance(verifier_labels, list):
        for entry in verifier_labels:
            if not isinstance(entry, dict):
                continue
            ref = entry.get("candidate_ref") or entry.get("id")
            if ref is not None and entry.get("label"):
                verifier_by_ref[str(ref)] = normalize_label(entry.get("label"))
    try:
        band = (
            float(args.get("disagreement_threshold"))
            if args.get("disagreement_threshold") is not None
            else 0.15
        )
    except (TypeError, ValueError):
        band = 0.15

    contested: list[dict[str, Any]] = []
    agreed = 0
    for row in rows:
        auto = row.get("auto_label")
        is_contested = False
        detail = ""
        if verifier_by_ref:
            ref = str(row.get("candidate_ref") or row.get("id"))
            verifier_label = verifier_by_ref.get(ref) or verifier_by_ref.get(
                str(row.get("id"))
            )
            if verifier_label is not None and verifier_label != auto:
                is_contested = True
                detail = f"verifier said {verifier_label}, auto said {auto}"
        else:
            rel = row.get("relevance")
            if rel is None or abs(float(rel) - 0.5) <= band:
                is_contested = True
                detail = "labeler near the decision boundary"
            elif row.get("materiality") == "high" and auto == IRRELEVANT:
                is_contested = True
                detail = "high-materiality item labeled irrelevant"
        if not is_contested:
            agreed += 1
            continue
        scope_type = "question" if row.get("question_id") else "triage_label"
        scope_ref = str(row.get("question_id") or row["id"])
        alert = ledger.create_alert(
            severity="warning",
            scope_type=scope_type,
            scope_ref=scope_ref,
            reason=f"contested_label:{row['id']}",
            recommended_action=(
                f'Hand-label triage item {row["id"]} ("{(row.get("title") or "")[:60]}"): '
                f"auto={auto}; {detail}. Resolve with forecast_ledger relabel_route "
                f"(label_id={row['id']}, label=<relevant_interesting|relevant_uninteresting|irrelevant>)."
            ),
        )
        updated = ledger.update_triage_label(
            row["id"], contested=True, alert_id=alert.id
        )
        contested.append(
            {**(updated or row), "alert_id": alert.id, "contested_reason": detail}
        )

    return tool_result(
        success=True,
        contested=contested,
        contested_count=len(contested),
        agreed_count=agreed,
        opened_alerts=[c["alert_id"] for c in contested],
        note=(
            "Contested triage labels (auto-label disputed by the verifier, or the labeler was "
            "unsure) are opened as MANUAL contested_label alerts for operator hand-labeling — "
            "never auto-resolved by the automode. Adjudicate with relabel_route to record the "
            "expert label (label_source='expert') and acknowledge the alert."
        ),
    )

def relabel_route(args: dict[str, Any], ledger) -> str:
    from forecasting.triage import normalize_label, verdict_for_label

    adjudications = args.get("adjudications")
    if not (isinstance(adjudications, list) and adjudications):
        label_id = args.get("label_id")
        label = args.get("label")
        if not (label_id and label):
            return tool_error(
                "relabel_route requires `adjudications`=[{label_id, label}] "
                "(or a single `label_id` + `label`)",
                success=False,
            )
        adjudications = [{"label_id": label_id, "label": label}]

    now = utc_now_iso()
    relabeled: list[dict[str, Any]] = []
    for adj in adjudications:
        if not isinstance(adj, dict):
            continue
        lid = adj.get("label_id")
        raw_label = adj.get("label") or adj.get("expert_label")
        if not lid or not raw_label:
            continue
        row = ledger.get_triage_label(str(lid))
        if row is None:
            continue
        expert = normalize_label(raw_label)
        updated = ledger.update_triage_label(
            str(lid),
            expert_label=expert,
            triage_label=expert,
            label_source="expert",
            contested=False,
            adjudicated_at=now,
            verdict=verdict_for_label(expert),
        )
        alert_id = row.get("alert_id")
        if alert_id:
            try:
                ledger.acknowledge_alert(alert_id, acknowledged_at=now)
            except Exception:
                pass
        relabeled.append(updated or row)

    return tool_result(
        success=True,
        relabeled=relabeled,
        count=len(relabeled),
        note=(
            "Operator expert labels recorded (label_source='expert'); the linked contested_label "
            "alerts were acknowledged because the real adjudication work was done (never a bare ack). "
            "These rows are now held-out gold for the triage trust gate (auto_label vs expert_label)."
        ),
    )

def triage_trust(args: dict[str, Any], ledger) -> str:
    from forecasting.triage import build_triage_trust_gate

    try:
        threshold = (
            float(args.get("threshold"))
            if args.get("threshold") is not None
            else float(os.getenv("FORECAST_TRIAGE_TRUST_THRESHOLD", "0.8"))
        )
    except (TypeError, ValueError):
        threshold = 0.8
    try:
        min_sample = (
            int(args.get("min_sample"))
            if args.get("min_sample") is not None
            else int(os.getenv("FORECAST_TRIAGE_TRUST_MIN_SAMPLE", "20"))
        )
    except (TypeError, ValueError):
        min_sample = 20
    gate = build_triage_trust_gate(
        ledger, threshold=threshold, min_sample=min_sample
    )
    return tool_result(
        success=True,
        triage_gate=gate,
        note=(
            "Held-out trust gate for the cheap auto-labeler (auto_label vs the operator's expert "
            "adjudication). Until accuracy clears the threshold over min_sample adjudicated items, "
            "mode='suggest_only' (surface verdicts, never auto-filter) — the 80%-trust-bar analog. "
            "This is also surfaced in forecast doctor."
        ),
    )


HANDLERS = {
    "label_score": label_score,
    "set_label_rubric": set_label_rubric,
    "list_label_rubrics": list_label_rubrics,
    "triage_label": triage_label,
    "triage_contested": triage_contested,
    "relabel_route": relabel_route,
    "triage_trust": triage_trust,
}
