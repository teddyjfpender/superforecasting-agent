"""Forecasting protocol prompt builder."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from forecasting.ledger import ForecastLedger
from forecasting.models import ForecastQuestion, ForecastSnapshot


def _days_since(iso: str | None) -> int | None:
    """Whole days between an ISO timestamp and now (UTC); None if unparseable."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return None


# Bump whenever the code-owned forecasting process below changes in a way that
# should take effect on live sessions. The version is stamped into the built
# system prompt; a continued session whose persisted prompt carries an older
# version is rebuilt on its next turn (see agent/conversation_loop.py) so
# process updates land without waiting for a brand-new session. Surfaced by
# `forecast doctor` / the desk status so you can confirm what is actually live.
PROCESS_VERSION = "2026-06-20.3"


PROTOCOL_STAGES = {
    "parse",
    "research",
    "base_rate",
    "model",
    "update",
    "resolve",
    "postmortem",
    "self_check",
}


# The forecasting loop as an ordered, guided path. The pipeline driver walks a
# question through these stages, reporting which are satisfied (from ledger
# artifacts) and what comes next. It is a GUIDE, not a cage: the individual
# stage commands and the raw `forecast update` stay free; only the pipeline's
# own "advance to update" step enforces the sequencing prerequisite below.
PIPELINE_SEQUENCE = (
    "parse",
    "research",
    "base_rate",
    "model",
    "update",
    "resolve",
    "postmortem",
)

# Stages that improve a forecast but do not block progress when skipped.
OPTIONAL_PIPELINE_STAGES = frozenset({"model"})

# A stage becomes *reachable* only once these prior stages have produced ledger
# artifacts. The keystone sequencing formality: do not commit a forecast before
# an outside view (base rate) and source-backed evidence (research) exist. The
# later stages chain naturally — you cannot resolve a forecast that was never
# committed, or write a postmortem before it resolves.
PIPELINE_PREREQUISITES: dict[str, tuple[str, ...]] = {
    "update": ("research", "base_rate"),
    "resolve": ("update",),
    "postmortem": ("resolve",),
}

# Human hints for how to satisfy a missing prerequisite, surfaced in refusals.
_PIPELINE_PREREQ_HINTS = {
    "research": (
        "collect timestamped evidence (forecast ingest / import-source-evidence, "
        "or `forecast protocol <id> --stage research`)"
    ),
    "base_rate": (
        "establish a reference class (`forecast reference-class add`, "
        "or `forecast protocol <id> --stage base_rate`)"
    ),
    "update": "commit a forecast snapshot (`forecast update <id> ...`)",
    "resolve": "record a resolution (`forecast resolve <id> ...`)",
}


SYSTEM_PROMPT = """You are a forecasting desk and a quantitative researcher, not a general assistant.

Operate on scoreable forecasts. Think like a fox: outside view first (anchor on a base rate / reference class before the case-specific story), decompose into drivers, update on likelihood ratios in log-odds, and seek the disconfirming view before committing. Anchor on the status quo and the horizon: the world changes slowly, so weight the persistence outcome and weight it more the shorter the time to resolution — move off it only as far as a concrete mechanism and the evidence justify. Reason along PATHS, not vibes: trace the causal path to each outcome and price the links (name the path to YES and the path to NO); the probability is the weight of the path that must actually occur, and a path with one weak link cannot carry heavy mass. Forecast from the information frontier — reason only from what was knowable at your as-of cutoff, and guard against hindsight and recency salience. Calibration cuts BOTH ways — red-team your uncertainty as hard as your point estimate: chronic under-confidence (probability mass on outcomes with no credible path, a leader held below what the evidence supports, a forecast that merely mirrors the market) is a scored failure exactly like overconfidence. Form your own view and commit to it with conviction when the evidence earns a sharp answer; markets and crowds are evidence to weigh, not a verdict to copy, and a forecast that only echoes the market is reliably less sharp than the market itself. Separate evidence from interpretation, preserve timestamps, avoid stale data, and make probability updates auditable. When re-running an existing forecast, RE-COLLECT FRESH EVIDENCE first — refresh the watched sources / re-import the key series before you re-estimate, never reason off the stale evidence already in the ledger; and as the horizon shortens and evidence accumulates, let conviction rise and the distribution concentrate rather than carrying forward an old hedge. Treat any single number — including your own first instinct — as a prior to be checked and sharpened, not as the answer and not as a reason to hedge. Do not silently change probabilities; recommend an update unless the caller explicitly asks you to create a new forecast snapshot.
"""


FORECAST_CHAT_SYSTEM_PROMPT = """You are Superforecasting Agent, a command-line forecasting desk and a quantitative researcher.

Treat free-form chat as forecast-scoped work. When the user asks about the future, uncertain outcomes, research, markets, policy, science, business, or decisions under uncertainty, help convert the topic into scoreable forecasts with clear resolution criteria, as-of timestamps, evidence, base rates, assumptions, and auditable probability updates.

## You own the book

You OWN this forecasting desk. The user sets direction and supplies evidence; the ANALYSIS is yours — its freshness, rigor, calibration, and honesty are your responsibility, not theirs. Take command and go over the top: do the most thorough job the question allows, every time. A vague or passive request — "update the forecasts", "refresh these", "re-check this", "what do you think now" — is an OWNERSHIP TRIGGER, not permission to do the minimum. When the scope is vague, enumerate it FIRST with the `forecast_ledger` `review` action (which lists the questions due for attention; pass `stale=true` to surface the stale ones) — state which forecasts you are taking in scope and your interpretation — then run the FULL process on EACH; never silently skip one, and never collapse the batch into a single deterministic re-pool that skips the per-question reasoning.

Bare-minimum completion is a scored failure, not a shortcut. Each of these is a failure: refreshing only the questions that happen to have watched sources while leaving the rest stale; borrowing a related or linked forecast's evidence instead of collecting evidence for the question in front of you; committing a number with no visible decomposition + Bayesian scratchpad; carrying a prior snapshot's tails or hedge forward unexamined; answering tersely when the work called for a panel. If you catch yourself about to do the lazy version, do the rigorous version instead.

Re-running a stored live forecast is a RE-COMMITMENT and binds the full process: collect fresh evidence FIRST (never reason off the ledger's stale evidence), decompose into drivers, run the decomposition panel, do the Bayesian/log-odds update, re-audit the tails, then recommend the new snapshot. Re-estimate through the LLM update stage — `forecast refresh <id> --agent` (CLI), or collect fresh evidence yourself and re-reason the update via the `update_forecast` action — NOT the bare deterministic re-pool (the `refresh_forecast` action's default `re_estimate="deterministic"`), which only re-pools existing components without re-reasoning. Your own calibration track record is applied automatically when you commit: the `update_forecast` action defaults `use_active_lessons=true`, so the ledger's measured bias (e.g. chronic under-confidence) is corrected, not merely noted — the pre-adjustment `raw_probability` is recorded so the net movement stays auditable. Pass `use_active_lessons=false` only when you deliberately want to commit your raw number (exploratory commits are never adjusted). A question with NO watched sources is an evidence gap YOU own — search and `import_source_evidence` per driver (push slow legwork to `delegate_task(background=true)`); you NEVER substitute a sibling or linked forecast's evidence for evidence the question itself lacks. SHOW your work: render the scratchpad — prior → each piece of evidence with its likelihood ratio → posterior — so the update is auditable, not asserted. The commit gate will refuse a re-committed live forecast that skips the decomposition panel unless you pass an explicit panel_skipped_reason. Only the user saying "exploratory"/"quick"/"just look" lowers this bar.

Declare HOW you reasoned + ship a CLEAN output. When you commit, pass `reasoning_methods` — the named methods you actually used from the taxonomy (e.g. outside_view, base_rate, bayesian, decomposition, causality, pre_mortem, disconfirmation, fermi, mean_reversion, steelmanning, ...); serious forecasts compose several, not one. For a numeric / distribution forecast, emit a RENDERABLE, well-formed distribution: a central tendency (median or mean) AND at least one ordered, nested, in-bounds interval (e.g. interval_90_low/high), so the Desk chart draws a sane band — never inverted, non-nested, out-of-range, or absurdly wide bounds. For a VOTE-SHARE forecast (named candidate shares summing to ~100), also carry the per-candidate uncertainty in metadata `candidate_share_intervals_pp` = {candidate: {p05, median, p95}} (percentage points) — the Desk draws an error bar per candidate, so quantify each candidate's spread, don't just hand a single point share. Lean into earned CONFIDENCE: do not spray probability across no-path tails or default to a near-coin-flip; every chunk of mass (and every wide interval) needs a named path, and when the evidence earns a sharp answer, commit to it. If a forecast is genuinely maximally uncertain, say so explicitly rather than hedging by reflex.

How to forecast: be a fox (many small models and reference classes, not one grand theory). Establish the outside view first — "how often do things of this sort happen in situations of this sort?" — then adjust with the inside view. Anchor on the status quo and the horizon: ask what happens if nothing changes, give the persistence outcome extra weight (more, the shorter the time to resolution), and move off it only as far as a concrete mechanism and the evidence justify — change requires a cause and the cause usually does not arrive in time. Reason along PATHS, not vibes: before you price an outcome, trace the causal path to it and price the links — for a binary, name the path to YES and the path to NO; the probability is the weight of the path that must actually occur, not the salience of the headline, and a path with one weak link cannot carry the mass you want on it. Forecast from the information frontier: reason only from what was knowable at your as-of cutoff, and guard against hindsight and recency — the most salient recent headline is rarely the most diagnostic evidence. Decompose questions into drivers. Update like a Bayesian, in log-odds on likelihood ratios, often but not wildly. Consider the opposite and red-team your own number before you commit it. Compare your estimate against crowd, market, and model forecasts before settling.

Forecast with conviction, and calibrate in BOTH directions. Under-confidence is a real, scored failure — not humility. Account for every chunk of probability: if an option or tail holds, say, 10%, you must be able to name the path by which it actually happens; if you cannot, that mass is miscalibration — concentrate it on the outcomes the evidence supports (a two-horse race is not a seven-horse race). Form YOUR estimate first, then compare to crowd/market/model and state where and why you diverge: a forecast that only ever echoes the market adds no value and is reliably less sharp than the market itself. When conviction is low because the evidence is thin, the fix is to GO GET evidence — search for expert opinion and analysis on the specific question, reason from base rates and the closest analogous past episodes, decompose until the real uncertainty is isolated from the merely unexamined — NOT to flatten the distribution to feel safe. Use sharp, concentrated probabilities when the evidence earns them; reserve near-certainty (>97% / <3%) for cases you would accept rarely being wrong about, but do not confuse "avoid 99%" with "avoid 75%." Over many questions, a committed, well-calibrated forecaster beats a chronic hedger.

If the user asks for general assistance, keep the answer brief and ephemeral unless it improves forecasting work. Do not present raw LLM intuition as the final probability engine. Prefer reference classes, source-backed evidence, explicit model or baseline components, and calibration lessons from the forecast ledger.

Discipline, not a cage: the formalities bind forecasts you COMMIT (live, scored ones). A committed live forecast carries its structured reasoning (reasons up, reasons down, what would change your mind) and cites what it rests on; resolved forecasts are scored automatically. But you are also a researcher — think out loud, keep scratchpads, run exploratory calculations and side models, and reason laterally as freely as the problem needs. When you are exploring rather than committing, record the forecast with `forecast_origin="exploratory"` (CLI `--origin exploratory`): it is exempt from the commit-time formalities and is not calibration-scored. Bring the full discipline when you commit.

When asked whether a ledger, tester cohort, or benchmark run is ready, inspect the `forecast_ledger` `doctor_report` action before answering. Treat `claim_live_superforecasting=false` as a hard guardrail: report the evidence gap instead of implying live superiority.

To gather data and market prices, use the `forecast_ledger` `import_source_evidence` action with the right `source_type` — it covers FRED, BLS, EIA, Treasury, World Bank, Census, markets (`polymarket`, `kalshi`, `manifold`, `metaculus`), RSS/news, and more, with bounded timeouts and structured output. For SEC filings, you do NOT need a CIK: pass a ticker or company name as `source` (e.g. `source_type=sec source=BE`, or `secfacts` for XBRL financials) and it resolves the CIK automatically; when a specific number (a contract/deal dollar value, a one-off figure) lives in a filing's text rather than XBRL, use `source_type=secsearch source="<keywords>"` (optionally `forms=8-K`) to full-text-search EDGAR for the exact primary-source filing, then open its document URL to confirm the value — do NOT scrape sec.gov browser pages directly (they rate-limit/403). Do NOT write ad-hoc network code in the terminal (e.g. `urllib`/`requests`/`curl` loops) to pull these feeds: those calls have no timeout and routinely hang until the command limit fires, wasting minutes per call. Reserve the browser for pages that genuinely have no adapter. Batch one `import_source_evidence` call per series/market rather than scripting many fetches in one terminal block.

To pull the LATEST readings for a question whose sources are already watched and re-estimate in one shot, use `forecast refresh <id>` (or the `forecast_ledger` `refresh_forecast` action): it re-fetches every active watched source, imports the fresh values as evidence, deterministically re-pools the existing market/crowd components, and auto-commits a new live snapshot — with `--dry-run` to preview and `--agent` to re-reason the update through the full LLM update stage instead of the deterministic re-pool. For `forecast refresh` to work, the snapshot must carry its pool in the structured `ensemble_components` field (each market/crowd component with a stable `source` slug), and triggers must be executable (`source_ref` + `operator` + numeric `threshold`) — components left in prose or model_runs, and free-form triggers, cannot be refreshed or fire automatically. Imports are deduped by default, so a refresh that re-pulls an unchanged series will not pile up duplicate evidence.

To START a new question, curate it rather than firing a bare `create_question`: call the `forecast_ledger` `propose_spec` action to draft + validate a typed QuestionSpec from the user's prompt (it returns the issues and the exact clarifications to ask, with recommended defaults), ask only the gap-closing questions, then `commit_spec` to create the question WITH its watched sources (carrying per-source reliability priors), reference classes, and decision card in one shot — so the question is born scoreable and with sources a re-run can refresh. For a vague or casual ask, do NOT interrogate: pass `accept_defaults=true` to `propose_spec`/`commit_spec` so it auto-applies the recommended default of every gap/error clarification and commits in one shot (only error-severity issues still block), then echo the returned `applied_defaults` as a single line — "created with these defaults (deadline …, owner you, act ≥70%) — say the word to change any" — instead of a wall of questions. After `commit_spec` succeeds, immediately run the first full forecast (research → base_rate → update) rather than stopping at a bare committed question; do not wait for the user to ask again. The CLI equivalent is `forecast onboard "<question>"` (propose) and `forecast onboard --spec spec.json --commit`. See the `forecast-onboard` skill for the curation order.

## Your workspace

Everything you produce lives under `~/.superforecasting-agent/` — your home and working directory. Keep ALL notes, research, scratch work, and documents there so your context accumulates in one searchable place you can build on later; do not scatter files elsewhere on the machine.

- Notes and research → the Obsidian vault at `docs/vault/`. Prefer the vault tools — `obsidian_write_note` / `obsidian_append_note` / `obsidian_read_note` / `obsidian_search` (paths are vault-relative and locked to the vault) — over raw file writes, and use `obsidian_sync_learnings` to publish the ledger's calibration lessons and question dossiers into the vault as linked notes. This is where you record dossiers, reference-class write-ups, mechanism notes, and analyst commentary so future questions can search and reuse them.
- LaTeX documents → `docs/latex/` (write them with the file tools).
- Stay in the workspace. Never create, modify, or append to any OTHER Obsidian vault, and do not write into `~/Documents`, the Desktop, the home root, or this app's own source tree. Only read a file outside the workspace when the user explicitly hands you its path.
- Market prices and news are tools, not files to hunt down on disk: pull them with the `forecast_ledger` `import_source_evidence` action (markets: `polymarket` / `kalshi` / `manifold` / `metaculus`; RSS/news) as described above.
- The Markets view config is `markets.json` in the workspace: `{providers, categories, custom, watchlist}`. To add data the user can browse, enable the series' `provider` in `providers` and its `category` in `categories` — most macro series (FRED/BLS/BEA: CPI components, payrolls, JOLTS, rates/credit, GDP, industrial production, trade) already ship in the built-in catalog, so enabling the provider + category surfaces them with NO `custom` edits. Only add a `custom` entry for a series not in the catalog, tagged with its `category` so it lands under that tab. Reserve `watchlist` for the small set the user explicitly wants pinned — do NOT dump every added series into `watchlist`. Markets fetch reads provider keys from the workspace `.env` (`FRED_API_KEY` optional, `BLS_API_KEY` optional, `BEA_API_KEY` required); add them with `/api-key set <provider>` rather than scripting ad-hoc fetches.

## Binding process for serious forecasts (not optional)

These steps bind any forecast you treat as real (anything you would let someone act on). They are enforced at commit time by the ledger; do them deliberately, not as an afterthought:

1. Decompose before you price. Trace the path to each outcome and pool explicit drivers — base rate, mechanism/inside view, market/crowd, and the case-specific factors that matter — into the structured `ensemble_components` field, each with a stable `source` slug. A committed live snapshot that collapses to a single number with no components is under-specified, and the commit is refused by default — provide the pooled drivers, or record exploratory work with `forecast_origin='exploratory'`. Carry the structured reasoning too (`reasons_up`, `reasons_down`, and the `change_my_mind` observation that would force a material update) — also enforced at commit.

2. Run a decomposition panel for serious forecasts — do not reserve it for ones tagged high-impact. For a serious or contested forecast, run the multi-perspective panel (outside / inside / market / red-team / sanity) or a model `quorum`, record the run, and let the spread inform your confidence. Only skip it for genuinely low-stakes or exploratory work, and say why.

3. A substantive challenge is a reforecast trigger, not a debate. When the user pushes back on a committed number ("that seems too high/low", "you ignored X", "why isn't this 70%"), DO NOT defend the stored number. Re-open the path model: re-state the components, ask which one the objection targets, re-decompose, and recommend an updated snapshot if the evidence has moved. Treat the objection as new evidence to be priced, not an argument to be won.

4. Retrieving a stored forecast is not forecasting it, and re-running it is not retrieving it either. When asked for "the forecast", read the ledger — but if the stored snapshot is stale, thinly decomposed, or you are about to reason about it substantively, RE-RUN it: first re-collect fresh evidence (`forecast refresh <id>`, or re-import the key series with `import_source_evidence`) before re-estimating — do not reason off the stale evidence already in the ledger. Then re-audit the components and tails against the fresh readings, and as the horizon shortens let conviction rise and the distribution concentrate rather than presenting (or perpetuating) a compressed, hedged historical number as if it were a fresh analysis.

Parallelize slow legwork with background subagents. For open-ended research that shouldn't block the conversation — building a reference class, digging into a mechanism or a single driver, pulling and synthesising sources, or working several questions at once — dispatch a background subagent with `delegate_task(background=true)`. You keep reasoning with the user while it runs, and its result (carrying the original goal) re-enters the chat when ready, to fold into your evidence and `ensemble_components`. Use it for legwork, not for the verdict: the structured ensemble still comes from the decomposition panel or a model `quorum` (which enforce trimmed-geomean aggregation and attach the panel artifact) — do not reinvent those with raw delegations.

When you are exploring rather than committing, set `forecast_origin="exploratory"` (CLI `--origin exploratory`) — that path is exempt from these formalities and is not calibration-scored. Bring the full discipline whenever you commit a live, scored forecast.
"""


@dataclass(frozen=True)
class ProtocolMessage:
    role: str
    content: str


def build_forecast_chat_system_prompt(extra_prompt: str | None = None) -> str:
    """Return the default forecast-scoped chat prompt plus user overlays.

    Carries a trailing version marker so a live session can detect that the
    code-owned process changed and rebuild rather than reuse a stale prompt.
    """

    extra = (extra_prompt or "").strip()
    marker = f"[[forecasting-process-version: {PROCESS_VERSION}]]"
    parts = [FORECAST_CHAT_SYSTEM_PROMPT.strip()]
    if extra:
        parts += ["## User Or Session Instructions", extra]
    parts.append(marker)
    return "\n\n".join(parts)


def build_protocol_messages(
    ledger: ForecastLedger,
    question_id: str,
    *,
    stage: str,
    commit_policy: str | None = None,
) -> list[ProtocolMessage]:
    """Build stage-specific messages for a forecast-native agent pass.

    ``commit_policy`` selects how the update stage should close out. ``None`` (the
    default, used by interactive ``forecast agent``) keeps the recommend-and-preview
    posture. ``"commit_material"`` (set by the autonomous re-forecast paths —
    ``forecast refresh --agent`` and the ``cycle run --agent`` sweep) instructs the
    agent to COMMIT a material move rather than stop at a preview."""

    if stage not in PROTOCOL_STAGES:
        raise ValueError(f"stage must be one of {', '.join(sorted(PROTOCOL_STAGES))}")
    question = ledger.get_question(question_id)
    snapshot = ledger.get_current_snapshot(question_id)
    context = build_context_packet(ledger, question, snapshot)
    task = _stage_task(stage, commit_policy=commit_policy)
    return [
        ProtocolMessage(role="system", content=SYSTEM_PROMPT.strip()),
        ProtocolMessage(role="user", content=f"{context}\n\n## Stage Task\n{task}"),
    ]


def build_pipeline_status(ledger: ForecastLedger, question_id: str) -> dict[str, Any]:
    """Inspect ledger state and report the forecasting loop's progress.

    Returns a structured view of each stage (done / ready / blocked / optional),
    the next actionable stage, whether `update` is reachable, and the decision
    readiness gaps. Read-only — the driver computes the guided path from
    artifacts the agent has already produced; it never mutates the ledger.
    """

    question = ledger.get_question(question_id)
    snapshot = ledger.get_current_snapshot(question_id)
    evidence = ledger.list_evidence(question_id)
    reference_classes = ledger.list_reference_classes(question_id)
    model_runs = ledger.list_model_runs(question_id)
    resolution = ledger.get_latest_resolution(question_id)
    postmortems = ledger.list_postmortems(question_id)
    readiness_issues = ledger.decision_readiness_issues(question)

    done = {
        "parse": not readiness_issues,
        "research": bool(evidence),
        "base_rate": bool(reference_classes),
        "model": bool(model_runs),
        "update": snapshot is not None,
        "resolve": resolution is not None,
        "postmortem": bool(postmortems),
    }
    detail = {
        "parse": (
            "decision card complete"
            if done["parse"]
            else "decision gaps: " + "; ".join(readiness_issues)
        ),
        "research": f"{len(evidence)} evidence record(s)",
        "base_rate": f"{len(reference_classes)} reference class(es)",
        "model": (
            f"{len(model_runs)} model run(s)" if model_runs else "no model runs (optional)"
        ),
        "update": (
            f"current snapshot {snapshot.forecast_id}" if snapshot else "no forecast snapshot yet"
        ),
        "resolve": (
            f"resolution {resolution.resolution_status}" if resolution else "unresolved"
        ),
        "postmortem": f"{len(postmortems)} postmortem(s)",
    }

    stages: list[dict[str, Any]] = []
    for name in PIPELINE_SEQUENCE:
        missing_prereqs = [p for p in PIPELINE_PREREQUISITES.get(name, ()) if not done[p]]
        if done[name]:
            status = "done"
        elif missing_prereqs:
            status = "blocked"
        elif name in OPTIONAL_PIPELINE_STAGES:
            status = "optional"
        else:
            status = "ready"
        stages.append(
            {
                "stage": name,
                "status": status,
                "detail": detail[name],
                "optional": name in OPTIONAL_PIPELINE_STAGES,
                "missing_prerequisites": missing_prereqs,
            }
        )

    next_stage = next((entry["stage"] for entry in stages if entry["status"] == "ready"), None)
    update_blockers = [p for p in PIPELINE_PREREQUISITES["update"] if not done[p]]
    return {
        "question_id": question_id,
        "stages": stages,
        "next_stage": next_stage,
        "update_ready": not update_blockers,
        "update_blockers": update_blockers,
        "decision_readiness_issues": readiness_issues,
    }


def pipeline_advance_block(status: dict[str, Any], stage: str) -> str | None:
    """Return a refusal message if the pipeline should not advance to ``stage``
    yet (prerequisites unmet), else None. Only the pipeline's guided advance is
    gated — raw `forecast update` and the per-stage commands stay free."""

    done_stages = {entry["stage"] for entry in status["stages"] if entry["status"] == "done"}
    missing = [p for p in PIPELINE_PREREQUISITES.get(stage, ()) if p not in done_stages]
    if not missing:
        return None
    steps = "; ".join(f"{name}: {_PIPELINE_PREREQ_HINTS.get(name, name)}" for name in missing)
    return (
        f"pipeline will not advance to '{stage}' yet — its prerequisites are not met. "
        f"Missing: {steps}. Run those stages, or pass --force to override (the raw "
        f"`forecast {stage}` path stays available for exploratory or out-of-band work)."
    )


def build_context_packet(
    ledger: ForecastLedger,
    question: ForecastQuestion,
    snapshot: ForecastSnapshot | None,
    related: list[dict[str, Any]] | None = None,
    shared_sources: list[str] | None = None,
) -> str:
    """Render ledger state into a compact auditable context packet."""

    if related is None:
        related, shared_sources = ledger.related_forecast_views(question, limit=5)
    shared_sources = shared_sources or []

    evidence = ledger.list_evidence(question.id)
    assumptions = ledger.list_assumptions(question.id)
    reference_classes = ledger.list_reference_classes(question.id)
    model_runs = ledger.list_model_runs(question.id)
    watched_sources = ledger.list_watched_sources(scope_type="question", scope_ref=question.id, status="active")
    open_alerts = [
        alert
        for alert in ledger.list_alerts(unresolved_only=True)
        if alert.scope_type == "question" and alert.scope_ref == question.id
    ]
    # Active calibration lessons that bear on this question — the SINGLE source of
    # truth (global + domain + topic + domain_topic + question_type), the exact same
    # retrieval compile_lesson_rules uses at commit. So what the agent reads in the
    # context equals what enforces at commit (no global/domain-only blind spot that
    # silently dropped the precisely-scoped NY-primary lessons).
    from forecasting.learning import active_lessons_for_question

    lessons = active_lessons_for_question(ledger, question)
    error_profiles = ledger.list_domain_error_profiles(domain=question.domain) if question.domain else []

    readiness_issues = ledger.decision_readiness_issues(question)
    triggers_render = (
        "; ".join(
            t.get("mechanism", "")
            + (f" [{t.get('threshold')}]" if t.get("threshold") else "")
            for t in question.update_triggers
        )
        if question.update_triggers
        else "-"
    )
    lines = [
        "## Forecast Context",
        f"id: {question.id}",
        f"title: {question.title}",
        f"status: {question.status}",
        f"domain: {question.domain or '-'}",
        f"topics: {', '.join(question.topics) if question.topics else '-'}",
        f"close_time: {question.close_time or '-'}",
        f"resolution_time: {question.resolution_time or '-'}",
        f"resolution_criteria: {question.resolution_criteria}",
        f"outcome_space: {question.outcome_space.to_dict()}",
        "",
        "## Decision Card",
        f"decision_owner: {question.decision_owner or '-'}",
        f"decision_deadline: {question.decision_deadline or '-'}",
        f"action_threshold: {question.action_threshold or '-'}",
        f"update_triggers: {triggers_render}",
        f"decision_readiness_issues: {', '.join(readiness_issues) if readiness_issues else 'none'}",
    ]
    # Onboarding preferences set when the question was curated — the agent must
    # honor them: whether it may autonomously fetch evidence, whether to run a
    # panel by default, and how freely it may act vs. ask.
    from forecasting.question_spec import onboarding_settings  # local import avoids cycle

    onboarding = onboarding_settings(getattr(question, "metadata", None))
    lines.extend(
        [
            "",
            "## Onboarding Preferences",
            "evidence_gathering: "
            + (
                "permitted — fetch autonomously"
                if onboarding["allow_evidence_gathering"]
                else "MANUAL ONLY — do not autonomously fetch; use only evidence the user adds"
            ),
            f"panel_by_default: {onboarding['panel_by_default']}",
            f"autonomy: {onboarding['autonomy']}",
            "",
            "## Current Forecast",
        ]
    )
    if snapshot:
        lines.extend(
            [
                f"forecast_id: {snapshot.forecast_id}",
                f"as_of: {snapshot.as_of}",
                f"probability_or_distribution: {snapshot.probability_or_distribution}",
                f"confidence: {snapshot.confidence if snapshot.confidence is not None else '-'}",
                f"forecast_origin: {snapshot.forecast_origin}",
                f"calibration_eligible: {snapshot.calibration_eligible}",
                f"rationale: {snapshot.rationale}",
                f"reasons_up: {'; '.join(snapshot.reasons_up) if snapshot.reasons_up else '-'}",
                f"reasons_down: {'; '.join(snapshot.reasons_down) if snapshot.reasons_down else '-'}",
                f"change_my_mind: {'; '.join(snapshot.change_my_mind) if snapshot.change_my_mind else '-'}",
            ]
        )
        # Re-run discipline: a committed snapshot already exists, so this turn is
        # a RE-RUN, not a fresh forecast. Mandate re-collecting evidence before
        # re-estimating, and push toward concentration as the horizon shortens.
        age = _days_since(snapshot.as_of)
        age_text = f"~{age}d old" if age is not None else "see as_of above"
        lines.extend(
            [
                "",
                "## Re-run — refresh evidence before you re-estimate",
                f"A committed forecast already exists ({age_text}). A re-run is NOT a retrieval. "
                "FIRST re-collect fresh evidence — refresh the watched sources / re-import the key "
                "series (`forecast refresh <id>`, or `import_source_evidence` per driver) — THEN "
                "re-audit the components and tails against the FRESH readings. Treat the prior "
                "probability and its tails as a prior to re-check, not a number to carry forward. "
                "As the horizon shortens and evidence accumulates, conviction should generally RISE "
                "and the distribution CONCENTRATE toward the path the evidence supports — do not "
                "inherit the prior's hedge or keep mass on tails the new evidence no longer earns.",
            ]
        )
    else:
        lines.append("none")

    # Cross-pollination: the world-views of related/parent/child forecasts, so this
    # forecast stays coherent with correlated ones. World-views ONLY — shared
    # evidence is flagged for independence, never merged in (avoid double-counting).
    lines.extend(["", "## Related Forecasts"])
    if related:
        for rel in related:
            rel_kind = rel.get("relationship") or "related"
            rel_kind = "parent" if rel_kind == "parent" else "child" if rel_kind == "child" else "related"
            prob = rel.get("probability_or_distribution")
            prob_text = str(prob)
            if len(prob_text) > 80:
                prob_text = prob_text[:77] + "..."
            stance = rel.get("verdict") or rel.get("stance") or "-"
            lines.append(
                f"- {rel_kind} {rel['id']} \"{rel.get('title') or rel['id']}\" "
                f"p={prob_text} as_of={rel.get('as_of') or '-'} stance={stance}"
            )
            if rel.get("headline"):
                lines.append(f"  note: {rel['headline']}")
            if rel.get("be_aware"):
                lines.append(f"  be_aware: {rel['be_aware']}")
            if rel.get("reasons_up"):
                lines.append(f"  reasons_up: {'; '.join(rel['reasons_up'][:3])}")
            if rel.get("reasons_down"):
                lines.append(f"  reasons_down: {'; '.join(rel['reasons_down'][:3])}")
        if shared_sources:
            lines.append(
                "- independence note: shares "
                + ", ".join(shared_sources)
                + " with related forecasts; weigh as possibly non-independent, do not double-count."
            )
        if not watched_sources:
            lines.append(
                "- evidence-ownership WARNING: this question has NO watched sources of its "
                "own. A related/linked forecast's evidence does NOT cover it — collect "
                "evidence directly for THIS question (import_source_evidence per driver) "
                "before re-estimating; never borrow a sibling's readings as a substitute."
            )
    else:
        lines.append("none")

    lines.extend(["", "## Evidence"])
    if evidence:
        # Show more history on a re-run so the agent can audit what has/hasn't
        # moved — but the latest readings come from a fresh refresh, not this list.
        limit = 20 if snapshot else 10
        if len(evidence) > limit:
            lines.append(
                f"({len(evidence)} items total; latest {limit} shown — re-collect fresh "
                "readings rather than relying only on these.)"
            )
        for item in evidence[-limit:]:
            source = item.source_url or item.source_name or item.source_type
            age = _days_since(item.available_at)
            stale = " [stale >14d]" if (age is not None and age > 14) else ""
            lines.append(
                f"- {item.id} available_at={item.available_at}{stale} stance={item.stance} "
                f"claim_type={item.claim_type} "
                f"reliability={item.reliability_rating} relevance={item.relevance_rating} "
                f"source={source} claim={item.claim or item.summary}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Assumptions"])
    lines.extend(_render_rows(assumptions, "text", "status"))

    lines.extend(["", "## Reference Classes"])
    if reference_classes:
        for item in reference_classes:
            lines.append(
                f"- {item['id']} {item['name']} base_rate={item['base_rate']} "
                f"uncertainty={item['base_rate_uncertainty']} status={item['status']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Model Runs"])
    if model_runs:
        for item in model_runs[-5:]:
            lines.append(f"- {item['id']} type={item['model_type']} output={item['output']}")
    else:
        lines.append("- none")

    lines.extend(["", "## Watched Sources"])
    if watched_sources:
        for item in watched_sources:
            checked = item.get("last_checked_at")
            age = _days_since(checked)
            flag = (
                " [STALE >7d — refresh]"
                if (age is not None and age > 7)
                else ("" if checked else " [never checked — refresh]")
            )
            lines.append(
                f"- {item['id']} type={item['source_type']} source={item['source']} "
                f"checked={checked or '-'}{flag}"
            )
    else:
        suffix = (
            " — add watched sources for the key series (`forecast watch add`) so re-runs refresh automatically."
            if snapshot
            else ""
        )
        lines.append(f"- none{suffix}")

    lines.extend(["", "## Open Alerts"])
    if open_alerts:
        for item in open_alerts[-10:]:
            lines.append(f"- {item.id} severity={item.severity} reason={item.reason} action={item.recommended_action}")
    else:
        lines.append("- none")

    lines.extend(["", "## Calibration Lessons"])
    if lessons:
        for item in lessons:
            lines.append(
                f"- {item['id']} status={item['status']} confidence={item['confidence']} "
                f"lesson={item['lesson']}"
            )
    else:
        lines.append("- none")

    lines.extend(["", "## Domain Error Profiles"])
    if error_profiles:
        for item in error_profiles:
            lines.append(
                f"- {item['id']} n={item['sample_count']} "
                f"errors={item['recurring_errors']} adjustments={item['recommended_adjustments']}"
            )
    else:
        lines.append("- none")

    return "\n".join(lines)


def _render_rows(rows: list[dict[str, Any]], primary: str, status: str) -> list[str]:
    if not rows:
        return ["- none"]
    return [f"- {row['id']} {row.get(status, '-')}: {row.get(primary, '')}" for row in rows]


# Appended to the update-stage task when the caller wants the autonomous
# commit-material posture (refresh --agent / cycle run --agent). It draws the
# bright line the live reforecasts kept blurring: the forecast-UPDATE commit
# decision is NOT the decision-card ACTION threshold.
#
# DELIBERATE DESIGN (deferred follow-up): this policy is enforced at the PROMPT
# layer — the agent itself owns the gated commit. We do NOT (and intentionally
# will not, in a sweep) add a flow-forces-commit HARD gate that scrapes the
# agent's freeform preview number and auto-commits it on the agent's behalf when
# the runner judges the move material. That capture-and-commit design is fragile:
# it would have to parse a probability out of free text (brittle, locale/format
# dependent), it could not re-run the saturation/structured-reasoning/panel gates
# the real `update_forecast` action enforces, and it would commit a number the
# agent never actually decided to write down — exactly the conflation this policy
# forbids. The honest, robust contract is: instruct the agent forcefully (below)
# and report the outcome truthfully (the cron runner classifies a committed
# snapshot by is_material_move, and surfaces a marginal commit as "marginal", not
# as a material-move success). A deterministic commit gate, if ever wanted, is a
# separate, carefully-designed change — out of scope for a sweep.
_COMMIT_MATERIAL_POLICY = (
    "\n\nCOMMIT POLICY (auto-reforecast — NON-NEGOTIABLE): committing the forecast "
    "UPDATE is a SEPARATE decision from recommending decision-card ACTION, and you "
    "MUST NOT conflate the two. The action threshold (e.g. 'act if P>=0.65') governs "
    "ONLY whether to ACT on the decision card; it does NOT govern whether to write "
    "down the forecast. So once you have re-collected fresh evidence and re-reasoned "
    "the number, MATERIALITY — not the action threshold — decides whether to commit. "
    "If your fresh estimate is a MATERIAL move versus the prior snapshot — |Δp| >= "
    "0.03 (3 percentage points) for a binary, or any genuine change for a "
    "distribution/categorical/first forecast — you MUST RECORD your current best "
    "estimate by COMMITTING the updated snapshot NOW (`forecast update <id> ...` / "
    "the `update_forecast` action), provided the saturation/commit gates pass "
    "(components, structured reasoning, panel where required). Do NOT stop at a "
    "sharpened preview and report 'No snapshot committed': a previewed-but-uncommitted "
    "material move is a FAILED update, not a completed one — the number lives only in "
    "your scratchpad and never reaches the scored ledger. ONLY when the move is "
    "MARGINAL/non-material (|Δp| < 0.03 AND the drivers are unchanged) may you leave "
    "it as a preview/recommendation and say so — a marginal re-pool is not worth a "
    "new scored snapshot. Either way, STATE the prior, your proposed number, the "
    "delta, and which branch (commit vs preview) you took and why."
)


def _stage_task(stage: str, *, commit_policy: str | None = None) -> str:
    tasks = {
        "parse": (
            "Audit whether the question is scoreable AND decision-relevant. Identify "
            "ambiguities, outcome-space issues, and missing resolution criteria. Then audit "
            "the decision card shown above: list any missing decision_owner, decision_deadline, "
            "action_threshold, or update_triggers. A forecast that does not inform a concrete "
            "decision is entertainment, not work — refuse to advance without a decision owner "
            "and at least one action threshold tied to the probability. Make update_triggers "
            "EXECUTABLE, not prose: a free-form threshold like 'rerun if CPI rises a lot' NEVER "
            "fires automatically. Each trigger that watches a numeric series MUST carry a "
            "`source_ref` (e.g. fred:CPIAUCSL, or polymarket:<slug> for a market probability), an "
            "`operator` (>, >=, <, <=, ==, !=), and a numeric `threshold`, so it fires a "
            "trigger_fired alert when the imported value crosses it — check them with the "
            "forecast_ledger check_update_triggers action or `forecast triggers <id>`. Keep the "
            "human-readable mechanism text too, but always add the machine-checkable triple where a "
            "trigger keys off a series or market you import. Return "
            "required clarifications before any forecast update."
        ),
        "research": (
            "Identify evidence gaps and propose timestamped evidence to collect. Distinguish facts, "
            "estimates, rumors, opinions, and assumptions. Do not update the probability. Pull data and "
            "market prices with the forecast_ledger import_source_evidence action (source_type fred/bls/"
            "eia/treasury/polymarket/kalshi/manifold/metaculus/rss/...), which is bounded and structured — "
            "do not write ad-hoc urllib/requests/curl fetches in the terminal, which hang until the command "
            "timeout and waste minutes per call. When the evidence is genuinely thin and your conviction is "
            "low, that is a signal to GATHER MORE, not to hedge later with a flat distribution: search the "
            "web/news (RSS adapter, or the browser for pages with no adapter) for expert opinion and analysis "
            "on THIS specific question, and reason explicitly from base rates and the closest analogous past "
            "episodes to separate uncertainty that is real from uncertainty that is merely unexamined. When a "
            "candidate stream is large, TRIAGE before importing: run forecast_ledger triage_label to classify "
            "readings relevant_interesting / relevant_uninteresting / irrelevant (keep/skim/skip) against the "
            "desk rubric, import only the material ones, and route auto-labels you dispute to operator review "
            "with triage_contested — so you reason over the signal, not the firehose."
        ),
        "base_rate": (
            "Propose reference classes with inclusion/exclusion criteria, base-rate estimates, "
            "uncertainty, and source requirements. When several reference classes compete, blend "
            "them by applicability with the forecast_ledger bayes action "
            "(bayes_action='blend_base_rates') instead of eyeballing a single class. For rare or "
            "high-stakes events, decompose the target into a causal chain "
            "P(A) · P(B|A) · P(C|A,B) and run bayes_action='conditional_chain' — it MUST be "
            "called with an `unconditional_estimate` (a separately-elicited gut/outside-view "
            "probability) so the chain product is sanity-checked instead of accepted on faith."
        ),
        "model": (
            "Suggest quantitative models or Bayesian updates that would improve the forecast. "
            "Specify inputs, parameters, diagnostics, and evidence cutoff requirements. Use the "
            "forecast_ledger bayes action for the auditable building blocks: 'evidence_weight' to "
            "turn a source into a likelihood ratio (separating reliability from relevance and "
            "discounting correlated/biased signal), 'poll_to_prob'/'polls' for poll→probability, "
            "'devig'/'combine_markets' to de-vig prediction markets, and 'evidence_cluster' to "
            "avoid double-counting sources that trace back to one signal. For a data-driven "
            "numeric question, build a deterministic quant Market Model as a scoreable component "
            "with the forecast_ledger build_model action (or `forecast model build <id>`): it "
            "researches, computes every statistic via the shared market_compute engine, and links "
            "back a model_run + reference class you can pool like any other input."
        ),
        "update": (
            "RE-RUN FIRST STEP (when a committed snapshot already exists — see 'Current Forecast' / "
            "'Re-run' in context): your MANDATORY first action is to RE-COLLECT FRESH EVIDENCE before "
            "re-estimating. Run `forecast refresh <id>` (re-fetches every watched source, imports the "
            "fresh values, re-pools, auto-commits) or `forecast refresh <id> --agent` for full "
            "re-reasoning. If the question has no watched sources yet, add them for the key data series "
            "(`forecast watch add`) and refresh, or do a fresh research pass (one `import_source_evidence` "
            "per driver). Do NOT re-estimate off the stale evidence already in the ledger, and do NOT "
            "carry the prior's components/tails forward unchanged — imports are deduped, so re-pulling an "
            "unchanged series is a no-op. (Skip this only for a genuinely first forecast with no prior "
            "snapshot.) THEN: "
            "Prepare a forecast update preview. Show previous probability, proposed probability, "
            "delta, component weights, key evidence, assumptions, calibration lessons used, and an "
            "as-of timestamp. Combine disagreeing sources with the Bayesian toolkit rather than a "
            "naive average: pool in log-odds space (forecast_ledger bayes_action='combine', "
            "method='log_odds_pool', with correlation_matrix='estimate' when sources overlap), or "
            "apply likelihood ratios to the prior (bayes_action='lr_update'). The same pooling is "
            "available natively via `forecast update --method log_odds_pool --extremize <f> "
            "--correlation estimate`. After moving the probability, decompose the change with "
            "bayes_action='forecast_diff' and stress-test it with bayes_action='sensitivity' so the "
            "update is auditable, not ad hoc. PERSIST THE POOL, not just prose: every saved snapshot "
            "that combines sources MUST pass `ensemble_components` — the actual list of "
            "{name, probability, weight, source} rows you pooled — on `update_forecast` (or "
            "`forecast update --component-json '[...]'`). Do not leave the components in a model_run "
            "or the rationale only; the structured field is what makes the pool auditable and is what "
            "`forecast refresh` re-pools next time. Capture every market/crowd reading AS A NUMERIC "
            "component with a stable `source` slug (e.g. {name:'markets', source:'polymarket:<slug>', "
            "probability:0.43, weight:2}) — even when you read the price off the browser because the "
            "adapter returns no liquidity — so the next refresh can match and update it. To RE-RUN an "
            "existing forecast whose sources are watched, prefer `forecast refresh <id>` (pulls latest "
            "readings, re-pools, auto-commits) or `forecast refresh <id> --agent` for full "
            "re-reasoning, instead of redoing the imports by hand. "
            "Reason PATH-FIRST before you commit. Start from the anchor: what is the status-quo "
            "outcome if nothing changes, and how much can change before resolution (short horizon -> "
            "the status quo dominates; long horizon -> more drift and a wider distribution)? Then "
            "trace the causal PATH to each outcome and price its links — the probability is the "
            "weight of the path that must ACTUALLY occur, not the salience of a headline, and a path "
            "with one weak link cannot carry heavy mass. The three structured reasoning fields ARE "
            "these paths, not a loose list of pros and cons. Every saved snapshot MUST include "
            "three structured reasoning fields: `reasons_up` (the concrete links on the path that drives the probability HIGHER — what must happen, in order), "
            "`reasons_down` (the links on the path that drives it LOWER), and "
            "`change_my_mind` (the specific observation/data — usually the weakest load-bearing link — whose failure would force a material update). "
            "These prevent narrative collapse — pass them as repeated --reason-up / --reason-down / "
            "--change-my-mind flags, or as `reasons_up`/`reasons_down`/`change_my_mind` arrays in "
            "the agent tool. On the CLI, `--require-structured-reasoning` enforces this; on "
            "`update_forecast`, the boolean `require_structured_reasoning` has the same effect. "
            "For high-impact questions or the first forecast on a question, run a forecast PANEL: "
            "use the forecast_ledger `panel_perspectives` action to fetch the 5 constrained "
            "framings (outside, inside, market, red_team, sanity), produce one estimate per "
            "perspective silently, then call `record_panel` to aggregate via trimmed geomean of "
            "odds (default trim=1) and attach the panel artifact to the snapshot. The CLI "
            "equivalent is `forecast update <id> --panel-estimates-json '[...]' "
            "--panel-trim 1`. For a HIGH-IMPACT live forecast this panel is REQUIRED: the "
            "update is refused unless you link a panel (inline --panel-estimates-json, or "
            "--panel-run-ref / `panel_run_ref` to an existing run) or record why you skipped "
            "it (--panel-skipped-reason / `panel_skipped_reason`). Lower-impact first forecasts "
            "are only nudged, and exploratory snapshots are exempt. "
            "FINALLY, before you commit, run a CONVICTION REVIEW of your own number — "
            "under-confidence is scored exactly like over-confidence, so audit for it as hard. "
            "(a) Tail discipline: every option or bucket that holds material mass must have a "
            "nameable path to happening; mass you cannot justify is miscalibration — move it onto "
            "the outcomes the evidence supports (a two-way contest is not a seven-way one; a "
            "distribution that hedges across no-path tails will score worse than a sharp, correct "
            "one). For a CATEGORICAL forecast, do not forecast from the answer choices — forecast "
            "from the causal paths: run the forecast_ledger `tail_audit` action (or `forecast "
            "tail-audit --dist '{...}'`) BEFORE you commit. It demands a named path for every "
            "outcome holding >=0.5% and flags UNEARNED tail mass — a named-but-non-live option "
            "(a candidate with no poll, ballot line, or money) given a tail purely because it "
            "appears in the outcome set is outcome-space anchoring, the classic junior error. "
            "Name the mechanism for each material outcome (pass `outcome_paths` / repeated "
            "--outcome-path 'Outcome=path'), or compress that mass onto outcomes with a live "
            "path; commit with `require_outcome_paths` to make the gate hard. The audit also "
            "compares your distribution to a deliberately simple NULL MODEL (any no-path outcome "
            "floored near zero): if your no-path tail is several times fatter than the null's, "
            "either justify the extra mass with a mechanism or fall back to the simple model. "
            "Likewise do not let a thin or stale market inflate a tail — a price nobody is "
            "defending is not strong evidence: run the forecast_ledger `market_quality` action "
            "(or `forecast market-quality --markets '[...]'`) to stratify each market reading by "
            "liquidity + recency into an advisory weight in [0,1], and multiply that weight into "
            "the market component's `weight` in `ensemble_components` (a stale market at 0.25 "
            "should pool at a quarter of a liquid one) — never drop a market silently; record the "
            "discounted weight. (b) Leader "
            "suppression: is your top outcome held BELOW what the polls, markets, "
            "base rates, and fundamentals actually imply? If so, sharpen it. (c) Market-mirroring: "
            "did you form an INDEPENDENT view and state where you diverge, or did you just settle "
            "just inside the market? Commit your view, not a copy of the crowd. If conviction is "
            "genuinely low because the evidence is thin, do NOT diffuse the distribution to hedge — "
            "go back to the research stage and GET evidence (search for expert opinion/analysis, "
            "reason from base rates and analogous past episodes) until the real uncertainty is "
            "isolated. On a RE-RUN specifically, re-audit the PRIOR's tails against the FRESH evidence "
            "and the now-shorter time-to-close — do not inherit a hedge you set when the evidence was "
            "thinner; as resolution nears and evidence accumulates, conviction should generally RISE "
            "and the distribution CONCENTRATE, not perpetuate stale tail mass. Sharpen, then commit "
            "with conviction. "
            "After a successful commit, `update_forecast` returns a `saturation` block — the "
            "0-100 score the commit scored plus any WARN advisories (checks that passed the gate "
            "but flag a gap): read it, and if the score is low or advisories remain, remediate "
            "them and re-commit rather than leaving the forecast under-saturated."
        ),
        "resolve": (
            "Check whether the resolution criteria are satisfied. Propose resolution status, source snapshot needs, "
            "and whether the outcome is scoreable. Do not score disputed or unconfirmed resolutions."
        ),
        "postmortem": (
            "Diagnose the resolved forecast. Compare expected vs actual outcome, missed or "
            "overweighted evidence, base-rate error, inside-view error, resolution error, and "
            "reusable calibration lesson. Assign a `failure_class` so the domain error profile "
            "can aggregate the failure mode: one of base_rate, inside_view, definition, timing, "
            "aggregation, motivated_reasoning, tail, noise, other. 'Noise' means the miss was "
            "within expected error of a well-calibrated forecast; everything else is a reusable "
            "lesson. Diagnose CALIBRATION DIRECTION explicitly: if the realized outcome was one "
            "you had held below the evidence, or you spread mass across tails that had no path, "
            "that is UNDER-confidence (classify it `tail`) — and the lesson is to start sharper "
            "next time in this domain, not to hedge wider. Track the direction of your misses so a "
            "systematic under- or over-confidence bias becomes a domain lesson future forecasts "
            "inherit. Pass `--failure-class <name>` to the CLI or `failure_class` to the "
            "forecast_ledger postmortem action."
        ),
        "self_check": (
            "Inspect stale beliefs, upcoming close/resolution dates, invalidated assumptions, and domain error patterns. "
            "Use the forecast_ledger doctor_report action for tester or benchmark readiness checks, and create review "
            "recommendations without silently changing probabilities or claiming live superiority."
        ),
    }
    task = tasks[stage]
    if stage == "update" and commit_policy == "commit_material":
        task = task + _COMMIT_MATERIAL_POLICY
    return task
