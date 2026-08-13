"""Durable source-change handoff and forecast operational task queue."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import uuid
from dataclasses import asdict
from datetime import timedelta
from functools import lru_cache
from math import exp
from pathlib import Path
from typing import Any, Callable

from forecasting.models import (
    LedgerNotFoundError,
    ValidationError,
    json_dumps,
    json_loads,
    parse_timestamp,
    timestamp_to_datetime,
    utc_now_iso,
)


SOURCE_EVENT_STATES = (
    "detected",
    "triaged",
    "claimed",
    "researched",
    "estimated",
    "proposed",
    "committed",
    "rejected",
    "reconciled",
    "failed",
    "superseded",
)


@lru_cache(maxsize=1)
def _runtime_code_identity() -> tuple[str, bool]:
    """Return the deployed commit and whether its checkout has local changes."""
    explicit = os.getenv("SUPERFORECASTING_AGENT_CODE_REVISION") or os.getenv("GITHUB_SHA")
    if explicit:
        return explicit.strip(), False
    root = Path(__file__).resolve().parents[2]
    try:
        revision = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        ).stdout.strip()
        dirty = bool(
            subprocess.run(
                ["git", "status", "--porcelain", "--untracked-files=normal"],
                cwd=root,
                check=True,
                capture_output=True,
                text=True,
                timeout=2,
            ).stdout.strip()
        )
        return revision or "unknown", dirty
    except (OSError, subprocess.SubprocessError):
        return "unknown", False

ESTIMATION_ARTIFACT_FIELDS = (
    "prior_probability",
    "evidence_updates",
    "raw_posterior",
    "ensemble_components",
    "panel_result",
    "proposed_probability",
    "materiality",
    "evidence_cutoff",
    "change_my_mind",
    "guardrail_results",
)


def initialize_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS source_change_events (
            id TEXT PRIMARY KEY,
            question_id TEXT REFERENCES forecast_questions(id) ON DELETE CASCADE,
            watched_source_id TEXT NOT NULL REFERENCES watched_sources(id) ON DELETE CASCADE,
            prior_source_snapshot_id TEXT REFERENCES source_snapshots(id) ON DELETE SET NULL,
            new_source_snapshot_id TEXT NOT NULL REFERENCES source_snapshots(id) ON DELETE CASCADE,
            prior_forecast_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
            detected_at TEXT NOT NULL,
            source_observed_at TEXT NOT NULL,
            old_state TEXT NOT NULL DEFAULT '{}',
            new_state TEXT NOT NULL DEFAULT '{}',
            materiality TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending',
            state TEXT NOT NULL DEFAULT 'detected',
            claim_owner TEXT,
            claim_expires_at TEXT,
            proposal_id TEXT REFERENCES forecast_update_proposals(id) ON DELETE SET NULL,
            forecast_snapshot_id TEXT REFERENCES forecast_snapshots(forecast_id) ON DELETE SET NULL,
            disposition TEXT,
            error TEXT,
            metadata TEXT NOT NULL DEFAULT '{}'
        );

        CREATE UNIQUE INDEX IF NOT EXISTS uq_source_change_event_snapshot
            ON source_change_events(watched_source_id, new_source_snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_source_change_events_pending
            ON source_change_events(status, detected_at);

        CREATE TABLE IF NOT EXISTS source_change_event_transitions (
            id TEXT PRIMARY KEY,
            source_change_event_id TEXT NOT NULL
                REFERENCES source_change_events(id) ON DELETE CASCADE,
            from_state TEXT,
            to_state TEXT NOT NULL,
            actor TEXT NOT NULL,
            reason TEXT,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_source_event_transitions
            ON source_change_event_transitions(source_change_event_id, created_at);

        CREATE TABLE IF NOT EXISTS operational_tasks (
            id TEXT PRIMARY KEY,
            task_type TEXT NOT NULL,
            lane TEXT NOT NULL DEFAULT 'deterministic',
            question_id TEXT REFERENCES forecast_questions(id) ON DELETE CASCADE,
            source_change_event_id TEXT REFERENCES source_change_events(id) ON DELETE CASCADE,
            alert_id TEXT REFERENCES alert_events(id) ON DELETE SET NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            priority INTEGER NOT NULL DEFAULT 50,
            utility_score REAL NOT NULL DEFAULT 0,
            utility_components TEXT NOT NULL DEFAULT '{}',
            available_at TEXT NOT NULL,
            due_at TEXT,
            lease_owner TEXT,
            lease_expires_at TEXT,
            claimed_at TEXT,
            completed_at TEXT,
            escalation_owner TEXT,
            escalated_at TEXT,
            attempt_count INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 5,
            idempotency_key TEXT NOT NULL UNIQUE,
            disposition TEXT,
            result TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_operational_tasks_ready
            ON operational_tasks(status, lane, priority, available_at);

        DROP TRIGGER IF EXISTS close_pending_task_when_alert_closed;
        CREATE TRIGGER IF NOT EXISTS close_pending_task_when_alert_closed
        AFTER UPDATE OF acknowledged_at ON alert_events
        WHEN OLD.acknowledged_at IS NULL AND NEW.acknowledged_at IS NOT NULL
        BEGIN
            INSERT OR IGNORE INTO source_change_event_transitions (
                id, source_change_event_id, from_state, to_state, actor, reason, created_at
            )
            SELECT 'scet_alert_' || event.id, event.id, event.state, 'reconciled',
                   'alert-lifecycle', 'linked alert closed elsewhere', NEW.acknowledged_at
            FROM source_change_events AS event
            JOIN operational_tasks AS task ON task.source_change_event_id = event.id
            WHERE task.alert_id = NEW.id AND event.status IN ('pending', 'failed');

            UPDATE source_change_events
            SET status = 'processed', state = 'reconciled',
                disposition = COALESCE(disposition, 'alert_closed_elsewhere'),
                claim_owner = NULL, claim_expires_at = NULL, error = NULL
            WHERE status IN ('pending', 'failed') AND id IN (
                SELECT source_change_event_id FROM operational_tasks
                WHERE alert_id = NEW.id AND source_change_event_id IS NOT NULL
            );

            UPDATE operational_tasks
            SET status = 'completed', completed_at = NEW.acknowledged_at,
                disposition = COALESCE(disposition, 'alert_closed_elsewhere'),
                lease_owner = NULL, lease_expires_at = NULL,
                updated_at = NEW.acknowledged_at
            WHERE alert_id = NEW.id
              AND status IN ('pending', 'awaiting_human', 'failed', 'dead_letter');
        END;

        CREATE TABLE IF NOT EXISTS operational_task_attempts (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES operational_tasks(id) ON DELETE CASCADE,
            lane TEXT NOT NULL,
            owner TEXT NOT NULL,
            claimed_at TEXT NOT NULL,
            finished_at TEXT,
            outcome TEXT,
            error TEXT,
            model_calls INTEGER NOT NULL DEFAULT 0,
            source_calls INTEGER NOT NULL DEFAULT 0,
            input_tokens INTEGER NOT NULL DEFAULT 0,
            output_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd REAL NOT NULL DEFAULT 0,
            cost_status TEXT,
            cost_source TEXT,
            latency_ms INTEGER NOT NULL DEFAULT 0,
            code_revision TEXT,
            worktree_dirty INTEGER NOT NULL DEFAULT 0
        );

        CREATE INDEX IF NOT EXISTS idx_operational_attempts_lane_time
            ON operational_task_attempts(lane, claimed_at);

        CREATE TABLE IF NOT EXISTS operational_lane_policies (
            lane TEXT PRIMARY KEY,
            daily_claim_budget INTEGER NOT NULL,
            slo_minutes INTEGER NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS automation_budget_leases (
            bucket TEXT PRIMARY KEY,
            lease_owner TEXT,
            lease_expires_at TEXT,
            last_run_at TEXT,
            last_spent INTEGER NOT NULL DEFAULT 0,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS source_token_buckets (
            bucket TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            account_key TEXT NOT NULL,
            tokens REAL NOT NULL,
            capacity REAL NOT NULL,
            refill_per_second REAL NOT NULL,
            updated_at TEXT NOT NULL,
            granted_count INTEGER NOT NULL DEFAULT 0,
            denied_count INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS operational_utility_models (
            id TEXT PRIMARY KEY,
            created_at TEXT NOT NULL,
            status TEXT NOT NULL,
            coefficients TEXT NOT NULL,
            sample_size INTEGER NOT NULL,
            metrics TEXT NOT NULL DEFAULT '{}'
        );
        """
    )
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(operational_tasks)")}
    if "claimed_at" not in columns:
        conn.execute("ALTER TABLE operational_tasks ADD COLUMN claimed_at TEXT")
    if "completed_at" not in columns:
        conn.execute("ALTER TABLE operational_tasks ADD COLUMN completed_at TEXT")
    if "utility_score" not in columns:
        conn.execute("ALTER TABLE operational_tasks ADD COLUMN utility_score REAL NOT NULL DEFAULT 0")
    if "utility_components" not in columns:
        conn.execute("ALTER TABLE operational_tasks ADD COLUMN utility_components TEXT NOT NULL DEFAULT '{}'")
    if "escalation_owner" not in columns:
        conn.execute("ALTER TABLE operational_tasks ADD COLUMN escalation_owner TEXT")
    if "escalated_at" not in columns:
        conn.execute("ALTER TABLE operational_tasks ADD COLUMN escalated_at TEXT")
    event_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(source_change_events)")
    }
    if "state" not in event_columns:
        conn.execute(
            "ALTER TABLE source_change_events ADD COLUMN state TEXT NOT NULL DEFAULT 'detected'"
        )
        conn.execute(
            """
            UPDATE source_change_events SET state = CASE
                WHEN status = 'processed' THEN 'reconciled'
                WHEN status = 'failed' THEN 'failed'
                ELSE 'detected'
            END
            """
        )
    conn.execute(
        """
        INSERT OR IGNORE INTO source_change_event_transitions (
            id, source_change_event_id, from_state, to_state, actor, reason, created_at
        )
        SELECT 'scet_migrated_' || id, id, NULL, state, 'schema-migration',
               'backfilled event state', detected_at
        FROM source_change_events
        WHERE NOT EXISTS (
            SELECT 1 FROM source_change_event_transitions t
            WHERE t.source_change_event_id = source_change_events.id
        )
        """
    )
    attempt_columns = {
        row["name"] for row in conn.execute("PRAGMA table_info(operational_task_attempts)")
    }
    for name, declaration in (
        ("model_calls", "INTEGER NOT NULL DEFAULT 0"),
        ("source_calls", "INTEGER NOT NULL DEFAULT 0"),
        ("input_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("output_tokens", "INTEGER NOT NULL DEFAULT 0"),
        ("cost_usd", "REAL NOT NULL DEFAULT 0"),
        ("cost_status", "TEXT"),
        ("cost_source", "TEXT"),
        ("latency_ms", "INTEGER NOT NULL DEFAULT 0"),
        ("code_revision", "TEXT"),
        ("worktree_dirty", "INTEGER NOT NULL DEFAULT 0"),
    ):
        if name not in attempt_columns:
            conn.execute(
                f"ALTER TABLE operational_task_attempts ADD COLUMN {name} {declaration}"
            )
    conn.executemany(
        """
        INSERT OR IGNORE INTO operational_lane_policies
            (lane, daily_claim_budget, slo_minutes, enabled)
        VALUES (?, ?, ?, 1)
        """,
        [
            ("deterministic_critical", 10000, 15),
            ("urgent_forecast", 500, 60),
            ("normal_reforecast", 200, 1440),
            ("maintenance", 50, 4320),
        ],
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO operational_tasks (
            id, task_type, lane, question_id, alert_id, status, priority,
            utility_score, utility_components, available_at, due_at,
            idempotency_key, created_at, updated_at
        )
        SELECT 'ot_alert_' || a.id, 'resolve_warning', 'urgent_forecast',
               CASE WHEN a.scope_type = 'question' AND EXISTS (
                    SELECT 1 FROM forecast_questions q WHERE q.id = a.scope_ref
               ) THEN a.scope_ref ELSE NULL END,
               a.id, 'pending', 100, 0, '{"model_version":"utility-v1"}',
               a.created_at, strftime('%Y-%m-%dT%H:%M:%SZ', a.created_at, '+1 hour'),
               'warning:' || a.id, a.created_at, a.created_at
        FROM alert_events a
        WHERE a.acknowledged_at IS NULL AND a.severity IN ('critical', 'high')
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO source_change_event_transitions (
            id, source_change_event_id, from_state, to_state, actor, reason, created_at
        )
        SELECT 'scet_alert_' || event.id, event.id, event.state, 'reconciled',
               'schema-migration', 'linked alert was already closed',
               COALESCE(alert.acknowledged_at, event.detected_at)
        FROM source_change_events AS event
        JOIN operational_tasks AS task ON task.source_change_event_id = event.id
        JOIN alert_events AS alert ON alert.id = task.alert_id
        WHERE event.status IN ('pending', 'failed') AND alert.acknowledged_at IS NOT NULL
        """
    )
    conn.execute(
        """
        UPDATE source_change_events
        SET status = 'processed', state = 'reconciled',
            disposition = COALESCE(disposition, 'alert_closed_elsewhere'),
            claim_owner = NULL, claim_expires_at = NULL, error = NULL
        WHERE status IN ('pending', 'failed') AND id IN (
            SELECT task.source_change_event_id
            FROM operational_tasks AS task
            JOIN alert_events AS alert ON alert.id = task.alert_id
            WHERE task.source_change_event_id IS NOT NULL
              AND alert.acknowledged_at IS NOT NULL
        )
        """
    )
    conn.execute(
        """
        UPDATE operational_tasks
        SET lane = 'urgent_forecast', priority = 100
        WHERE alert_id IN (
            SELECT id FROM alert_events
            WHERE acknowledged_at IS NULL AND severity IN ('critical', 'high')
        ) AND status IN ('pending', 'leased')
        """
    )
    conn.execute(
        """
        UPDATE operational_tasks
        SET status = 'awaiting_human',
            escalation_owner = COALESCE(
                (SELECT NULLIF(owner, '') FROM forecast_questions
                 WHERE id = operational_tasks.question_id),
                'human:forecast-duty'
            ),
            escalated_at = COALESCE(escalated_at, completed_at, updated_at),
            completed_at = NULL
        WHERE task_type = 'resolve_warning' AND status = 'completed'
          AND alert_id IN (
              SELECT id FROM alert_events
              WHERE acknowledged_at IS NULL AND severity IN ('critical', 'high')
          )
          AND NOT EXISTS (
              SELECT 1 FROM operational_tasks AS sibling
              WHERE sibling.alert_id = operational_tasks.alert_id
                AND sibling.id != operational_tasks.id
                AND (sibling.status IN ('pending', 'leased', 'awaiting_human')
                     OR sibling.escalation_owner IS NOT NULL)
          )
        """
    )
    # Older warning workers re-polled whole questions after a durable successful
    # observation had already been captured. A transient fetch failure then marked
    # every pending event for the question failed without ever claiming its task.
    # Recover only that unmistakable shape; genuine failed observations stay failed.
    conn.execute(
        """
        INSERT OR IGNORE INTO source_change_event_transitions (
            id, source_change_event_id, from_state, to_state, actor, reason, created_at
        )
        SELECT 'scet_recovered_' || event.id, event.id, event.state, 'detected',
               'schema-migration', 'recovered successful immutable observation from redundant recheck failure',
               strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        FROM source_change_events AS event
        JOIN operational_tasks AS task ON task.source_change_event_id = event.id
        JOIN forecast_questions AS question ON question.id = event.question_id
        LEFT JOIN alert_events AS alert ON alert.id = task.alert_id
        WHERE event.status = 'failed' AND event.disposition = 'source_failure'
          AND json_extract(event.new_state, '$.status') = 'success'
          AND task.status IN ('failed', 'dead_letter')
          AND task.attempt_count = 0
          AND question.status = 'active'
          AND (alert.id IS NULL OR alert.acknowledged_at IS NULL)
        """
    )
    conn.execute(
        """
        UPDATE source_change_events
        SET status = 'pending', state = 'detected', disposition = NULL, error = NULL,
            claim_owner = NULL, claim_expires_at = NULL
        WHERE status = 'failed' AND disposition = 'source_failure'
          AND json_extract(new_state, '$.status') = 'success'
          AND id IN (
              SELECT task.source_change_event_id
              FROM operational_tasks AS task
              JOIN forecast_questions AS question ON question.id = task.question_id
              LEFT JOIN alert_events AS alert ON alert.id = task.alert_id
              WHERE task.status IN ('failed', 'dead_letter') AND task.attempt_count = 0
                AND question.status = 'active'
                AND (alert.id IS NULL OR alert.acknowledged_at IS NULL)
          )
        """
    )
    # Collapse legacy fan-out failures from one question refresh cycle into one
    # batch failure plus terminal child records. The old worker attached the same
    # aggregate error to every source event, which inflated production failures.
    conn.execute(
        """
        WITH duplicate_groups AS (
            SELECT question_id, detected_at, COALESCE(error, '') AS error_key
            FROM source_change_events
            WHERE status = 'failed'
              AND disposition IN ('source_failure', 'source_failure_batch')
            GROUP BY question_id, detected_at, COALESCE(error, '')
            HAVING COUNT(*) > 1
        )
        UPDATE source_change_events
        SET disposition = 'source_failure_batch'
        WHERE status = 'failed' AND disposition = 'source_failure'
          AND id = (
              SELECT MIN(candidate.id) FROM source_change_events AS candidate
              WHERE candidate.question_id = source_change_events.question_id
                AND candidate.detected_at = source_change_events.detected_at
                AND COALESCE(candidate.error, '') = COALESCE(source_change_events.error, '')
                AND candidate.status = 'failed'
                AND candidate.disposition = 'source_failure'
          )
          AND EXISTS (
              SELECT 1 FROM duplicate_groups AS batch
              WHERE batch.question_id = source_change_events.question_id
                AND batch.detected_at = source_change_events.detected_at
                AND batch.error_key = COALESCE(source_change_events.error, '')
          )
        """
    )
    conn.execute(
        """
        WITH ranked AS (
            SELECT id,
                   FIRST_VALUE(id) OVER (
                       PARTITION BY question_id, detected_at, COALESCE(error, '')
                       ORDER BY id
                   ) AS parent_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY question_id, detected_at, COALESCE(error, '')
                       ORDER BY id
                   ) AS position,
                   COUNT(*) OVER (
                       PARTITION BY question_id, detected_at, COALESCE(error, '')
                   ) AS batch_size
            FROM source_change_events
            WHERE status = 'failed'
              AND disposition IN ('source_failure', 'source_failure_batch')
        )
        INSERT OR IGNORE INTO source_change_event_transitions (
            id, source_change_event_id, from_state, to_state, actor, reason, created_at
        )
        SELECT 'scet_failure_child_' || id, id, 'failed', 'reconciled',
               'schema-migration', 'collapsed duplicate batch source failure',
               strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
        FROM ranked WHERE batch_size > 1 AND position > 1
        """
    )
    conn.execute(
        """
        UPDATE source_change_events AS parent
        SET disposition = 'source_failure_batch'
        WHERE parent.status = 'failed' AND parent.disposition = 'source_failure'
          AND EXISTS (
              SELECT 1 FROM source_change_events AS child
              WHERE child.disposition = 'source_failure_child'
                AND json_extract(child.metadata, '$.source_failure_parent_id') = parent.id
          )
        """
    )
    conn.execute(
        """
        WITH ranked AS (
            SELECT id,
                   FIRST_VALUE(id) OVER (
                       PARTITION BY question_id, detected_at, COALESCE(error, '')
                       ORDER BY id
                   ) AS parent_id,
                   ROW_NUMBER() OVER (
                       PARTITION BY question_id, detected_at, COALESCE(error, '')
                       ORDER BY id
                   ) AS position,
                   COUNT(*) OVER (
                       PARTITION BY question_id, detected_at, COALESCE(error, '')
                   ) AS batch_size
            FROM source_change_events
            WHERE status = 'failed'
              AND disposition IN ('source_failure', 'source_failure_batch')
        )
        UPDATE source_change_events
        SET status = 'processed', state = 'reconciled',
            disposition = 'source_failure_child', error = NULL,
            metadata = json_set(
                COALESCE(metadata, '{}'), '$.source_failure_parent_id',
                (SELECT parent_id FROM ranked WHERE ranked.id = source_change_events.id)
            )
        WHERE id IN (
            SELECT id FROM ranked WHERE batch_size > 1 AND position > 1
        )
        """
    )
    conn.execute(
        """
        UPDATE operational_tasks
        SET status = 'pending', lane = 'deterministic_critical', disposition = NULL,
            error = NULL, completed_at = NULL, lease_owner = NULL,
            lease_expires_at = NULL, available_at = created_at, updated_at = created_at
        WHERE status IN ('failed', 'dead_letter') AND attempt_count = 0
          AND source_change_event_id IN (
              SELECT id FROM source_change_events
              WHERE status = 'pending' AND state = 'detected' AND disposition IS NULL
          )
        """
    )
    # Remaining attempt_count=0 source failures are genuine historical
    # observations (the recoverable successful-event shape above is pending
    # again). Keep their failed source events as the audit record while
    # archiving duplicate task rows out of the worker-failure view.
    conn.execute(
        """
        UPDATE operational_tasks
        SET status = 'completed', disposition = 'historical_source_failure_recorded',
            completed_at = COALESCE(completed_at, updated_at),
            result = json_set(COALESCE(result, '{}'), '$.historical_error', error),
            lease_owner = NULL, lease_expires_at = NULL
        WHERE status = 'failed' AND disposition = 'source_failure'
          AND attempt_count = 0
        """
    )
    conn.execute(
        """
        UPDATE operational_tasks
        SET status = 'completed',
            completed_at = COALESCE(completed_at, (
                SELECT acknowledged_at FROM alert_events WHERE id = operational_tasks.alert_id
            )),
            disposition = COALESCE(disposition, 'alert_closed_elsewhere'),
            lease_owner = NULL, lease_expires_at = NULL,
            updated_at = COALESCE((
                SELECT acknowledged_at FROM alert_events WHERE id = operational_tasks.alert_id
            ), updated_at)
        WHERE status IN ('pending', 'awaiting_human', 'failed', 'dead_letter') AND alert_id IN (
            SELECT id FROM alert_events WHERE acknowledged_at IS NOT NULL
        )
        """
    )
    conn.execute(
        """
        UPDATE operational_task_attempts
        SET finished_at = COALESCE(finished_at, strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
            outcome = COALESCE(outcome, 'human_escalation_required'),
            error = COALESCE(error, 'worker execution stopped after human escalation')
        WHERE finished_at IS NULL AND task_id IN (
            SELECT id FROM operational_tasks
            WHERE disposition = 'human_escalation_required'
        )
        """
    )
    conn.execute(
        """
        UPDATE operational_tasks
        SET status = 'awaiting_human', lease_owner = NULL, lease_expires_at = NULL,
            updated_at = COALESCE(escalated_at, updated_at)
        WHERE disposition = 'human_escalation_required'
          AND status IN ('pending', 'leased')
        """
    )


def calculate_task_utility(
    ledger,
    *,
    question_id: str | None,
    task_type: str,
    watch: dict[str, Any] | None = None,
    now: str | None = None,
    expected_cost_usd: float | None = None,
) -> dict[str, Any]:
    """Return the versioned impact×urgency×movement×VOI÷cost queue score."""
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    question = ledger.get_question(question_id) if question_id else None
    impact = {
        "critical": 1.0,
        "high": 0.85,
        "medium": 0.55,
        "low": 0.25,
    }.get(str(getattr(question, "impact", None) or "medium").lower(), 0.55)
    deadline = None
    if question:
        deadline = timestamp_to_datetime(
            question.decision_deadline or question.close_time or question.resolution_time
        )
    if deadline is None:
        urgency = 0.4
        resolution_proximity = 0.4
    else:
        days = max((deadline - now_dt).total_seconds() / 86400, 0.0)
        urgency = 1.0 / (1.0 + days / 14.0)
        resolution_proximity = 1.0 / (1.0 + days / 30.0)
    role = str((watch or {}).get("role") or "")
    information_value = {
        "resolver": 1.0,
        "official_primary": 0.95,
        "leading_indicator": 0.8,
        "market_price": 0.75,
        "consensus": 0.7,
        "background_context": 0.35,
    }.get(role, 0.6)
    movement_probability = 0.9 if task_type == "finalize_resolution" else 0.65
    if role in {"resolver", "official_primary"}:
        movement_probability = max(movement_probability, 0.85)
    cost = max(
        float(expected_cost_usd if expected_cost_usd is not None else 0.02),
        0.001,
    )
    if task_type == "finalize_resolution":
        cost = max(float(expected_cost_usd or 0.001), 0.001)
    raw = (
        impact
        * urgency
        * movement_probability
        * information_value
        * resolution_proximity
        / cost
    )
    components = {
        "model_version": "utility-v1",
        "impact": round(impact, 6),
        "urgency": round(urgency, 6),
        "movement_probability": round(movement_probability, 6),
        "information_value": round(information_value, 6),
        "resolution_proximity": round(resolution_proximity, 6),
        "expected_cost_usd": round(cost, 6),
    }
    calibrated = _active_utility_model(ledger)
    if calibrated:
        score = 100 * _utility_probability(components, calibrated["coefficients"])
        components["model_version"] = calibrated["id"]
    else:
        score = raw
    return {"score": round(score, 6), "components": components}


def utility_backtest(ledger) -> dict[str, Any]:
    """Evaluate utility ranking against completed useful task outcomes."""
    useful = {"proposed", "auto_committed", "resolved_by_resolution"}
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT utility_score, disposition, utility_components
            FROM operational_tasks WHERE status = 'completed'
            ORDER BY utility_score DESC
            """
        ).fetchall()
    labelled = [
        (float(row["utility_score"] or 0), row["disposition"] in useful)
        for row in rows
    ]
    midpoint = max(len(labelled) // 2, 1)
    top, bottom = labelled[:midpoint], labelled[midpoint:]
    positives = [score for score, outcome in labelled if outcome]
    negatives = [score for score, outcome in labelled if not outcome]
    pairs = [(positive, negative) for positive in positives for negative in negatives]
    concordance = (
        sum(1.0 if positive > negative else 0.5 if positive == negative else 0.0 for positive, negative in pairs)
        / len(pairs)
        if pairs
        else None
    )
    return {
        "model_version": "utility-v1",
        "sample_size": len(labelled),
        "useful_outcomes": len(positives),
        "top_half_useful_rate": (
            round(sum(outcome for _, outcome in top) / len(top), 6) if top else None
        ),
        "bottom_half_useful_rate": (
            round(sum(outcome for _, outcome in bottom) / len(bottom), 6)
            if bottom
            else None
        ),
        "pairwise_concordance": round(concordance, 6) if concordance is not None else None,
        "calibration_ready": len(labelled) >= 20 and len(positives) >= 5 and len(negatives) >= 5,
    }


def calibrate_task_utility(
    ledger,
    *,
    min_samples: int = 20,
    iterations: int = 400,
) -> dict[str, Any]:
    """Fit and activate a small logistic utility model from completed outcomes."""
    useful = {"proposed", "auto_committed", "resolved_by_resolution"}
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT disposition, utility_components FROM operational_tasks
            WHERE status = 'completed' AND utility_components != '{}'
            """
        ).fetchall()
    samples = [
        (
            _utility_features(json_loads(row["utility_components"], {})),
            1.0 if row["disposition"] in useful else 0.0,
        )
        for row in rows
    ]
    positives = sum(label for _, label in samples)
    negatives = len(samples) - positives
    if len(samples) < max(int(min_samples), 2) or positives < 2 or negatives < 2:
        return {
            "activated": False,
            "sample_size": len(samples),
            "positive_outcomes": int(positives),
            "negative_outcomes": int(negatives),
            "reason": "insufficient mixed completed outcomes",
        }
    names = list(_utility_features({}))
    intercept = 0.0
    weights = {name: 0.0 for name in names}
    rate = 0.25
    for _ in range(max(int(iterations), 1)):
        intercept_gradient = 0.0
        gradients = {name: 0.0 for name in names}
        for features, label in samples:
            prediction = _sigmoid(
                intercept + sum(weights[name] * features[name] for name in names)
            )
            error = prediction - label
            intercept_gradient += error
            for name in names:
                gradients[name] += error * features[name]
        intercept -= rate * intercept_gradient / len(samples)
        for name in names:
            weights[name] -= rate * (
                gradients[name] / len(samples) + 0.01 * weights[name]
            )
    coefficients = {"intercept": intercept, **weights}
    predictions = [
        (_utility_probability_from_features(features, coefficients), bool(label))
        for features, label in samples
    ]
    positives_scored = [score for score, label in predictions if label]
    negatives_scored = [score for score, label in predictions if not label]
    pairs = [
        (positive, negative)
        for positive in positives_scored
        for negative in negatives_scored
    ]
    concordance = sum(
        1.0 if positive > negative else 0.5 if positive == negative else 0.0
        for positive, negative in pairs
    ) / len(pairs)
    model_id = f"utility-calibrated-{uuid.uuid4().hex[:8]}"
    stamp = utc_now_iso()
    metrics = {"pairwise_concordance": round(concordance, 6)}
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE operational_utility_models SET status = 'retired' WHERE status = 'active'"
        )
        conn.execute(
            """
            INSERT INTO operational_utility_models (
                id, created_at, status, coefficients, sample_size, metrics
            ) VALUES (?, ?, 'active', ?, ?, ?)
            """,
            (model_id, stamp, json_dumps(coefficients), len(samples), json_dumps(metrics)),
        )
        pending = conn.execute(
            "SELECT id, utility_components FROM operational_tasks WHERE status = 'pending'"
        ).fetchall()
        for row in pending:
            components = json_loads(row["utility_components"], {})
            components["model_version"] = model_id
            conn.execute(
                "UPDATE operational_tasks SET utility_score = ?, utility_components = ? WHERE id = ?",
                (
                    round(100 * _utility_probability(components, coefficients), 6),
                    json_dumps(components),
                    row["id"],
                ),
            )
    return {
        "activated": True,
        "model_id": model_id,
        "sample_size": len(samples),
        "coefficients": coefficients,
        "metrics": metrics,
    }


def _active_utility_model(ledger) -> dict[str, Any] | None:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM operational_utility_models WHERE status = 'active' "
            "ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return None
    data = dict(row)
    data["coefficients"] = json_loads(data["coefficients"], {})
    data["metrics"] = json_loads(data["metrics"], {})
    return data


def _utility_features(components: dict[str, Any]) -> dict[str, float]:
    cost = max(float(components.get("expected_cost_usd") or 0.02), 0.001)
    return {
        "impact": float(components.get("impact") or 0),
        "urgency": float(components.get("urgency") or 0),
        "movement_probability": float(components.get("movement_probability") or 0),
        "information_value": float(components.get("information_value") or 0),
        "resolution_proximity": float(components.get("resolution_proximity") or 0),
        "inverse_cost": min(0.02 / cost, 1.0),
    }


def _utility_probability(
    components: dict[str, Any], coefficients: dict[str, float]
) -> float:
    return _utility_probability_from_features(
        _utility_features(components), coefficients
    )


def _utility_probability_from_features(
    features: dict[str, float], coefficients: dict[str, float]
) -> float:
    value = float(coefficients.get("intercept") or 0) + sum(
        float(coefficients.get(name) or 0) * feature
        for name, feature in features.items()
    )
    return _sigmoid(value)


def _sigmoid(value: float) -> float:
    value = max(min(value, 40.0), -40.0)
    return 1.0 / (1.0 + exp(-value))
def record_source_change_event(
    ledger,
    *,
    question_id: str | None,
    watch: dict[str, Any],
    source_snapshot: dict[str, Any],
    previous_signature: str | None,
    current_signature: str | None,
    detected_at: str,
) -> dict[str, Any]:
    event_id = f"sce_{uuid.uuid4().hex[:12]}"
    task_id = f"ot_{uuid.uuid4().hex[:12]}"
    idempotency_key = f"source-change:{watch['id']}:{source_snapshot['id']}"
    prior_forecast = ledger.get_current_snapshot(question_id) if question_id else None
    utility = calculate_task_utility(
        ledger,
        question_id=question_id,
        task_type="process_source_change",
        watch=watch,
        now=detected_at,
    )
    with ledger._connect() as conn:
        previous = conn.execute(
            """
            SELECT id FROM source_snapshots
            WHERE watched_source_id = ? AND id != ?
            ORDER BY retrieved_at DESC, rowid DESC LIMIT 1
            """,
            (watch["id"], source_snapshot["id"]),
        ).fetchone()
        conn.execute(
            """
            INSERT OR IGNORE INTO source_change_events (
                id, question_id, watched_source_id, prior_source_snapshot_id,
                new_source_snapshot_id, prior_forecast_id, detected_at,
                source_observed_at, old_state, new_state, materiality, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                question_id,
                watch["id"],
                previous["id"] if previous else None,
                source_snapshot["id"],
                getattr(prior_forecast, "forecast_id", None),
                detected_at,
                source_snapshot.get("retrieved_at") or detected_at,
                json_dumps({"signature": previous_signature}),
                json_dumps({"signature": current_signature, "status": source_snapshot.get("status")}),
                json_dumps({"changed": True}),
                json_dumps({"source_type": watch.get("source_type"), "source": watch.get("source")}),
            ),
        )
        event = conn.execute(
            "SELECT * FROM source_change_events WHERE watched_source_id = ? AND new_source_snapshot_id = ?",
            (watch["id"], source_snapshot["id"]),
        ).fetchone()
        event_id = event["id"]
        conn.execute(
            """
            INSERT OR IGNORE INTO source_change_event_transitions (
                id, source_change_event_id, from_state, to_state, actor, reason, created_at
            ) VALUES (?, ?, NULL, 'detected', 'source-monitor', 'source signature changed', ?)
            """,
            (f"scet_{event_id}", event_id, detected_at),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO operational_tasks (
                id, task_type, lane, question_id, source_change_event_id,
                status, priority, utility_score, utility_components, available_at,
                idempotency_key, created_at, updated_at
            ) VALUES (?, 'process_source_change', 'deterministic_critical', ?, ?,
                      'pending', 70, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                question_id,
                event_id,
                utility["score"],
                json_dumps(utility["components"]),
                detected_at,
                idempotency_key,
                detected_at,
                detected_at,
            ),
        )
        task = conn.execute(
            "SELECT * FROM operational_tasks WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return {"event": _event_dict(event), "task": _task_dict(task)}


def pending_source_change(
    ledger, *, watched_source_id: str, current_signature: str | None
) -> dict[str, Any] | None:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM source_change_events WHERE watched_source_id = ? AND status = 'pending'",
            (watched_source_id,),
        ).fetchall()
        for row in rows:
            event = _event_dict(row)
            if event["new_state"].get("signature") == current_signature:
                task = conn.execute(
                    "SELECT * FROM operational_tasks WHERE source_change_event_id = ? LIMIT 1",
                    (event["id"],),
                ).fetchone()
                return {"event": event, "task": _task_dict(task)}
    return None


def link_source_change_alert(ledger, event_id: str, alert_id: str) -> None:
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE operational_tasks SET alert_id = ?, updated_at = ? WHERE source_change_event_id = ?",
            (alert_id, utc_now_iso(), event_id),
        )


def list_source_change_events(
    ledger, *, question_id: str | None = None, status: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if question_id:
        clauses.append("question_id = ?")
        params.append(question_id)
    if status:
        clauses.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(int(limit), 1))
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM source_change_events {where} ORDER BY detected_at ASC LIMIT ?",
            params,
        ).fetchall()
    return [_event_dict(row) for row in rows]


def list_source_change_event_transitions(
    ledger, source_change_event_id: str
) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT * FROM source_change_event_transitions
            WHERE source_change_event_id = ? ORDER BY created_at ASC, rowid ASC
            """,
            (source_change_event_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def transition_source_change_event(
    ledger,
    event_id: str,
    *,
    to_state: str,
    actor: str,
    reason: str | None = None,
    now: str | None = None,
    allowed_from: set[str] | None = None,
) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        _transition_source_change_event_conn(
            conn,
            event_id,
            to_state=to_state,
            actor=actor,
            reason=reason,
            now=stamp,
            allowed_from=allowed_from,
        )
        row = conn.execute(
            "SELECT * FROM source_change_events WHERE id = ?", (event_id,)
        ).fetchone()
    return _event_dict(row)


def reconcile_source_events_for_proposal(
    ledger,
    proposal_id: str,
    *,
    outcome: str,
    actor: str,
    forecast_snapshot_id: str | None = None,
) -> int:
    if outcome not in {"committed", "rejected"}:
        raise ValidationError("proposal event outcome must be committed or rejected")
    stamp = utc_now_iso()
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT id FROM source_change_events WHERE proposal_id = ?",
            (proposal_id,),
        ).fetchall()
        for row in rows:
            _transition_source_change_event_conn(
                conn,
                row["id"],
                to_state=outcome,
                actor=actor,
                reason=f"proposal {proposal_id} {outcome}",
                now=stamp,
            )
            conn.execute(
                """
                UPDATE source_change_events SET disposition = ?, forecast_snapshot_id = ?
                WHERE id = ?
                """,
                (outcome, forecast_snapshot_id, row["id"]),
            )
            _transition_source_change_event_conn(
                conn,
                row["id"],
                to_state="reconciled",
                actor=actor,
                reason="proposal outcome reconciled",
                now=stamp,
            )
    return len(rows)


def _transition_source_change_event_conn(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    to_state: str,
    actor: str,
    reason: str | None,
    now: str,
    allowed_from: set[str] | None = None,
) -> None:
    if to_state not in SOURCE_EVENT_STATES:
        raise ValidationError(f"invalid source-change state: {to_state}")
    row = conn.execute(
        "SELECT state FROM source_change_events WHERE id = ?", (event_id,)
    ).fetchone()
    if row is None:
        raise ValidationError(f"source-change event not found: {event_id}")
    from_state = row["state"] or "detected"
    if allowed_from is not None and from_state not in allowed_from:
        raise ValidationError(
            f"cannot transition source-change event {event_id} from {from_state} to {to_state}"
        )
    if from_state == to_state:
        return
    conn.execute(
        "UPDATE source_change_events SET state = ? WHERE id = ?",
        (to_state, event_id),
    )
    conn.execute(
        """
        INSERT INTO source_change_event_transitions (
            id, source_change_event_id, from_state, to_state, actor, reason, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            f"scet_{uuid.uuid4().hex[:12]}",
            event_id,
            from_state,
            to_state,
            actor,
            reason,
            now,
        ),
    )


def list_operational_tasks(
    ledger, *, status: str | None = None, lane: str | None = None, limit: int = 100
) -> list[dict[str, Any]]:
    clauses, params = [], []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if lane:
        clauses.append("lane = ?")
        params.append(lane)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(max(int(limit), 1))
    with ledger._connect() as conn:
        rows = conn.execute(
            f"SELECT * FROM operational_tasks {where} "
            "ORDER BY utility_score DESC, priority DESC, available_at ASC LIMIT ?",
            params,
        ).fetchall()
    return [_task_dict(row) for row in rows]


def enqueue_alert_operational_task(
    ledger,
    alert,
    *,
    lane: str,
    now: str | None = None,
) -> dict[str, Any]:
    """Ensure one durable, SLA-bearing task exists for an open alert."""
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    severity = str(getattr(alert, "severity", "") or "warning").lower()
    priority = 100 if severity in {"critical", "high"} else 70 if severity == "warning" else 50
    due_minutes = 60 if severity in {"critical", "high"} else 1440 if severity == "warning" else 4320
    question_id = None
    if getattr(alert, "scope_type", None) == "question":
        try:
            ledger.get_question(alert.scope_ref)
            question_id = alert.scope_ref
        except Exception:
            question_id = None
    try:
        utility = calculate_task_utility(
            ledger,
            question_id=question_id,
            task_type="resolve_warning",
            now=stamp,
        )
    except Exception:
        utility = {"score": 0.0, "components": {"model_version": "utility-v1"}}
    task_id = f"ot_{uuid.uuid4().hex[:12]}"
    idempotency_key = f"warning:{alert.id}"
    due_at = (now_dt + timedelta(minutes=due_minutes)).isoformat().replace("+00:00", "Z")
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO operational_tasks (
                id, task_type, lane, question_id, alert_id, status, priority,
                utility_score, utility_components, available_at, due_at,
                idempotency_key, created_at, updated_at
            ) VALUES (?, 'resolve_warning', ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                lane,
                question_id,
                alert.id,
                priority,
                utility["score"],
                json_dumps(utility["components"]),
                stamp,
                due_at,
                idempotency_key,
                stamp,
                stamp,
            ),
        )
        conn.execute(
            """
            UPDATE operational_tasks
            SET lane = CASE WHEN ? = 'urgent_forecast' THEN ? ELSE lane END,
                priority = MAX(priority, ?), due_at = MIN(COALESCE(due_at, ?), ?),
                updated_at = ?
            WHERE idempotency_key = ? AND status IN ('pending', 'leased')
            """,
            (lane, lane, priority, due_at, due_at, stamp, idempotency_key),
        )
        row = conn.execute(
            "SELECT * FROM operational_tasks WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
    return _task_dict(row)


def claim_alert_operational_task(
    ledger,
    alert,
    *,
    owner: str,
    lane: str,
    now: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any] | None:
    """Claim the single durable task that owns one alert action."""
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    expires = (now_dt + timedelta(seconds=max(int(lease_seconds), 1))).isoformat().replace(
        "+00:00", "Z"
    )
    code_revision, worktree_dirty = _runtime_code_identity()
    task = enqueue_alert_operational_task(ledger, alert, lane=lane, now=stamp)
    idempotency_key = task["idempotency_key"]
    with ledger._connect() as conn:
        claimed = conn.execute(
            """
            UPDATE operational_tasks
            SET status = 'leased', lease_owner = ?, lease_expires_at = ?,
                claimed_at = ?, attempt_count = attempt_count + 1, updated_at = ?
            WHERE idempotency_key = ? AND attempt_count < max_attempts
              AND (status = 'pending' OR (status = 'leased' AND lease_expires_at <= ?))
            """,
            (owner, expires, stamp, stamp, idempotency_key, stamp),
        )
        if claimed.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM operational_tasks WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        conn.execute(
            """
            UPDATE operational_task_attempts
            SET finished_at = ?, outcome = 'lease_expired',
                error = COALESCE(error, 'worker lease expired before completion')
            WHERE task_id = ? AND finished_at IS NULL AND owner != ?
            """,
            (stamp, row["id"], owner),
        )
        conn.execute(
            """
            INSERT INTO operational_task_attempts (
                id, task_id, lane, owner, claimed_at, code_revision, worktree_dirty
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                f"ota_{uuid.uuid4().hex[:12]}",
                row["id"],
                row["lane"],
                owner,
                stamp,
                code_revision,
                1 if worktree_dirty else 0,
            ),
        )
    return _task_dict(row)


def claim_operational_tasks(
    ledger,
    *,
    owner: str,
    lane: str = "deterministic_critical",
    now: str | None = None,
    lease_seconds: int = 300,
    limit: int = 10,
    task_type: str | None = None,
    question_id: str | None = None,
) -> list[dict[str, Any]]:
    stamp = now or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    expires = (now_dt + timedelta(seconds=max(int(lease_seconds), 1))).isoformat().replace(
        "+00:00", "Z"
    )
    code_revision, worktree_dirty = _runtime_code_identity()
    claimed_ids: list[str] = []
    reclaim_expired_operational_tasks(ledger, owner=owner, now=stamp)
    with ledger._connect() as conn:
        policy = conn.execute(
            "SELECT * FROM operational_lane_policies WHERE lane = ?", (lane,)
        ).fetchone()
        if policy is None or not bool(policy["enabled"]):
            return []
        if lane == "maintenance":
            higher = conn.execute(
                """
                SELECT task.available_at, policy.slo_minutes
                FROM operational_tasks AS task
                JOIN operational_lane_policies AS policy ON policy.lane = task.lane
                WHERE task.status IN ('pending', 'leased')
                  AND task.lane IN ('deterministic_critical', 'urgent_forecast')
                """,
            ).fetchall()
            if any(
                (timestamp_to_datetime(row["available_at"]) or now_dt)
                <= now_dt - timedelta(minutes=int(row["slo_minutes"]))
                for row in higher
            ):
                return []
        day_start = f"{stamp[:10]}T00:00:00Z"
        used = conn.execute(
            "SELECT COUNT(*) AS n FROM operational_task_attempts WHERE lane = ? AND claimed_at >= ?",
            (lane, day_start),
        ).fetchone()["n"]
        remaining_budget = max(int(policy["daily_claim_budget"]) - int(used), 0)
        if remaining_budget == 0:
            return []
        claim_limit = min(max(int(limit), 1), remaining_budget)
        exhausted_rows = conn.execute(
            """
            SELECT id, source_change_event_id FROM operational_tasks
            WHERE status IN ('pending', 'leased') AND attempt_count >= max_attempts
              AND (status = 'pending' OR lease_expires_at <= ?)
            """,
            (stamp,),
        ).fetchall()
        conn.execute(
            """
            UPDATE operational_tasks
            SET status = 'dead_letter', disposition = 'failed_dead_letter',
                lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE status IN ('pending', 'leased') AND attempt_count >= max_attempts
              AND (status = 'pending' OR lease_expires_at <= ?)
            """,
            (stamp, stamp),
        )
        for exhausted_row in exhausted_rows:
            if exhausted_row["source_change_event_id"]:
                _transition_source_change_event_conn(
                    conn,
                    exhausted_row["source_change_event_id"],
                    to_state="failed",
                    actor=owner,
                    reason="expired task exhausted retries",
                    now=stamp,
                )
                conn.execute(
                    "UPDATE source_change_events SET status = 'failed', "
                    "error = 'operational task exhausted retries' WHERE id = ?",
                    (exhausted_row["source_change_event_id"],),
                )
        rows = conn.execute(
            """
            SELECT id FROM operational_tasks
            WHERE lane = ? AND available_at <= ?
              AND (status = 'pending' OR (status = 'leased' AND lease_expires_at <= ?))
              AND attempt_count < max_attempts
              AND (? IS NULL OR task_type = ?)
              AND (? IS NULL OR question_id = ?)
            ORDER BY
                CASE WHEN ? = 'urgent_forecast' THEN available_at END ASC,
                CASE WHEN ? != 'urgent_forecast' THEN utility_score END DESC,
                priority DESC, available_at ASC LIMIT ?
            """,
            (
                lane,
                stamp,
                stamp,
                task_type,
                task_type,
                question_id,
                question_id,
                lane,
                lane,
                min(max(claim_limit * 50, claim_limit), 5000),
            ),
        ).fetchall()
        for row in rows:
            if len(claimed_ids) >= claim_limit:
                break
            source_event_id = conn.execute(
                "SELECT source_change_event_id FROM operational_tasks WHERE id = ?",
                (row["id"],),
            ).fetchone()["source_change_event_id"]
            if source_event_id:
                same_question_running = conn.execute(
                    """
                    SELECT 1
                    FROM operational_tasks running
                    JOIN source_change_events running_event
                      ON running_event.id = running.source_change_event_id
                    JOIN source_change_events candidate_event
                      ON candidate_event.id = ?
                    WHERE running.status = 'leased'
                      AND running.lease_expires_at > ?
                      AND running.id != ?
                      AND running_event.question_id = candidate_event.question_id
                    LIMIT 1
                    """,
                    (source_event_id, stamp, row["id"]),
                ).fetchone()
                if same_question_running is not None:
                    continue
            result = conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'leased', lease_owner = ?, lease_expires_at = ?,
                    claimed_at = ?, attempt_count = attempt_count + 1, updated_at = ?
                WHERE id = ? AND (status = 'pending' OR
                    (status = 'leased' AND lease_expires_at <= ?))
                """,
                (owner, expires, stamp, stamp, row["id"], stamp),
            )
            if result.rowcount == 1:
                claimed_ids.append(row["id"])
                if source_event_id:
                    _transition_source_change_event_conn(
                        conn,
                        source_event_id,
                        to_state="claimed",
                        actor=owner,
                        reason=f"claimed task {row['id']}",
                        now=stamp,
                        allowed_from={"detected", "triaged", "claimed", "failed"},
                    )
                conn.execute(
                    """
                    UPDATE operational_task_attempts
                    SET finished_at = ?, outcome = 'lease_expired',
                        error = COALESCE(error, 'worker lease expired before completion')
                    WHERE task_id = ? AND finished_at IS NULL AND owner != ?
                    """,
                    (stamp, row["id"], owner),
                )
                conn.execute(
                    """
                    INSERT INTO operational_task_attempts
                        (id, task_id, lane, owner, claimed_at, code_revision, worktree_dirty)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        f"ota_{uuid.uuid4().hex[:12]}",
                        row["id"],
                        lane,
                        owner,
                        stamp,
                        code_revision,
                        1 if worktree_dirty else 0,
                    ),
                )
        claimed = [
            conn.execute("SELECT * FROM operational_tasks WHERE id = ?", (task_id,)).fetchone()
            for task_id in claimed_ids
        ]
    return [_task_dict(row) for row in claimed]


def reclaim_expired_operational_tasks(
    ledger,
    *,
    owner: str = "lease-reclaimer",
    now: str | None = None,
) -> dict[str, int]:
    """Return expired leases to their correct queue before each worker claim."""
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    counts = {"requeued": 0, "awaiting_human": 0, "dead_lettered": 0}
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT id, source_change_event_id, attempt_count, max_attempts, disposition
            FROM operational_tasks
            WHERE status = 'leased' AND lease_expires_at <= ?
            """,
            (stamp,),
        ).fetchall()
        for row in rows:
            if row["disposition"] == "human_escalation_required":
                status = "awaiting_human"
                disposition = row["disposition"]
                counts["awaiting_human"] += 1
            elif int(row["attempt_count"] or 0) >= int(row["max_attempts"] or 1):
                status = "dead_letter"
                disposition = "failed_dead_letter"
                counts["dead_lettered"] += 1
            else:
                status = "pending"
                disposition = "lease_expired_requeued"
                counts["requeued"] += 1
            conn.execute(
                """
                UPDATE operational_tasks
                SET status = ?, disposition = ?, lease_owner = NULL,
                    lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'leased'
                """,
                (status, disposition, stamp, row["id"]),
            )
            conn.execute(
                """
                UPDATE operational_task_attempts
                SET finished_at = ?, outcome = 'lease_expired',
                    error = COALESCE(error, 'worker lease expired before completion')
                WHERE task_id = ? AND finished_at IS NULL
                """,
                (stamp, row["id"]),
            )
            if status == "dead_letter" and row["source_change_event_id"]:
                _transition_source_change_event_conn(
                    conn,
                    row["source_change_event_id"],
                    to_state="failed",
                    actor=owner,
                    reason="expired task exhausted retries",
                    now=stamp,
                )
                conn.execute(
                    """
                    UPDATE source_change_events
                    SET status = 'failed', error = 'operational task exhausted retries'
                    WHERE id = ?
                    """,
                    (row["source_change_event_id"],),
                )
    return counts


def complete_operational_task(
    ledger,
    task_id: str,
    *,
    owner: str,
    disposition: str,
    result: dict[str, Any] | None = None,
    usage: dict[str, Any] | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        if disposition == "surfaced_for_review":
            updated = conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'awaiting_human', disposition = ?, result = ?, error = NULL,
                    escalation_owner = COALESCE(
                        (SELECT NULLIF(owner, '') FROM forecast_questions
                         WHERE id = operational_tasks.question_id),
                        'human:forecast-duty'
                    ),
                    escalated_at = ?, lease_owner = NULL, lease_expires_at = NULL,
                    completed_at = NULL, updated_at = ?
                WHERE id = ? AND status = 'leased' AND lease_owner = ?
                """,
                (disposition, json_dumps(result or {}), stamp, stamp, task_id, owner),
            )
        else:
            updated = conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'completed', disposition = ?, result = ?, error = NULL,
                    lease_owner = NULL, lease_expires_at = NULL,
                    completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'leased' AND lease_owner = ?
                """,
                (disposition, json_dumps(result or {}), stamp, stamp, task_id, owner),
            )
        if updated.rowcount != 1:
            raise ValueError("operational task is not leased by this worker")
        conn.execute(
            """
            UPDATE operational_task_attempts
            SET finished_at = ?, outcome = ?
            WHERE task_id = ? AND owner = ? AND finished_at IS NULL
            """,
            (stamp, disposition, task_id, owner),
        )
        _record_attempt_usage(conn, task_id=task_id, owner=owner, usage=usage)
        row = conn.execute(
            "SELECT * FROM operational_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row["task_type"] == "process_source_change" and disposition in {
            "reviewed_immaterial",
            "proposed",
            "auto_committed",
            "superseded_by_new_forecast",
        }:
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, 'estimation_completed'),
                    ack_note = COALESCE(ack_note, 'auto_close:estimation_completed')
                WHERE scope_type = 'question' AND scope_ref = ?
                  AND reason LIKE 'forecast_estimation_required:%'
                  AND acknowledged_at IS NULL
                """,
                (stamp, row["question_id"]),
            )
    return _task_dict(row)


def _record_attempt_usage(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    owner: str,
    usage: dict[str, Any] | None,
) -> None:
    if not usage:
        return
    values = {
        "model_calls": max(int(usage.get("model_calls") or 0), 0),
        "source_calls": max(int(usage.get("source_calls") or 0), 0),
        "input_tokens": max(int(usage.get("input_tokens") or 0), 0),
        "output_tokens": max(int(usage.get("output_tokens") or 0), 0),
        "cost_usd": max(float(usage.get("cost_usd") or 0), 0.0),
        "cost_status": str(usage.get("cost_status") or "unknown"),
        "cost_source": str(usage.get("cost_source") or "unknown"),
        "latency_ms": max(int(usage.get("latency_ms") or 0), 0),
    }
    conn.execute(
        """
        UPDATE operational_task_attempts
        SET model_calls = ?, source_calls = ?, input_tokens = ?, output_tokens = ?,
            cost_usd = ?, latency_ms = ?, cost_status = ?, cost_source = ?
        WHERE id = (
            SELECT id FROM operational_task_attempts
            WHERE task_id = ? AND owner = ?
            ORDER BY claimed_at DESC LIMIT 1
        )
        """,
        (
            values["model_calls"],
            values["source_calls"],
            values["input_tokens"],
            values["output_tokens"],
            values["cost_usd"],
            values["latency_ms"],
            values["cost_status"],
            values["cost_source"],
            task_id,
            owner,
        ),
    )


def run_source_change_router(
    ledger,
    *,
    owner: str,
    now: str | None = None,
    limit: int = 100,
    lease_seconds: int = 300,
) -> list[dict[str, Any]]:
    """Route exact immutable source events without fetching their sources again.

    Monitoring owns observation; estimation owns judgment. This deterministic
    worker is the handoff between them: valid observations move to the estimator
    lane, while inactive/superseded work is closed against current ledger state.
    """
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    tasks = claim_operational_tasks(
        ledger,
        owner=owner,
        lane="deterministic_critical",
        now=stamp,
        lease_seconds=lease_seconds,
        limit=limit,
        task_type="process_source_change",
    )
    results: list[dict[str, Any]] = []
    for task in tasks:
        event_id = task.get("source_change_event_id")
        try:
            with ledger._connect() as conn:
                event_row = conn.execute(
                    "SELECT * FROM source_change_events WHERE id = ?", (event_id,)
                ).fetchone()
            if event_row is None:
                raise ValidationError(f"source-change event not found: {event_id}")
            event = _event_dict(event_row)
            if event["status"] != "pending":
                completed = complete_operational_task(
                    ledger,
                    task["id"],
                    owner=owner,
                    disposition="event_already_terminal",
                    result={"source_change_event_id": event_id},
                    now=stamp,
                )
                results.append({"task": completed, "event": event})
                continue

            question = ledger.get_question(event["question_id"])
            current = ledger.get_current_snapshot(event["question_id"])
            if question.status != "active":
                results.append(
                    _close_source_change_task(
                        ledger,
                        task=task,
                        event=event,
                        owner=owner,
                        state="reconciled",
                        disposition="question_not_active",
                        now=stamp,
                    )
                )
                continue
            if current is None or current.forecast_id != event.get("prior_forecast_id"):
                results.append(
                    _close_source_change_task(
                        ledger,
                        task=task,
                        event=event,
                        owner=owner,
                        state="superseded",
                        disposition="superseded_by_new_forecast",
                        forecast_snapshot_id=getattr(current, "forecast_id", None),
                        now=stamp,
                    )
                )
                continue
            if event["new_state"].get("status") != "success":
                results.append(
                    _close_source_change_task(
                        ledger,
                        task=task,
                        event=event,
                        owner=owner,
                        state="failed",
                        disposition="source_observation_failed",
                        acknowledge_alert=True,
                        now=stamp,
                    )
                )
                continue

            transition_source_change_event(
                ledger,
                event_id,
                to_state="triaged",
                actor=owner,
                reason="immutable source observation routed to estimator",
                now=stamp,
                allowed_from={"detected", "triaged", "claimed", "failed"},
            )
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE source_change_events SET disposition = 'estimator_required', "
                    "error = NULL, claim_owner = NULL, claim_expires_at = NULL WHERE id = ?",
                    (event_id,),
                )
                moved = conn.execute(
                    """
                    UPDATE operational_tasks
                    SET lane = 'normal_reforecast', priority = MAX(priority, 80),
                        status = 'pending', disposition = 'estimator_required', error = NULL,
                        lease_owner = NULL, lease_expires_at = NULL, available_at = ?, updated_at = ?
                    WHERE id = ? AND status = 'leased' AND lease_owner = ?
                    """,
                    (stamp, stamp, task["id"], owner),
                )
                if moved.rowcount != 1:
                    raise ValidationError("source-change route lost its task lease")
                conn.execute(
                    """
                    UPDATE operational_task_attempts
                    SET finished_at = ?, outcome = 'routed_to_estimator'
                    WHERE task_id = ? AND owner = ? AND finished_at IS NULL
                    """,
                    (stamp, task["id"], owner),
                )
                task_row = conn.execute(
                    "SELECT * FROM operational_tasks WHERE id = ?", (task["id"],)
                ).fetchone()
                final_event = conn.execute(
                    "SELECT * FROM source_change_events WHERE id = ?", (event_id,)
                ).fetchone()
            results.append({"task": _task_dict(task_row), "event": _event_dict(final_event)})
        except Exception as exc:
            try:
                failed = fail_operational_task(
                    ledger, task["id"], owner=owner, error=str(exc)[:2000], now=stamp
                )
                results.append({"task": failed, "error": str(exc)})
            except Exception as failure_exc:
                results.append(
                    {"task": task, "error": str(exc), "failure_recording_error": str(failure_exc)}
                )
    return results


def _close_source_change_task(
    ledger,
    *,
    task: dict[str, Any],
    event: dict[str, Any],
    owner: str,
    state: str,
    disposition: str,
    forecast_snapshot_id: str | None = None,
    acknowledge_alert: bool = True,
    now: str,
) -> dict[str, Any]:
    transition_source_change_event(
        ledger,
        event["id"],
        to_state=state,
        actor=owner,
        reason=disposition,
        now=now,
        allowed_from={"detected", "triaged", "claimed", "failed"},
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE source_change_events
            SET status = ?, disposition = ?, forecast_snapshot_id = ?, error = NULL,
                claim_owner = NULL, claim_expires_at = NULL
            WHERE id = ?
            """,
            ("failed" if state == "failed" else "processed", disposition,
             forecast_snapshot_id, event["id"]),
        )
        if state != "failed":
            conn.execute(
                "UPDATE watched_sources SET last_checked_at = ?, last_seen_signature = ? WHERE id = ?",
                (now, event["new_state"].get("signature"), event["watched_source_id"]),
            )
        if acknowledge_alert:
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, ?),
                    ack_note = COALESCE(ack_note, 'auto_close:source_event_terminal')
                WHERE id = ?
                """,
                (now, disposition, task.get("alert_id")),
            )
    completed = complete_operational_task(
        ledger,
        task["id"],
        owner=owner,
        disposition=disposition,
        result={"source_change_event_id": event["id"], "forecast_snapshot_id": forecast_snapshot_id},
        now=now,
    )
    with ledger._connect() as conn:
        final_event = conn.execute(
            "SELECT * FROM source_change_events WHERE id = ?", (event["id"],)
        ).fetchone()
    return {"task": completed, "event": _event_dict(final_event)}


def run_estimator_tasks(
    ledger,
    *,
    owner: str,
    estimator: Callable[[dict[str, Any]], dict[str, Any]],
    now: str | None = None,
    limit: int = 5,
    lease_seconds: int = 900,
    question_id: str | None = None,
    allow_auto_commit: bool = False,
) -> list[dict[str, Any]]:
    """Consume immutable source-change events with an injected estimator.

    The callback receives the event and its already-persisted source snapshot. It
    must return a structured estimate; this worker never polls the source again.
    """
    if not callable(estimator):
        raise ValidationError("an estimator callback is required")
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    tasks = claim_operational_tasks(
        ledger,
        owner=owner,
        lane="normal_reforecast",
        now=stamp,
        lease_seconds=lease_seconds,
        limit=limit,
        task_type="process_source_change",
        question_id=question_id,
    )
    results: list[dict[str, Any]] = []
    for task in tasks:
        try:
            payload = _estimator_payload(ledger, task, now=stamp)
            current = ledger.get_current_snapshot(payload["source_change_event"]["question_id"])
            if (
                current is not None
                and current.forecast_id
                != payload["source_change_event"].get("prior_forecast_id")
            ):
                # The expensive callback cannot affect this event anymore.  Let the
                # normal apply path close it against current state without spending
                # a model call.
                results.append(
                    apply_estimation_result(
                        ledger,
                        task_id=task["id"],
                        owner=owner,
                        estimate={},
                        now=stamp,
                        allow_auto_commit=allow_auto_commit,
                    )
                )
                continue
            replay_estimate = (task.get("result") or {}).get("replay_estimate")
            if not replay_estimate and not any(
                bool((snapshot.get("parsed_values") or {}).get("content_available"))
                for snapshot in payload.get("source_snapshots") or []
            ):
                event_ids = [row["id"] for row in payload["source_change_events"]]
                complete_source_change_events(
                    ledger,
                    question_id=payload["source_change_event"]["question_id"],
                    event_ids=event_ids,
                    status="processed",
                    disposition="insufficient_content",
                    forecast_snapshot_id=getattr(current, "forecast_id", None),
                    now=stamp,
                )
                with ledger._connect() as conn:
                    conn.execute(
                        """
                        UPDATE alert_events
                        SET acknowledged_at = COALESCE(acknowledged_at, ?),
                            disposition = COALESCE(disposition, 'insufficient_content'),
                            ack_note = COALESCE(ack_note, 'auto_close:insufficient_source_content')
                        WHERE scope_type = 'question' AND scope_ref = ?
                          AND reason LIKE 'forecast_estimation_required:%'
                          AND acknowledged_at IS NULL
                        """,
                        (stamp, payload["source_change_event"]["question_id"]),
                    )
                    task_row = conn.execute(
                        "SELECT * FROM operational_tasks WHERE id = ?", (task["id"],)
                    ).fetchone()
                    event_row = conn.execute(
                        "SELECT * FROM source_change_events WHERE id = ?",
                        (payload["source_change_event"]["id"],),
                    ).fetchone()
                results.append(
                    {
                        "task": _task_dict(task_row),
                        "event": _event_dict(event_row),
                        "proposal": None,
                        "insufficient_content": True,
                    }
                )
                continue
            estimate = replay_estimate or estimator(payload)
            if not isinstance(estimate, dict):
                raise ValidationError("estimator must return an object")
            from forecasting.estimator_worker import normalize_estimator_forecast

            outcome_space = (payload.get("question") or {}).get("outcome_space") or {}
            estimate["proposed_probability_or_distribution"] = normalize_estimator_forecast(
                estimate.get("proposed_probability_or_distribution"),
                outcome_type=str(outcome_space.get("type") or "binary"),
            )
            transition_source_change_event(
                ledger,
                task["source_change_event_id"],
                to_state="researched",
                actor=owner,
                reason="estimator completed source research",
                now=stamp,
                allowed_from={"claimed"},
            )
            result = apply_estimation_result(
                ledger,
                task_id=task["id"],
                owner=owner,
                estimate=estimate,
                now=stamp,
                allow_auto_commit=allow_auto_commit,
            )
            results.append(result)
        except Exception as exc:  # one event must not poison the worker batch
            try:
                transition_source_change_event(
                    ledger,
                    task["source_change_event_id"],
                    to_state="failed",
                    actor=owner,
                    reason=str(exc)[:500],
                    now=stamp,
                    allowed_from={"claimed", "researched", "estimated", "failed"},
                )
                failed = fail_operational_task(
                    ledger,
                    task["id"],
                    owner=owner,
                    error=str(exc)[:2000],
                    usage=getattr(exc, "usage", None),
                    now=stamp,
                    retryable=not isinstance(exc, ValidationError)
                    and exc.__class__.__name__ != "EstimatorOutputError",
                )
                results.append({"task": failed, "error": str(exc)})
            except Exception as failure_exc:
                results.append(
                    {
                        "task": task,
                        "error": str(exc),
                        "failure_recording_error": str(failure_exc),
                    }
                )
    return results


def _estimator_batch_rows(
    ledger, task: dict[str, Any], *, now: str
) -> list[dict[str, Any]]:
    event_id = task.get("source_change_event_id")
    if not event_id:
        raise ValidationError("estimator task has no source-change event")
    with ledger._connect() as conn:
        event_row = conn.execute(
            "SELECT * FROM source_change_events WHERE id = ?", (event_id,)
        ).fetchone()
        if event_row is None:
            raise ValidationError(f"source-change event not found: {event_id}")
        rows = conn.execute(
            """
            SELECT event.id, task.id AS task_id
            FROM source_change_events AS event
            JOIN operational_tasks AS task ON task.source_change_event_id = event.id
            WHERE event.question_id = ? AND event.prior_forecast_id IS ?
              AND event.status = 'pending' AND task.task_type = 'process_source_change'
              AND (
                  task.id = ? OR task.status = 'pending'
                  OR (task.status = 'leased' AND task.lease_expires_at <= ?)
              )
            ORDER BY CASE WHEN task.id = ? THEN 0 ELSE 1 END,
                     event.detected_at, event.id
            LIMIT 6
            """,
            (
                event_row["question_id"],
                event_row["prior_forecast_id"],
                task["id"],
                now,
                task["id"],
            ),
        ).fetchall()
        batch: list[dict[str, Any]] = []
        for row in rows:
            candidate = conn.execute(
                "SELECT * FROM source_change_events WHERE id = ?", (row["id"],)
            ).fetchone()
            snapshot = conn.execute(
                "SELECT * FROM source_snapshots WHERE id = ?",
                (candidate["new_source_snapshot_id"],),
            ).fetchone()
            watch = conn.execute(
                "SELECT * FROM watched_sources WHERE id = ?",
                (candidate["watched_source_id"],),
            ).fetchone()
            batch.append(
                {
                    "event": _event_dict(candidate),
                    "task_id": row["task_id"],
                    "source_snapshot": ledger._row_to_source_snapshot(snapshot),
                    "watched_source": ledger._row_to_watched_source(watch),
                }
            )
    return batch


def _estimator_payload(
    ledger, task: dict[str, Any], *, now: str | None = None
) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    batch = _estimator_batch_rows(ledger, task, now=stamp)
    if not batch:
        raise ValidationError("estimator task has no serviceable source-change events")
    primary = batch[0]
    event = primary["event"]
    question = ledger.get_question(event["question_id"])
    prior = (
        ledger.get_snapshot(event["prior_forecast_id"])
        if event.get("prior_forecast_id")
        else None
    )
    return {
        "task_id": task["id"],
        "source_change_event": event,
        "source_snapshot": primary["source_snapshot"],
        "watched_source": primary["watched_source"],
        "source_change_events": [row["event"] for row in batch],
        "source_snapshots": [row["source_snapshot"] for row in batch],
        "watched_sources": [row["watched_source"] for row in batch],
        "question": asdict(question),
        "prior_forecast": asdict(prior) if prior else None,
    }


def apply_estimation_result(
    ledger,
    *,
    task_id: str,
    owner: str,
    estimate: dict[str, Any],
    now: str | None = None,
    allow_auto_commit: bool = False,
) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        task_row = conn.execute(
            "SELECT * FROM operational_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if (
            task_row is None
            or task_row["status"] != "leased"
            or task_row["lease_owner"] != owner
        ):
            raise ValidationError("estimator task is not leased by this worker")
        event_row = conn.execute(
            "SELECT * FROM source_change_events WHERE id = ?",
            (task_row["source_change_event_id"],),
        ).fetchone()
    event = _event_dict(event_row)
    batch = _estimator_batch_rows(ledger, _task_dict(task_row), now=stamp)
    batch_events = [row["event"] for row in batch]
    batch_event_ids = [row["id"] for row in batch_events]
    sibling_event_ids = [event_id for event_id in batch_event_ids if event_id != event["id"]]
    source_snapshots = [row["source_snapshot"] for row in batch]
    source_snapshot_refs = [row["id"] for row in source_snapshots]
    evidence_refs = _evidence_refs_from_source_snapshots(
        ledger,
        question_id=event["question_id"],
        source_snapshots=source_snapshots,
    )
    current = ledger.get_current_snapshot(event["question_id"])
    if current is None:
        raise ValidationError("estimation requires a current forecast")
    if current.forecast_id != event.get("prior_forecast_id"):
        transition_source_change_event(
            ledger,
            event["id"],
            to_state="superseded",
            actor=owner,
            reason=f"current forecast changed to {current.forecast_id}",
            now=stamp,
            allowed_from={"researched", "claimed", "failed"},
        )
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE source_change_events
                SET status = 'processed', disposition = 'superseded_by_new_forecast',
                    forecast_snapshot_id = ?, error = NULL
                WHERE id = ?
                """,
                (current.forecast_id, event["id"]),
            )
            conn.execute(
                """
                UPDATE watched_sources
                SET last_checked_at = ?, last_seen_signature = ? WHERE id = ?
                """,
                (
                    stamp,
                    event["new_state"].get("signature"),
                    event["watched_source_id"],
                ),
            )
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, 'superseded'),
                    ack_note = COALESCE(ack_note, 'auto_close:event_superseded')
                WHERE id = (SELECT alert_id FROM operational_tasks WHERE id = ?)
                """,
                (stamp, task_id),
            )
        task = complete_operational_task(
            ledger,
            task_id,
            owner=owner,
            disposition="superseded_by_new_forecast",
            result={"current_forecast_id": current.forecast_id},
            usage=estimate.get("usage"),
            now=stamp,
        )
        coalesced = complete_source_change_events(
            ledger,
            question_id=event["question_id"],
            event_ids=sibling_event_ids,
            status="processed",
            disposition="superseded_by_new_forecast",
            forecast_snapshot_id=current.forecast_id,
            now=stamp,
        )
        with ledger._connect() as conn:
            final_event = conn.execute(
                "SELECT * FROM source_change_events WHERE id = ?", (event["id"],)
            ).fetchone()
        return {
            "task": task,
            "event": _event_dict(final_event),
            "superseded": True,
            "coalesced_event_count": coalesced,
        }

    artifact = _validate_estimation_artifact(
        event, estimate, required_event_ids=batch_event_ids
    )
    proposed = estimate.get("proposed_probability_or_distribution")
    if proposed is None:
        proposed = artifact["proposed_probability"]
    rationale = str(estimate.get("rationale") or "").strip()
    if not rationale:
        raise ValidationError("estimator rationale is required")
    transition_source_change_event(
        ledger,
        event["id"],
        to_state="estimated",
        actor=owner,
        reason="structured estimate validated",
        now=stamp,
        allowed_from={"researched"},
    )
    try:
        policy = ledger.get_active_autopilot_policy(event["question_id"])
    except LedgerNotFoundError:
        policy = None
    # A watched source is explicit consent to monitor, but not to auto-commit.
    # Questions without an autopilot policy still receive an estimate and a
    # reviewable proposal; the synthetic policy can never commit by itself.
    policy = policy or {
        "id": None,
        "mode": "propose",
        "materiality_policy": {},
        "guardrail_policy": {},
        "notification_policy": {},
    }
    violations = ledger._autopilot_guardrail_violations(
        policy=policy,
        prior_payload=current.probability_or_distribution,
        proposed_payload=proposed,
        source_snapshots=source_snapshots,
    )
    artifact["guardrail_results"] = {
        "passed": not violations,
        "violations": violations,
    }
    from forecasting.warnings import MATERIAL_MOVE_THRESHOLD, is_material_move

    minimum_delta = float(
        (policy.get("materiality_policy") or {}).get(
            "min_probability_delta", MATERIAL_MOVE_THRESHOLD
        )
    )
    materiality = artifact.get("materiality")
    explicitly_immaterial = (
        isinstance(materiality, dict)
        and (
            materiality.get("changed") is False
            or materiality.get("threshold_triggered") is False
        )
    ) or (
        isinstance(materiality, str)
        and materiality.strip().lower() in {"none", "immaterial", "non_material"}
    )
    estimate_is_material = not explicitly_immaterial and is_material_move(
        current.probability_or_distribution,
        proposed,
        threshold=max(minimum_delta, 0.0),
    )
    pending_proposals = (
        ledger.list_forecast_update_proposals(
            question_id=event["question_id"], status="pending", limit=100
        )
        if estimate_is_material
        else []
    )
    matching = next(
        (
            candidate
            for candidate in pending_proposals
            if candidate.get("prior_forecast_id") == current.forecast_id
            and set(source_snapshot_refs).issubset(
                set(candidate.get("source_snapshot_refs") or [])
            )
        ),
        None,
    )
    conflicting = next(
        (
            candidate
            for candidate in pending_proposals
            if candidate.get("prior_forecast_id") == current.forecast_id
        ),
        None,
    )
    if conflicting and matching is None:
        raise ValidationError(
            f"pending proposal {conflicting['id']} must be reviewed before this event can propose"
        )
    if matching:
        proposal = matching
        model_refs = proposal.get("model_run_refs") or []
        if not model_refs:
            raise ValidationError("matching proposal has no estimator model run")
        model_run = ledger.get_model_run(model_refs[-1])
    else:
        model_run = ledger.record_model_run(
            question_id=event["question_id"],
            model_type="source_change_estimation",
            inputs={
                "source_change_event_id": event["id"],
                "source_change_event_ids": batch_event_ids,
                "prior_forecast_id": current.forecast_id,
                "source_snapshot_refs": source_snapshot_refs,
                "evidence_refs": evidence_refs,
            },
            parameters={
                "materiality_policy": policy["materiality_policy"],
                "guardrail_policy": policy["guardrail_policy"],
            },
            output={
                "proposed_probability_or_distribution": proposed,
                "rationale": rationale,
                "estimation_artifact": artifact,
            },
            diagnostics={"guardrail_violations": violations},
            model_version=str(estimate.get("model_version") or "estimator-worker-v1"),
            prompt_version=estimate.get("prompt_version"),
            evidence_cutoff=artifact["evidence_cutoff"],
        )
    if not estimate_is_material:
        transition_source_change_event(
            ledger,
            event["id"],
            to_state="reconciled",
            actor=owner,
            reason=f"reviewed immaterial (< {minimum_delta:.3f} probability delta)",
            now=stamp,
            allowed_from={"estimated"},
        )
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE source_change_events
                SET status = 'processed', disposition = 'reviewed_immaterial',
                    proposal_id = NULL, forecast_snapshot_id = ?, error = NULL
                WHERE id = ?
                """,
                (current.forecast_id, event["id"]),
            )
            conn.execute(
                """
                UPDATE watched_sources
                SET last_checked_at = ?, last_seen_signature = ? WHERE id = ?
                """,
                (
                    stamp,
                    event["new_state"].get("signature"),
                    event["watched_source_id"],
                ),
            )
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, 'reviewed_immaterial'),
                    ack_note = COALESCE(ack_note, 'auto_close:reviewed_immaterial')
                WHERE id = (SELECT alert_id FROM operational_tasks WHERE id = ?)
                """,
                (stamp, task_id),
            )
        task = complete_operational_task(
            ledger,
            task_id,
            owner=owner,
            disposition="reviewed_immaterial",
            result={
                "source_change_event_id": event["id"],
                "model_run_id": model_run["id"],
                "prior_forecast_id": current.forecast_id,
                "minimum_probability_delta": minimum_delta,
            },
            usage=estimate.get("usage"),
            now=stamp,
        )
        coalesced = complete_source_change_events(
            ledger,
            question_id=event["question_id"],
            event_ids=sibling_event_ids,
            status="processed",
            disposition="reviewed_immaterial",
            forecast_snapshot_id=current.forecast_id,
            now=stamp,
        )
        with ledger._connect() as conn:
            final_event_row = conn.execute(
                "SELECT * FROM source_change_events WHERE id = ?", (event["id"],)
            ).fetchone()
        return {
            "task": task,
            "event": _event_dict(final_event_row),
            "model_run": model_run,
            "proposal": None,
            "forecast_snapshot": None,
            "coalesced_event_count": coalesced,
        }
    proposal = ledger.create_forecast_update_proposal(
            question_id=event["question_id"],
            run_id=None,
            prior_forecast_id=current.forecast_id,
            proposed_probability_or_distribution=proposed,
        rationale=rationale,
        evidence_refs=evidence_refs,
        source_snapshot_refs=source_snapshot_refs,
            model_run_refs=[model_run["id"]],
        )
    snapshot = None
    disposition = "proposed"
    event_state = "proposed"
    if allow_auto_commit and policy["mode"] == "auto_commit" and not violations:
        snapshot = ledger.approve_forecast_update_proposal(
            proposal["id"], reviewed_by=f"estimator:{owner}", status="auto_committed"
        )
        disposition = "auto_committed"
        event_state = "committed"
    elif policy["mode"] == "alert_only" or violations:
        ledger.create_alert(
            severity="high" if violations else "warning",
            scope_type="question",
            scope_ref=event["question_id"],
            reason=f"autopilot_guardrail_review:{proposal['id']}",
            recommended_action=(
                f"Review proposal {proposal['id']} before updating the forecast."
                + (" Guardrails: " + "; ".join(violations) if violations else "")
            ),
            now=stamp,
        )
    else:
        ledger.create_alert(
            severity="info",
            scope_type="question",
            scope_ref=event["question_id"],
            reason=f"autopilot_update_proposed:{proposal['id']}",
            recommended_action=(
                f"Review with `forecast autopilot approve {proposal['id']}` or reject it."
            ),
            now=stamp,
        )
    transition_source_change_event(
        ledger,
        event["id"],
        to_state=event_state,
        actor=owner,
        reason=disposition,
        now=stamp,
        allowed_from={"estimated"},
    )
    with ledger._connect() as conn:
        conn.execute(
            """
            UPDATE source_change_events
            SET status = 'processed', disposition = ?, proposal_id = ?,
                forecast_snapshot_id = ?, error = NULL
            WHERE id = ?
            """,
            (
                disposition,
                proposal["id"],
                snapshot.forecast_id if snapshot else None,
                event["id"],
            ),
        )
        conn.execute(
            """
            UPDATE alert_events
            SET acknowledged_at = COALESCE(acknowledged_at, ?),
                disposition = COALESCE(disposition, ?),
                ack_note = COALESCE(ack_note, 'auto_close:source_event_estimated')
            WHERE id = (SELECT alert_id FROM operational_tasks WHERE id = ?)
            """,
            (stamp, disposition, task_id),
        )
        conn.execute(
            """
            UPDATE watched_sources
            SET last_checked_at = ?, last_seen_signature = ?
            WHERE id = ?
            """,
            (
                stamp,
                event["new_state"].get("signature"),
                event["watched_source_id"],
            ),
        )
    transition_source_change_event(
        ledger,
        event["id"],
        to_state="reconciled",
        actor=owner,
        reason="estimator task completed",
        now=stamp,
        allowed_from={"proposed", "committed"},
    )
    task = complete_operational_task(
        ledger,
        task_id,
        owner=owner,
        disposition=disposition,
        result={
            "source_change_event_id": event["id"],
            "model_run_id": model_run["id"],
            "proposal_id": proposal["id"],
            "forecast_snapshot_id": snapshot.forecast_id if snapshot else None,
        },
        usage=estimate.get("usage"),
        now=stamp,
    )
    coalesced = complete_source_change_events(
        ledger,
        question_id=event["question_id"],
        event_ids=sibling_event_ids,
        status="processed",
        disposition=disposition,
        proposal_id=proposal["id"],
        forecast_snapshot_id=snapshot.forecast_id if snapshot else None,
        now=stamp,
    )
    with ledger._connect() as conn:
        final_event_row = conn.execute(
            "SELECT * FROM source_change_events WHERE id = ?", (event["id"],)
        ).fetchone()
    return {
        "task": task,
        "event": _event_dict(final_event_row),
        "model_run": model_run,
        "proposal": ledger.get_forecast_update_proposal(proposal["id"]),
        "forecast_snapshot": snapshot,
        "coalesced_event_count": coalesced,
    }


def _evidence_refs_from_source_snapshots(
    ledger,
    *,
    question_id: str,
    source_snapshots: list[dict[str, Any]],
) -> list[str]:
    refs: list[str] = []
    for snapshot in source_snapshots:
        for item in (snapshot.get("parsed_values") or {}).get("changed_items") or []:
            content_hash = str(item.get("content_hash") or "")
            with ledger._connect() as conn:
                existing = conn.execute(
                    """
                    SELECT id FROM evidence_items
                    WHERE question_id = ?
                      AND json_extract(metadata, '$.source_snapshot_id') = ?
                      AND json_extract(metadata, '$.content_hash') = ?
                    LIMIT 1
                    """,
                    (question_id, snapshot["id"], content_hash),
                ).fetchone()
            if existing is not None:
                refs.append(existing["id"])
                continue
            source_url = item.get("canonical_url")
            claim = str(item.get("headline") or item.get("summary") or "").strip()
            evidence = ledger.add_evidence(
                question_id=question_id,
                source_or_note=source_url or f"source snapshot {snapshot['id']}",
                source_url=source_url,
                source_name=str(snapshot.get("source_type") or "watched source"),
                source_type=f"adapter:{snapshot.get('source_type') or 'watch'}",
                published_at=item.get("published_at"),
                available_at=item.get("source_observation_time") or snapshot.get("retrieved_at"),
                claim=claim,
                summary=str(item.get("summary") or claim),
                metadata={
                    "source_snapshot_id": snapshot["id"],
                    "content_hash": content_hash,
                    "entry_id": item.get("entry_id"),
                    "old_value": item.get("old_value"),
                    "new_value": item.get("new_value"),
                },
                archive_url_snapshot=False,
            )
            refs.append(evidence.id)
    return list(dict.fromkeys(refs))


def _validate_estimation_artifact(
    event: dict[str, Any],
    estimate: dict[str, Any],
    *,
    required_event_ids: list[str] | None = None,
) -> dict[str, Any]:
    artifact = estimate.get("estimation_artifact")
    if not isinstance(artifact, dict):
        raise ValidationError("estimation_artifact is required")
    missing = [field for field in ESTIMATION_ARTIFACT_FIELDS if field not in artifact]
    if missing:
        raise ValidationError("estimation artifact missing: " + ", ".join(missing))
    updates = artifact.get("evidence_updates")
    if not isinstance(updates, list) or not updates:
        raise ValidationError("estimation artifact requires evidence_updates")
    required = set(required_event_ids or [event["id"]])
    cited = {str(row.get("event_id")) for row in updates if row.get("event_id")}
    missing_events = sorted(required - cited)
    if missing_events:
        raise ValidationError(
            "estimation artifact does not cite source-change event(s): "
            + ", ".join(missing_events)
        )
    for update in updates:
        if str(update.get("event_id")) not in required:
            continue
        for field in ("likelihood_ratio", "correlation_cluster", "reliability_weight"):
            if field not in update:
                raise ValidationError(f"evidence update missing {field}")
    if not isinstance(artifact.get("change_my_mind"), list):
        raise ValidationError("change_my_mind must be a list")
    artifact = dict(artifact)
    artifact["evidence_cutoff"] = parse_timestamp(
        artifact["evidence_cutoff"], field_name="evidence_cutoff"
    )
    return artifact


def run_resolution_finalization_tasks(
    ledger,
    *,
    owner: str,
    now: str | None = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    tasks = claim_operational_tasks(
        ledger,
        owner=owner,
        lane="deterministic_critical",
        now=now,
        limit=limit,
        task_type="finalize_resolution",
    )
    results: list[dict[str, Any]] = []
    for task in tasks:
        try:
            score = ledger.score_question(task["question_id"])
            question = ledger.get_question(task["question_id"])
            postmortem = ledger.create_postmortem(
                question_id=task["question_id"],
                summary="Auto-created after confirmed resolution and scoring.",
                what_happened="The question resolved and its final committed forecast was scored.",
                what_was_expected="See the linked forecast snapshot and score record.",
                lesson=ledger._auto_postmortem_lesson(question, score),
                calibration_adjustment=ledger._auto_postmortem_adjustment(question, score),
            )
            completed = complete_operational_task(
                ledger,
                task["id"],
                owner=owner,
                disposition="resolved_by_resolution",
                result={"score_id": score.id, "postmortem_id": postmortem["id"]},
                now=now,
            )
            results.append(completed)
        except Exception as exc:
            results.append(
                fail_operational_task(
                    ledger,
                    task["id"],
                    owner=owner,
                    error=str(exc),
                    now=now,
                )
            )
    return results


def reconcile_operational_dead_letters(
    ledger,
    *,
    owner: str,
    now: str | None = None,
    transient_retry_delay_seconds: int = 86400,
) -> list[dict[str, Any]]:
    """Reconcile abandoned and superseded warning tasks.

    Threshold-trigger alerts are moved to the paid reforecast route after the
    classifier learned that route. Unavailable sources remain open for operator
    repair while the source monitor owns retries; missing/inactive watches close
    safely as obsolete. Legacy warning tasks are closed when the exact source
    event already has its own worker task.
    Unknown dead letters remain terminal but receive a visible manual disposition.
    """
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    stamp_dt = timestamp_to_datetime(stamp)
    assert stamp_dt is not None
    results: list[dict[str, Any]] = []
    # The hosted estimator now projects source batches into a provider-safe prompt.
    # Give context-overflow dead letters one fresh retry under that bounded payload,
    # and persist a marker so a genuinely incompatible task cannot loop forever.
    with ledger._connect() as conn:
        context_overflow = conn.execute(
            """
            SELECT * FROM operational_tasks
            WHERE task_type = 'process_source_change' AND status = 'dead_letter'
              AND error LIKE 'Context length exceeded:%'
            ORDER BY created_at
            """
        ).fetchall()
        for task in context_overflow:
            prior_result = json_loads(task["result"], {})
            if prior_result.get("recovery") == "bounded_estimator_payload_v1":
                continue
            prior_result["recovery"] = "bounded_estimator_payload_v1"
            conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'pending', attempt_count = 0,
                    disposition = 'recovered_after_estimator_payload_bound',
                    result = ?, error = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, available_at = ?, updated_at = ?
                WHERE id = ? AND status = 'dead_letter'
                """,
                (json_dumps(prior_result), stamp, stamp, task["id"]),
            )
            _transition_source_change_event_conn(
                conn,
                task["source_change_event_id"],
                to_state="detected",
                actor=owner,
                reason="retry after bounded estimator payload deployment",
                now=stamp,
                allowed_from={"failed"},
            )
            conn.execute(
                """
                UPDATE source_change_events
                SET status = 'pending', disposition = 'estimator_required', error = NULL,
                    claim_owner = NULL, claim_expires_at = NULL
                WHERE id = ?
                """,
                (task["source_change_event_id"],),
            )
            results.append(
                {"task_id": task["id"], "action": "retry_bounded_estimator_payload"}
            )
    # One-time replay for the legacy typed numeric envelope bug. Reuse the last
    # persisted estimate so recovery neither re-polls the source nor pays for a
    # sixth identical model call.
    with ledger._connect() as conn:
        legacy_numeric = conn.execute(
            """
            SELECT * FROM operational_tasks
            WHERE task_type = 'process_source_change' AND status = 'dead_letter'
              AND error LIKE 'distribution value for ''type'' must be a number%'
            ORDER BY created_at
            """
        ).fetchall()
        for task in legacy_numeric:
            model_run = conn.execute(
                """
                SELECT output, model_version FROM model_runs
                WHERE model_type = 'source_change_estimation'
                  AND json_extract(inputs, '$.source_change_event_id') = ?
                ORDER BY created_at DESC, rowid DESC LIMIT 1
                """,
                (task["source_change_event_id"],),
            ).fetchone()
            estimate = json_loads(model_run["output"], {}) if model_run else {}
            if not estimate:
                continue
            estimate["model_version"] = model_run["model_version"] or "replayed-estimator"
            conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'pending', attempt_count = 0,
                    disposition = 'replay_after_numeric_envelope_fix',
                    result = ?, error = NULL, lease_owner = NULL,
                    lease_expires_at = NULL, available_at = ?, updated_at = ?
                WHERE id = ? AND status = 'dead_letter'
                """,
                (json_dumps({"replay_estimate": estimate}), stamp, stamp, task["id"]),
            )
            _transition_source_change_event_conn(
                conn,
                task["source_change_event_id"],
                to_state="detected",
                actor=owner,
                reason="replay persisted estimate after numeric envelope normalization fix",
                now=stamp,
                allowed_from={"failed"},
            )
            conn.execute(
                """
                UPDATE source_change_events
                SET status = 'pending', disposition = 'estimator_required', error = NULL,
                    claim_owner = NULL, claim_expires_at = NULL
                WHERE id = ?
                """,
                (task["source_change_event_id"],),
            )
            results.append({"task_id": task["id"], "action": "replay_numeric_estimate"})
    # Old trigger tasks may have been recovered into the urgent queue just before
    # the estimator route created the question-level work that now owns them.
    # Reconcile those duplicates instead of making a second worker reforecast the
    # same question. A terminal immutable source event is also sufficient proof
    # that the original trigger received a disposition.
    with ledger._connect() as conn:
        recovered = conn.execute(
            """
            SELECT task.* FROM operational_tasks AS task
            WHERE task.status = 'pending'
              AND task.disposition = 'recovered_to_reforecast'
            ORDER BY task.available_at, task.id
            """
        ).fetchall()
        for task in recovered:
            estimator_owner = conn.execute(
                """
                SELECT candidate.id FROM operational_tasks AS candidate
                JOIN alert_events AS alert ON alert.id = candidate.alert_id
                WHERE candidate.question_id = ? AND candidate.id != ?
                  AND candidate.status IN ('pending', 'leased', 'awaiting_human')
                  AND candidate.lane = 'normal_reforecast'
                  AND alert.reason LIKE 'forecast_estimation_required:%'
                LIMIT 1
                """,
                (task["question_id"], task["id"]),
            ).fetchone()
            terminal_event = conn.execute(
                """
                SELECT id, disposition FROM source_change_events
                WHERE question_id = ? AND status IN ('processed', 'failed')
                  AND detected_at >= ?
                ORDER BY detected_at DESC LIMIT 1
                """,
                (task["question_id"], task["available_at"]),
            ).fetchone()
            if estimator_owner is None and terminal_event is None:
                continue
            disposition = (
                "coalesced_to_estimator"
                if estimator_owner is not None
                else str(terminal_event["disposition"] or "source_event_terminal")
            )
            result = {
                "reconciled_by": owner,
                "estimator_task_id": estimator_owner["id"] if estimator_owner else None,
                "source_change_event_id": terminal_event["id"] if terminal_event else None,
            }
            conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'completed', disposition = ?, result = ?, error = NULL,
                    completed_at = ?, updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (disposition, json_dumps(result), stamp, stamp, task["id"]),
            )
            conn.execute(
                """
                UPDATE alert_events
                SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, ?),
                    ack_note = COALESCE(ack_note, 'auto_close:recovered_trigger_reconciled')
                WHERE id = ?
                """,
                (stamp, disposition, task["alert_id"]),
            )
            results.append(
                {"task_id": task["id"], "action": "reconcile_recovered_trigger", **result}
            )
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT task.*, alert.reason, alert.acknowledged_at
            FROM operational_tasks AS task
            LEFT JOIN alert_events AS alert ON alert.id = task.alert_id
            WHERE task.task_type = 'resolve_warning' AND (
                (task.status = 'dead_letter'
                 AND COALESCE(task.disposition, '') != 'manual_dead_letter_review')
                OR (
                    task.status = 'pending'
                    AND alert.reason LIKE 'watched_source_unavailable:%'
                )
                OR (
                    task.status = 'pending'
                    AND alert.reason = 'domain_error_profile_review'
                )
                OR (
                    task.status = 'pending'
                    AND alert.reason LIKE 'watched_source_changed:%'
                    AND EXISTS (
                        SELECT 1 FROM operational_tasks AS source_task
                        WHERE source_task.alert_id = task.alert_id
                          AND source_task.task_type = 'process_source_change'
                          AND source_task.id != task.id
                    )
                )
                OR (
                    task.status = 'leased' AND task.lease_expires_at <= ?
                    AND alert.acknowledged_at IS NOT NULL
                )
            )
            ORDER BY task.available_at, task.id
            """,
            (stamp,),
        ).fetchall()
    for row in rows:
        reason = str(row["reason"] or "")
        if row["acknowledged_at"]:
            with ledger._connect() as conn:
                conn.execute(
                    """
                    UPDATE operational_tasks
                    SET status = 'completed', disposition = 'alert_closed_elsewhere',
                        completed_at = COALESCE(completed_at, ?),
                        lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE id = ? AND status IN ('pending', 'leased', 'dead_letter')
                    """,
                    (stamp, stamp, row["id"]),
                )
            results.append({"task_id": row["id"], "action": "closed_obsolete"})
            continue
        if reason.startswith(("trigger_fired:", "learned_error_update_required:")):
            with ledger._connect() as conn:
                conn.execute(
                    """
                    UPDATE operational_tasks
                    SET status = 'pending', lane = 'urgent_forecast', priority = MAX(priority, 90),
                        attempt_count = 0, disposition = 'recovered_to_reforecast', error = NULL,
                        lease_owner = NULL, lease_expires_at = NULL, available_at = ?, updated_at = ?
                    WHERE id = ? AND status IN ('leased', 'dead_letter')
                    """,
                    (stamp, stamp, row["id"]),
                )
            results.append({"task_id": row["id"], "action": "recovered_to_reforecast"})
            continue
        if reason == "domain_error_profile_review":
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE alert_events SET severity = 'info' WHERE id = ?",
                    (row["alert_id"],),
                )
                conn.execute(
                    """
                    UPDATE operational_tasks
                    SET status = 'completed', disposition = 'profile_digest_visible',
                        completed_at = COALESCE(completed_at, ?), error = NULL,
                        lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                    WHERE id = ? AND status IN ('pending', 'leased', 'dead_letter')
                    """,
                    (stamp, stamp, row["id"]),
                )
            results.append({"task_id": row["id"], "action": "profile_digest_visible"})
            continue
        if reason.startswith("watched_source_changed:"):
            with ledger._connect() as conn:
                source_worker = conn.execute(
                    """
                    SELECT 1 FROM operational_tasks
                    WHERE alert_id = ? AND task_type = 'process_source_change' AND id != ?
                    LIMIT 1
                    """,
                    (row["alert_id"], row["id"]),
                ).fetchone()
                if source_worker is not None:
                    conn.execute(
                        """
                        UPDATE operational_tasks
                        SET status = 'completed', disposition = 'source_event_worker_owns',
                            completed_at = COALESCE(completed_at, ?), error = NULL,
                            lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                        WHERE id = ? AND status IN ('pending', 'leased', 'dead_letter')
                        """,
                        (stamp, stamp, row["id"]),
                    )
            if source_worker is not None:
                results.append({"task_id": row["id"], "action": "source_event_worker_owns"})
                continue
        if reason.startswith("watched_source_unavailable:"):
            watch_id = reason.split(":", 1)[1]
            with ledger._connect() as conn:
                watch = conn.execute(
                    "SELECT status FROM watched_sources WHERE id = ?", (watch_id,)
                ).fetchone()
                if watch is None or watch["status"] != "active":
                    conn.execute(
                        """
                        UPDATE alert_events
                        SET acknowledged_at = ?, disposition = 'source_inactive',
                            ack_note = 'auto_close:watched_source_inactive'
                        WHERE id = ? AND acknowledged_at IS NULL
                        """,
                        (stamp, row["alert_id"]),
                    )
                    conn.execute(
                        """
                        UPDATE operational_tasks
                        SET status = 'completed', disposition = 'source_inactive',
                            completed_at = ?, updated_at = ?
                        WHERE id = ? AND status = 'dead_letter'
                        """,
                        (stamp, stamp, row["id"]),
                    )
                    action = "closed_inactive_source"
                else:
                    conn.execute(
                        """
                        UPDATE operational_tasks
                        SET status = 'completed', disposition = 'source_monitor_retrying',
                            completed_at = COALESCE(completed_at, ?), error = NULL,
                            lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                        WHERE id = ? AND status IN ('pending', 'leased', 'dead_letter')
                        """,
                        (stamp, stamp, row["id"]),
                    )
                    conn.execute(
                        "UPDATE alert_events SET disposition = 'source_monitor_retrying' WHERE id = ?",
                        (row["alert_id"],),
                    )
                    action = "source_monitor_retrying"
            results.append({"task_id": row["id"], "action": action, "watch_id": watch_id})
            continue
        with ledger._connect() as conn:
            conn.execute(
                """
                UPDATE operational_tasks SET disposition = 'manual_dead_letter_review', updated_at = ?
                WHERE id = ? AND status = 'dead_letter'
                """,
                (stamp, row["id"]),
            )
        results.append({"task_id": row["id"], "action": "manual_dead_letter_review"})
    return results


def heartbeat_operational_task(
    ledger,
    task_id: str,
    *,
    owner: str,
    now: str | None = None,
    lease_seconds: int = 300,
) -> dict[str, Any]:
    stamp = now or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    expires = (now_dt + timedelta(seconds=max(int(lease_seconds), 1))).isoformat().replace(
        "+00:00", "Z"
    )
    with ledger._connect() as conn:
        updated = conn.execute(
            """
            UPDATE operational_tasks SET lease_expires_at = ?, updated_at = ?
            WHERE id = ? AND status = 'leased' AND lease_owner = ?
              AND lease_expires_at > ?
            """,
            (expires, stamp, task_id, owner, stamp),
        )
        if updated.rowcount != 1:
            raise ValueError("operational task lease is missing, expired, or owned by another worker")
        row = conn.execute("SELECT * FROM operational_tasks WHERE id = ?", (task_id,)).fetchone()
    return _task_dict(row)


def fail_operational_task(
    ledger,
    task_id: str,
    *,
    owner: str,
    error: str,
    usage: dict[str, Any] | None = None,
    now: str | None = None,
    retry_delay_seconds: int = 60,
    retryable: bool = True,
) -> dict[str, Any]:
    stamp = now or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM operational_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None or row["status"] != "leased" or row["lease_owner"] != owner:
            raise ValueError("operational task is not leased by this worker")
        delay = max(int(retry_delay_seconds), 0)
        if retry_delay_seconds == 60:
            # Default retries spread out exponentially; explicit caller delays
            # (including zero in tests/manual recovery) remain exact.
            delay = min(60 * (4 ** max(int(row["attempt_count"] or 1) - 1, 0)), 21600)
        available_at = (now_dt + timedelta(seconds=delay)).isoformat().replace("+00:00", "Z")
        exhausted = (not retryable) or (
            int(row["attempt_count"] or 0) >= int(row["max_attempts"] or 1)
        )
        status = "dead_letter" if exhausted else "pending"
        disposition = (
            "invalid_payload_dead_letter"
            if exhausted and not retryable
            else "failed_dead_letter"
            if exhausted
            else "failed_retrying"
        )
        conn.execute(
            """
            UPDATE operational_tasks
            SET status = ?, disposition = ?, error = ?, available_at = ?,
                lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'leased' AND lease_owner = ?
            """,
            (status, disposition, error, available_at, stamp, task_id, owner),
        )
        conn.execute(
            """
            UPDATE operational_task_attempts
            SET finished_at = ?, outcome = ?, error = ?
            WHERE task_id = ? AND owner = ? AND finished_at IS NULL
            """,
            (stamp, disposition, error, task_id, owner),
        )
        _record_attempt_usage(conn, task_id=task_id, owner=owner, usage=usage)
        if exhausted and row["source_change_event_id"]:
            _transition_source_change_event_conn(
                conn,
                row["source_change_event_id"],
                to_state="failed",
                actor=owner,
                reason="task exhausted retries",
                now=stamp,
            )
            conn.execute(
                "UPDATE source_change_events SET status = 'failed', error = ? "
                "WHERE id = ? AND status = 'pending'",
                (error, row["source_change_event_id"]),
            )
        updated = conn.execute(
            "SELECT * FROM operational_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return _task_dict(updated)


def defer_source_change_events_for_estimation(
    ledger,
    *,
    question_id: str,
    event_ids: list[str],
    reason: str = "estimator_required",
    now: str | None = None,
) -> int:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        clauses = ["question_id = ?", "status = 'pending'"]
        params: list[Any] = [question_id]
        if not event_ids:
            return 0
        clauses.append(f"id IN ({','.join('?' for _ in event_ids)})")
        params.extend(event_ids)
        events = conn.execute(
            "SELECT id, old_state, new_state FROM source_change_events WHERE "
            + " AND ".join(clauses),
            params,
        ).fetchall()
        for event in events:
            _transition_source_change_event_conn(
                conn,
                event["id"],
                to_state="triaged",
                actor="autopilot",
                reason=reason,
                now=stamp,
                allowed_from={"detected", "triaged"},
            )
            conn.execute(
                "UPDATE source_change_events SET disposition = ? WHERE id = ?",
                (reason, event["id"]),
            )
            conn.execute(
                """
                UPDATE operational_tasks
                SET lane = 'normal_reforecast', priority = 80, status = 'pending',
                    disposition = ?, lease_owner = NULL, lease_expires_at = NULL,
                    updated_at = ?
                WHERE source_change_event_id = ? AND status IN ('pending', 'leased')
                """,
                (reason, stamp, event["id"]),
            )
    return len(events)


def complete_source_change_events(
    ledger,
    *,
    question_id: str,
    event_ids: list[str],
    status: str,
    disposition: str,
    proposal_id: str | None = None,
    forecast_snapshot_id: str | None = None,
    error: str | None = None,
    now: str | None = None,
) -> int:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        clauses = ["question_id = ?", "status = 'pending'"]
        params: list[Any] = [question_id]
        if not event_ids:
            return 0
        clauses.append(f"id IN ({','.join('?' for _ in event_ids)})")
        params.extend(event_ids)
        events = conn.execute(
            "SELECT id, old_state, new_state FROM source_change_events WHERE "
            + " AND ".join(clauses),
            params,
        ).fetchall()
        failure_parent_id = events[0]["id"] if status == "failed" and len(events) > 1 else None
        for index, event in enumerate(events):
            is_failure_child = failure_parent_id is not None and index > 0
            event_status = "processed" if is_failure_child else status
            event_disposition = (
                "source_failure_child"
                if is_failure_child
                else f"{disposition}_batch"
                if failure_parent_id is not None
                else disposition
            )
            event_error = None if is_failure_child else error
            task = conn.execute(
                "SELECT alert_id FROM operational_tasks WHERE source_change_event_id = ? LIMIT 1",
                (event["id"],),
            ).fetchone()
            conn.execute(
                """
                UPDATE source_change_events
                SET status = ?, disposition = ?, proposal_id = ?,
                    forecast_snapshot_id = ?, error = ?,
                    metadata = CASE WHEN ? IS NULL THEN metadata
                        ELSE json_set(COALESCE(metadata, '{}'), '$.source_failure_parent_id', ?)
                    END
                WHERE id = ? AND status = 'pending'
                """,
                (
                    event_status,
                    event_disposition,
                    proposal_id,
                    forecast_snapshot_id,
                    event_error,
                    failure_parent_id if is_failure_child else None,
                    failure_parent_id,
                    event["id"],
                ),
            )
            if status == "processed":
                new_signature = json_loads(event["new_state"], {}).get("signature")
                conn.execute(
                    """
                    UPDATE watched_sources
                    SET last_checked_at = ?, last_seen_signature = ?
                    WHERE id = (
                        SELECT watched_source_id FROM source_change_events WHERE id = ?
                    )
                    """,
                    (stamp, new_signature, event["id"]),
                )
            terminal_state = (
                "failed"
                if event_status == "failed"
                else "committed"
                if disposition == "auto_committed"
                else "proposed"
                if disposition == "proposed"
                else "reconciled"
            )
            _transition_source_change_event_conn(
                conn,
                event["id"],
                to_state=terminal_state,
                actor="source-change-consumer",
                reason=event_disposition,
                now=stamp,
            )
            if terminal_state in {"committed", "proposed"}:
                _transition_source_change_event_conn(
                    conn,
                    event["id"],
                    to_state="reconciled",
                    actor="source-change-consumer",
                    reason="consumer disposition recorded",
                    now=stamp,
                )
            conn.execute(
                """
                UPDATE operational_tasks SET status = ?, disposition = ?, error = ?,
                    lease_owner = NULL, lease_expires_at = NULL, completed_at = ?, updated_at = ?
                WHERE source_change_event_id = ? AND status IN ('pending', 'leased')
                """,
                (
                    "completed" if event_status == "processed" else "failed",
                    event_disposition,
                    event_error,
                    stamp,
                    stamp,
                    event["id"],
                ),
            )
            conn.execute(
                """
                UPDATE operational_task_attempts SET finished_at = ?, outcome = ?, error = ?
                WHERE task_id IN (
                    SELECT id FROM operational_tasks WHERE source_change_event_id = ?
                ) AND finished_at IS NULL
                """,
                (stamp, event_disposition, event_error, event["id"]),
            )
            if task is not None and task["alert_id"]:
                old_signature = str(json_loads(event["old_state"], {}).get("signature") or "")
                new_signature = str(json_loads(event["new_state"], {}).get("signature") or "")
                if old_signature.startswith("missing:") and not new_signature.startswith("missing:"):
                    alert_disposition = "resolved_by_source_recovery"
                elif disposition == "auto_committed":
                    alert_disposition = "resolved_by_forecast_update"
                elif disposition in {
                    "no_material_change",
                    "rechecked_without_policy",
                    "reviewed_immaterial",
                }:
                    alert_disposition = "reviewed_immaterial"
                elif disposition == "insufficient_content":
                    alert_disposition = "insufficient_content"
                elif event_status == "failed":
                    alert_disposition = "source_observation_failed"
                else:
                    alert_disposition = "deferred"
                conn.execute(
                    """
                    UPDATE alert_events
                    SET acknowledged_at = COALESCE(acknowledged_at, ?),
                        ack_note = COALESCE(ack_note, 'auto_close:source_event_disposition'),
                        disposition = COALESCE(disposition, ?)
                    WHERE id = ? AND acknowledged_at IS NULL
                    """,
                    (stamp, alert_disposition, task["alert_id"]),
                )
    return len(events)


def set_operational_lane_policy(
    ledger,
    lane: str,
    *,
    daily_claim_budget: int,
    slo_minutes: int,
    enabled: bool = True,
) -> dict[str, Any]:
    if daily_claim_budget < 0 or slo_minutes <= 0:
        raise ValueError("lane budget must be non-negative and SLO minutes must be positive")
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT INTO operational_lane_policies
                (lane, daily_claim_budget, slo_minutes, enabled)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(lane) DO UPDATE SET
                daily_claim_budget = excluded.daily_claim_budget,
                slo_minutes = excluded.slo_minutes,
                enabled = excluded.enabled
            """,
            (lane, int(daily_claim_budget), int(slo_minutes), 1 if enabled else 0),
        )
        row = conn.execute(
            "SELECT * FROM operational_lane_policies WHERE lane = ?", (lane,)
        ).fetchone()
    data = dict(row)
    data["enabled"] = bool(data["enabled"])
    return data


def escalate_overdue_high_severity_tasks(
    ledger, *, now: str | None = None
) -> dict[str, Any]:
    """Assign breached urgent work to a durable human escalation owner."""
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    escalated: list[dict[str, Any]] = []
    with ledger._connect() as conn:
        rows = conn.execute(
            """
            SELECT task.id, task.question_id, task.alert_id, task.result,
                   COALESCE(NULLIF(question.owner, ''), 'human:forecast-duty') AS owner
            FROM operational_tasks task
            JOIN alert_events alert ON alert.id = task.alert_id
            LEFT JOIN forecast_questions question ON question.id = task.question_id
            WHERE alert.acknowledged_at IS NULL
              AND alert.severity IN ('critical', 'high')
              AND task.due_at IS NOT NULL AND task.due_at <= ?
              AND task.escalated_at IS NULL
              AND (task.status = 'pending' OR
                   (task.status = 'leased' AND task.lease_expires_at <= ?))
            ORDER BY task.available_at ASC
            """,
            (stamp, stamp),
        ).fetchall()
        for row in rows:
            result = json_loads(row["result"], {})
            result["escalation"] = {
                "owner": row["owner"],
                "escalated_at": stamp,
                "reason": "high_severity_slo_breach",
            }
            conn.execute(
                """
                UPDATE operational_tasks
                SET status = 'awaiting_human', escalation_owner = ?, escalated_at = ?,
                    disposition = 'human_escalation_required', result = ?,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE id = ? AND escalated_at IS NULL
                """,
                (row["owner"], stamp, json_dumps(result), stamp, row["id"]),
            )
            conn.execute(
                """
                UPDATE operational_task_attempts
                SET finished_at = ?, outcome = 'human_escalation_required',
                    error = COALESCE(error, 'worker execution stopped after human escalation')
                WHERE task_id = ? AND finished_at IS NULL
                """,
                (stamp, row["id"]),
            )
            escalated.append(
                {
                    "task_id": row["id"],
                    "alert_id": row["alert_id"],
                    "owner": row["owner"],
                }
            )
    return {"escalated": escalated, "escalated_count": len(escalated)}


def suspend_unhealthy_watched_sources(
    ledger,
    *,
    now: str | None = None,
    failure_threshold: int = 3,
    low_yield_min_events: int = 5,
    low_yield_ratio: float = 0.95,
) -> list[dict[str, Any]]:
    """Suspend exact watches that repeatedly fail or emit signature-only deltas."""
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    cutoff_dt = timestamp_to_datetime(stamp)
    assert cutoff_dt is not None
    cutoff = (cutoff_dt - timedelta(days=7)).isoformat().replace("+00:00", "Z")
    suspended: list[dict[str, Any]] = []
    with ledger._connect() as conn:
        watches = conn.execute(
            """
            SELECT watch.id, watch.scope_type, watch.scope_ref, watch.source,
                   watch.source_type, watch.metadata,
                   SUM(CASE WHEN event.status = 'failed'
                         AND event.disposition = 'source_observation_failed'
                         THEN 1 ELSE 0 END) AS failures,
                   SUM(CASE WHEN json_extract(snapshot.parsed_values, '$.parser_version')
                         = 'changed-items-v1' AND event.status != 'pending'
                         THEN 1 ELSE 0 END) AS current_parser_terminal,
                   SUM(CASE WHEN json_extract(snapshot.parsed_values, '$.parser_version')
                         = 'changed-items-v1'
                         AND event.disposition LIKE 'insufficient_content%'
                         THEN 1 ELSE 0 END) AS insufficient
            FROM watched_sources watch
            LEFT JOIN source_change_events event
              ON event.watched_source_id = watch.id AND event.detected_at >= ?
            LEFT JOIN source_snapshots snapshot ON snapshot.id = event.new_source_snapshot_id
            WHERE watch.status = 'active'
            GROUP BY watch.id
            """,
            (cutoff,),
        ).fetchall()
        for row in watches:
            failures = int(row["failures"] or 0)
            terminal = int(row["current_parser_terminal"] or 0)
            insufficient = int(row["insufficient"] or 0)
            reason = None
            if failures >= max(int(failure_threshold), 1):
                reason = "repeated_source_observation_failure"
            elif (
                terminal >= max(int(low_yield_min_events), 1)
                and insufficient / max(terminal, 1) >= float(low_yield_ratio)
            ):
                reason = "persistently_insufficient_content"
            if not reason:
                continue
            metadata = json_loads(row["metadata"], {})
            metadata["suspension"] = {
                "reason": reason,
                "suspended_at": stamp,
                "failures_7d": failures,
                "current_parser_terminal_7d": terminal,
                "insufficient_7d": insufficient,
            }
            conn.execute(
                "UPDATE watched_sources SET status = 'inactive', metadata = ? "
                "WHERE id = ? AND status = 'active'",
                (json_dumps(metadata), row["id"]),
            )
            suspended.append(
                {
                    "watch_id": row["id"],
                    "scope_type": row["scope_type"],
                    "scope_ref": row["scope_ref"],
                    "source": row["source"],
                    "source_type": row["source_type"],
                    "reason": reason,
                }
            )
    for row in suspended:
        ledger.create_alert(
            severity="high",
            scope_type=row["scope_type"],
            scope_ref=row["scope_ref"] or row["watch_id"],
            reason=f"watched_source_suspended:{row['watch_id']}",
            recommended_action=(
                f"Repair or replace the suspended {row['source_type']} watch "
                f"{row['source']} ({row['reason']}); then re-enable it."
            ),
            now=stamp,
        )
    return suspended


def act_on_human_task(
    ledger,
    task_id: str,
    *,
    action: str,
    owner: str = "human:forecast-duty",
    defer_hours: float = 24.0,
    note: str | None = None,
    now: str | None = None,
) -> dict[str, Any]:
    """Acknowledge, defer, close, or return a human task to reforecast work."""
    if action not in {"acknowledge", "defer", "resolve", "reforecast"}:
        raise ValidationError("human task action must be acknowledge, defer, resolve, or reforecast")
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    stamp_dt = timestamp_to_datetime(stamp)
    assert stamp_dt is not None
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM operational_tasks WHERE id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise LedgerNotFoundError(f"operational task not found: {task_id}")
        if row["status"] != "awaiting_human":
            raise ValidationError("human task is no longer awaiting_human")
        result = json_loads(row["result"], {})
        result["human_action"] = {
            "action": action,
            "owner": owner,
            "at": stamp,
            "note": note,
        }
        if action == "defer":
            available = (
                stamp_dt + timedelta(hours=max(float(defer_hours), 0.0))
            ).isoformat().replace("+00:00", "Z")
            conn.execute(
                """
                UPDATE operational_tasks SET available_at = ?, due_at = ?,
                    disposition = 'human_deferred', result = ?, updated_at = ?
                WHERE id = ?
                """,
                (available, available, json_dumps(result), stamp, task_id),
            )
        elif action == "reforecast":
            conn.execute(
                """
                UPDATE operational_tasks SET status = 'pending', lane = 'urgent_forecast',
                    priority = MAX(priority, 95), available_at = ?,
                    disposition = 'human_reforecast_requested', result = ?,
                    escalation_owner = NULL, escalated_at = NULL,
                    lease_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE id = ?
                """,
                (stamp, json_dumps(result), stamp, task_id),
            )
        else:
            disposition = (
                "human_acknowledged" if action == "acknowledge" else "human_resolved"
            )
            conn.execute(
                """
                UPDATE operational_tasks SET status = 'completed', disposition = ?,
                    result = ?, completed_at = ?, updated_at = ?,
                    lease_owner = NULL, lease_expires_at = NULL
                WHERE id = ?
                """,
                (disposition, json_dumps(result), stamp, stamp, task_id),
            )
            conn.execute(
                """
                UPDATE alert_events SET acknowledged_at = COALESCE(acknowledged_at, ?),
                    disposition = COALESCE(disposition, ?),
                    ack_note = COALESCE(ack_note, ?)
                WHERE id = ?
                """,
                (
                    stamp,
                    disposition,
                    f"{owner}:{action}" + (f":{note}" if note else ""),
                    row["alert_id"],
                ),
            )
        final = conn.execute(
            "SELECT * FROM operational_tasks WHERE id = ?", (task_id,)
        ).fetchone()
    return _task_dict(final)


def operational_cockpit(ledger, *, now: str | None = None) -> dict[str, Any]:
    stamp = now or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    day_start = f"{stamp[:10]}T00:00:00Z"
    with ledger._connect() as conn:
        task_rows = conn.execute(
            """
            SELECT lane, status, available_at, created_at, claimed_at, completed_at
            FROM operational_tasks
            """
        ).fetchall()
        policies = conn.execute(
            "SELECT * FROM operational_lane_policies ORDER BY slo_minutes ASC"
        ).fetchall()
        attempts = conn.execute(
            "SELECT * FROM operational_task_attempts WHERE claimed_at >= ?",
            (day_start,),
        ).fetchall()
        all_attempts = conn.execute(
            "SELECT * FROM operational_task_attempts"
        ).fetchall()
        coverage = conn.execute(
            """
            SELECT
              SUM(CASE WHEN q.status = 'active' THEN 1 ELSE 0 END) AS active_questions,
              SUM(CASE WHEN q.status = 'active' AND q.current_forecast_id IS NULL THEN 1 ELSE 0 END)
                AS active_without_forecast,
              SUM(CASE WHEN q.status = 'active' AND NOT EXISTS (
                    SELECT 1 FROM scheduled_reviews r
                    WHERE r.scope_type = 'question' AND r.scope_ref = q.id AND r.enabled = 1
                  ) THEN 1 ELSE 0 END) AS active_without_schedule,
              SUM(CASE WHEN q.status = 'active' AND NOT EXISTS (
                    SELECT 1 FROM watched_sources w
                    WHERE w.scope_type = 'question' AND w.scope_ref = q.id AND w.status = 'active'
                  ) THEN 1 ELSE 0 END) AS active_without_watch,
              SUM(CASE WHEN q.status = 'resolved' AND EXISTS (
                    SELECT 1 FROM scheduled_reviews r
                    WHERE r.scope_type = 'question' AND r.scope_ref = q.id AND r.enabled = 1
                  ) THEN 1 ELSE 0 END) AS resolved_with_schedule
            FROM forecast_questions q
            """
        ).fetchone()
        source_counts = conn.execute(
            "SELECT status, COUNT(*) AS n FROM source_change_events GROUP BY status"
        ).fetchall()
        source_lifecycle = conn.execute(
            """
            SELECT
              SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
              SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed,
              SUM(CASE WHEN status = 'processed' THEN 1 ELSE 0 END) AS processed,
              SUM(CASE WHEN status = 'pending' AND disposition = 'estimator_required' THEN 1 ELSE 0 END)
                AS estimator_required,
              SUM(CASE WHEN status = 'pending' AND NOT EXISTS (
                    SELECT 1 FROM operational_tasks task
                    WHERE task.source_change_event_id = source_change_events.id
                      AND task.status IN ('pending', 'leased', 'awaiting_human')
                  ) THEN 1 ELSE 0 END) AS stranded,
              SUM(CASE WHEN status = 'failed' AND EXISTS (
                    SELECT 1 FROM operational_tasks task
                    JOIN alert_events alert ON alert.id = task.alert_id
                    WHERE task.source_change_event_id = source_change_events.id
                      AND task.status IN ('pending', 'leased', 'awaiting_human')
                      AND alert.acknowledged_at IS NULL
                  ) THEN 1 ELSE 0 END) AS open_failed,
              SUM(CASE WHEN status = 'failed' AND NOT EXISTS (
                    SELECT 1 FROM operational_tasks task
                    JOIN alert_events alert ON alert.id = task.alert_id
                    WHERE task.source_change_event_id = source_change_events.id
                      AND task.status IN ('pending', 'leased')
                      AND alert.acknowledged_at IS NULL
                  ) THEN 1 ELSE 0 END) AS terminal_failed,
              MIN(CASE WHEN status = 'pending' THEN detected_at END) AS oldest_pending_at
            FROM source_change_events
            """
        ).fetchone()
        question_modes = conn.execute(
            "SELECT id, status, metadata FROM forecast_questions"
        ).fetchall()
        scheduled_question_ids = {
            row["scope_ref"]
            for row in conn.execute(
                "SELECT scope_ref FROM scheduled_reviews "
                "WHERE enabled = 1 AND scope_type = 'question'"
            ).fetchall()
        }
        resolution_schedule_ids = {
            row["scope_ref"]
            for row in conn.execute(
                "SELECT scope_ref FROM scheduled_reviews WHERE enabled = 1 "
                "AND scope_type = 'question' AND trigger_reason = 'resolution_only'"
            ).fetchall()
        }
        watched_question_ids = {
            row["scope_ref"]
            for row in conn.execute(
                "SELECT scope_ref FROM watched_sources WHERE status = 'active' "
                "AND scope_type = 'question'"
            ).fetchall()
        }
        history_rows = conn.execute(
            """
            WITH days AS (
                SELECT substr(created_at, 1, 10) AS day, COUNT(*) AS arrivals, 0 AS services
                FROM operational_tasks WHERE lane != 'human_review' GROUP BY day
                UNION ALL
                SELECT substr(completed_at, 1, 10) AS day, 0, COUNT(*)
                FROM operational_tasks
                WHERE completed_at IS NOT NULL AND lane != 'human_review' GROUP BY day
            ), costs AS (
                SELECT substr(claimed_at, 1, 10) AS day, SUM(cost_usd) AS cost_usd,
                       SUM(model_calls) AS model_calls, SUM(source_calls) AS source_calls
                FROM operational_task_attempts GROUP BY day
            )
            SELECT days.day, SUM(days.arrivals) AS arrivals, SUM(days.services) AS services,
                   COALESCE(costs.cost_usd, 0) AS cost_usd,
                   COALESCE(costs.model_calls, 0) AS model_calls,
                   COALESCE(costs.source_calls, 0) AS source_calls
            FROM days LEFT JOIN costs ON costs.day = days.day
            GROUP BY days.day ORDER BY days.day DESC LIMIT 30
            """
        ).fetchall()
        rate_limits = conn.execute(
            "SELECT * FROM source_token_buckets ORDER BY bucket"
        ).fetchall()
        high_alert_rows = conn.execute(
            """
            SELECT a.id, a.created_at,
                   MAX(CASE WHEN task.status IN ('pending', 'leased') THEN 1 ELSE 0 END)
                       AS has_active_task,
                   MAX(CASE WHEN task.status = 'leased' THEN 1 ELSE 0 END) AS has_lease,
                   MIN(CASE WHEN task.status IN ('pending', 'leased', 'awaiting_human')
                            THEN task.due_at END)
                       AS due_at,
                   MAX(CASE WHEN task.status = 'awaiting_human' THEN 1 ELSE 0 END)
                       AS is_awaiting_human,
                   MAX(CASE WHEN task.escalation_owner IS NOT NULL THEN 1 ELSE 0 END)
                       AS has_escalation_owner,
                   MAX(CASE WHEN task.status = 'dead_letter' OR task.escalated_at IS NOT NULL
                            THEN 1 ELSE 0 END) AS has_human_escalation
            FROM alert_events a
            LEFT JOIN operational_tasks task ON task.alert_id = a.id
            WHERE a.acknowledged_at IS NULL AND a.severity IN ('critical', 'high')
            GROUP BY a.id, a.created_at
            ORDER BY a.created_at ASC
            """
        ).fetchall()
        source_flow_rows = conn.execute(
            """
            SELECT event.id, event.detected_at, event.status, event.disposition,
                   snapshot.source_type, snapshot.source_url, snapshot.adapter_version,
                   snapshot.parsed_values,
                   MIN(CASE WHEN transition.to_state IN
                       ('reconciled', 'failed', 'superseded')
                       THEN transition.created_at END) AS terminal_at
            FROM source_change_events event
            LEFT JOIN source_snapshots snapshot ON snapshot.id = event.new_source_snapshot_id
            LEFT JOIN source_change_event_transitions transition
              ON transition.source_change_event_id = event.id
            WHERE event.detected_at >= ? OR event.status = 'pending'
            GROUP BY event.id
            """,
            ((now_dt - timedelta(days=7)).isoformat().replace("+00:00", "Z"),),
        ).fetchall()
        alert_flow_rows = conn.execute(
            """
            SELECT created_at, acknowledged_at, severity,
                   CASE WHEN EXISTS (
                       SELECT 1 FROM operational_tasks task
                       WHERE task.alert_id = alert_events.id
                         AND task.status IN ('pending', 'leased', 'awaiting_human')
                   ) THEN 1 ELSE 0 END AS executable
            FROM alert_events
            WHERE created_at >= ? OR acknowledged_at >= ?
            """,
            (
                (now_dt - timedelta(days=7)).isoformat().replace("+00:00", "Z"),
                (now_dt - timedelta(days=7)).isoformat().replace("+00:00", "Z"),
            ),
        ).fetchall()
        human_rows = conn.execute(
            """
            SELECT task.id AS task_id, task.question_id, task.alert_id,
                   task.escalation_owner, task.escalated_at, task.due_at,
                   task.disposition, task.created_at, alert.severity, alert.reason,
                   question.title
            FROM operational_tasks task
            JOIN alert_events alert ON alert.id = task.alert_id
            LEFT JOIN forecast_questions question ON question.id = task.question_id
            WHERE task.status = 'awaiting_human' AND alert.acknowledged_at IS NULL
            ORDER BY
              CASE WHEN alert.reason LIKE '%resolution%' THEN 0 ELSE 1 END,
              COALESCE(task.due_at, task.created_at), task.created_at
            LIMIT 100
            """
        ).fetchall()

    queue: dict[str, dict[str, Any]] = {}
    for policy in policies:
        lane = policy["lane"]
        lane_tasks = [row for row in task_rows if row["lane"] == lane]
        open_tasks = [row for row in lane_tasks if row["status"] in {"pending", "leased"}]
        ages = sorted(
            max((now_dt - timestamp_to_datetime(row["available_at"])).total_seconds() / 60, 0.0)
            for row in open_tasks
            if timestamp_to_datetime(row["available_at"]) is not None
        )
        lane_attempts = [row for row in attempts if row["lane"] == lane]
        queue[lane] = {
            "backlog": len(open_tasks),
            "oldest_age_minutes": round(max(ages), 1) if ages else 0.0,
            "p50_age_minutes": round(ages[len(ages) // 2], 1) if ages else 0.0,
            "p95_age_minutes": round(ages[min(int(len(ages) * 0.95), len(ages) - 1)], 1) if ages else 0.0,
            "slo_minutes": int(policy["slo_minutes"]),
            "slo_breaches": sum(age > int(policy["slo_minutes"]) for age in ages),
            "daily_budget": int(policy["daily_claim_budget"]),
            "claims_today": len(lane_attempts),
            "completed_today": sum(row["outcome"] not in {None, "failed_retrying"} for row in lane_attempts),
            "dead_letter": sum(row["status"] == "dead_letter" for row in lane_tasks),
        }
    capacity = {
        "actively_serviced": 0,
        "monitor_only": 0,
        "resolution_only": 0,
        "archived": 0,
        "resolved": 0,
        "unclassified": 0,
    }
    actively_serviced_without_schedule = 0
    monitor_only_without_watch = 0
    resolution_only_without_schedule = 0
    for row in question_modes:
        metadata = json_loads(row["metadata"], {})
        if row["status"] == "resolved":
            mode = "resolved"
        elif row["status"] == "archived":
            mode = "archived"
        else:
            mode = metadata.get("service_mode") or "unclassified"
        if mode in capacity:
            capacity[mode] += 1
        if (
            row["status"] == "active"
            and mode == "actively_serviced"
            and row["id"] not in scheduled_question_ids
        ):
            actively_serviced_without_schedule += 1
        if row["status"] == "active" and mode == "monitor_only" and row["id"] not in watched_question_ids:
            monitor_only_without_watch += 1
        if (
            row["status"] == "active"
            and mode == "resolution_only"
            and row["id"] not in resolution_schedule_ids
        ):
            resolution_only_without_schedule += 1
    total_cost = sum(float(row["cost_usd"] or 0) for row in all_attempts)
    material_outputs = sum(
        row["outcome"] in {"proposed", "auto_committed"} for row in all_attempts
    )
    resolution_outputs = sum(
        row["outcome"] == "resolved_by_resolution" for row in all_attempts
    )
    utility_model = _active_utility_model(ledger)
    high_ages = [
        max((now_dt - timestamp_to_datetime(row["created_at"])).total_seconds() / 60, 0.0)
        for row in high_alert_rows
        if timestamp_to_datetime(row["created_at"]) is not None
    ]
    arrival_to_claim = sorted(
        max(
            (
                timestamp_to_datetime(row["claimed_at"])
                - timestamp_to_datetime(row["created_at"])
            ).total_seconds(),
            0.0,
        )
        for row in task_rows
        if timestamp_to_datetime(row["claimed_at"])
        and timestamp_to_datetime(row["created_at"])
    )
    claim_to_terminal = sorted(
        max(
            (
                timestamp_to_datetime(row["completed_at"])
                - timestamp_to_datetime(row["claimed_at"])
            ).total_seconds(),
            0.0,
        )
        for row in task_rows
        if timestamp_to_datetime(row["completed_at"])
        and timestamp_to_datetime(row["claimed_at"])
    )

    def latency_summary(values: list[float]) -> dict[str, float | int | None]:
        if not values:
            return {"count": 0, "p50_seconds": None, "p90_seconds": None}
        return {
            "count": len(values),
            "p50_seconds": round(values[len(values) // 2], 1),
            "p90_seconds": round(values[min(int(len(values) * 0.9), len(values) - 1)], 1),
        }

    one_day_ago = now_dt - timedelta(days=1)
    seven_days_ago = now_dt - timedelta(days=7)

    def flow_window(hours: int) -> dict[str, Any]:
        cutoff = now_dt - timedelta(hours=hours)
        arrivals = sum(
            bool((dt := timestamp_to_datetime(row["detected_at"])) and dt >= cutoff)
            for row in source_flow_rows
        )
        completions = sum(
            bool((dt := timestamp_to_datetime(row["terminal_at"])) and dt >= cutoff)
            for row in source_flow_rows
        )
        return {
            "hours": hours,
            "arrivals": arrivals,
            "terminal": completions,
            "net": arrivals - completions,
            "completion_exceeds_arrivals": completions > arrivals,
        }

    pending_source_ages = sorted(
        max((now_dt - detected).total_seconds() / 3600, 0.0)
        for row in source_flow_rows
        if row["status"] == "pending"
        and (detected := timestamp_to_datetime(row["detected_at"])) is not None
    )
    content_groups: dict[str, dict[str, Any]] = {}
    for row in source_flow_rows:
        parsed = json_loads(row["parsed_values"], {})
        key = f"{row['source_type'] or 'unknown'}:{row['source_url'] or 'unknown'}"
        group = content_groups.setdefault(
            key,
            {
                "source_type": row["source_type"],
                "source": row["source_url"],
                "adapter_version": row["adapter_version"],
                "parser_version": parsed.get("parser_version"),
                "events": 0,
                "changed_items": 0,
                "with_title": 0,
                "with_text": 0,
                "with_published_at": 0,
                "with_url": 0,
                "with_hash": 0,
                "insufficient_content": 0,
                "terminal": 0,
            },
        )
        items = parsed.get("changed_items") or []
        if not isinstance(items, list):
            items = []
        group["events"] += 1
        group["changed_items"] += len(items)
        group["with_title"] += sum(bool(item.get("headline")) for item in items if isinstance(item, dict))
        group["with_text"] += sum(bool(item.get("summary")) for item in items if isinstance(item, dict))
        group["with_published_at"] += sum(bool(item.get("published_at")) for item in items if isinstance(item, dict))
        group["with_url"] += sum(bool(item.get("canonical_url")) for item in items if isinstance(item, dict))
        group["with_hash"] += sum(bool(item.get("content_hash")) for item in items if isinstance(item, dict))
        if row["terminal_at"]:
            group["terminal"] += 1
        if str(row["disposition"] or "").startswith("insufficient_content"):
            group["insufficient_content"] += 1
    for group in content_groups.values():
        terminal = int(group["terminal"])
        group["insufficient_content_pct"] = (
            round(100 * int(group["insufficient_content"]) / terminal, 1)
            if terminal
            else None
        )

    def alert_window(hours: int) -> dict[str, Any]:
        cutoff = now_dt - timedelta(hours=hours)
        arrivals = [
            row for row in alert_flow_rows
            if (created := timestamp_to_datetime(row["created_at"])) and created >= cutoff
        ]
        closures = [
            row for row in alert_flow_rows
            if (closed := timestamp_to_datetime(row["acknowledged_at"])) and closed >= cutoff
        ]
        open_rows = [row for row in arrivals if not row["acknowledged_at"]]
        ages = sorted(
            max((now_dt - created).total_seconds() / 3600, 0.0)
            for row in open_rows
            if (created := timestamp_to_datetime(row["created_at"]))
        )
        latencies = sorted(
            max((closed - created).total_seconds() / 3600, 0.0)
            for row in closures
            if (closed := timestamp_to_datetime(row["acknowledged_at"]))
            and (created := timestamp_to_datetime(row["created_at"]))
        )
        return {
            "hours": hours,
            "arrivals": len(arrivals),
            "closures": len(closures),
            "net": len(arrivals) - len(closures),
            "open_from_window": len(open_rows),
            "open_age_p90_hours": round(
                ages[min(int(len(ages) * 0.9), len(ages) - 1)], 1
            ) if ages else None,
            "closure_latency_p90_hours": round(
                latencies[min(int(len(latencies) * 0.9), len(latencies) - 1)], 1
            ) if latencies else None,
            "executable_pct": round(
                100 * sum(bool(row["executable"]) for row in open_rows) / len(open_rows), 1
            ) if open_rows else 100.0,
        }

    human_inbox = []
    for row in human_rows:
        human_inbox.append(
            {
                **dict(row),
                "age_hours": round(
                    max(
                        (
                            now_dt
                            - (
                                timestamp_to_datetime(row["escalated_at"])
                                or timestamp_to_datetime(row["created_at"])
                                or now_dt
                            )
                        ).total_seconds()
                        / 3600,
                        0.0,
                    ),
                    1,
                ),
                "actions": {
                    "acknowledge": f"forecast alerts --task {row['task_id']} --action acknowledge",
                    "defer": f"forecast alerts --task {row['task_id']} --action defer --defer-hours 24",
                    "resolve": f"forecast alerts --task {row['task_id']} --action resolve",
                    "reforecast": f"forecast alerts --task {row['task_id']} --action reforecast",
                },
            }
        )
    return {
        "generated_at": stamp,
        "queue": queue,
        "awaiting_human": sum(row["status"] == "awaiting_human" for row in task_rows),
        "arrival_count": len(task_rows),
        "service_count_today": sum(item["completed_today"] for item in queue.values()),
        "coverage": {
            **{key: int(coverage[key] or 0) for key in coverage.keys()},
            "actively_serviced_without_schedule": actively_serviced_without_schedule,
            "monitor_only_without_watch": monitor_only_without_watch,
            "resolution_only_without_schedule": resolution_only_without_schedule,
            "service_mode_coverage_gaps": (
                actively_serviced_without_schedule
                + monitor_only_without_watch
                + resolution_only_without_schedule
            ),
            "unclassified_active": sum(
                row["status"] == "active"
                and not json_loads(row["metadata"], {}).get("service_mode")
                for row in question_modes
            ),
        },
        "source_changes": {
            **{row["status"]: int(row["n"]) for row in source_counts},
            "estimator_required": int(source_lifecycle["estimator_required"] or 0),
            "stranded": int(source_lifecycle["stranded"] or 0),
            "open_failed": int(source_lifecycle["open_failed"] or 0),
            "terminal_failed": int(source_lifecycle["terminal_failed"] or 0),
            "oldest_pending_at": source_lifecycle["oldest_pending_at"],
            "flow": {
                "6h": flow_window(6),
                "24h": flow_window(24),
                "oldest_pending_hours": round(max(pending_source_ages), 1)
                if pending_source_ages else 0.0,
                "p90_pending_hours": round(
                    pending_source_ages[
                        min(int(len(pending_source_ages) * 0.9), len(pending_source_ages) - 1)
                    ],
                    1,
                ) if pending_source_ages else 0.0,
            },
            "content_yield": list(content_groups.values()),
        },
        "alert_flow": {"24h": alert_window(24), "7d": alert_window(24 * 7)},
        "human_inbox": {
            "count": len(human_inbox),
            "groups": len({row["question_id"] for row in human_inbox}),
            "items": human_inbox,
        },
        "capacity": capacity,
        "high_severity": {
            "open": len(high_alert_rows),
            "unclaimed": sum(
                not row["has_active_task"] and not row["has_escalation_owner"]
                for row in high_alert_rows
            ),
            "awaiting_execution": sum(
                bool(row["has_active_task"]) and not row["has_lease"]
                for row in high_alert_rows
            ),
            "awaiting_human": sum(
                bool(row["is_awaiting_human"]) for row in high_alert_rows
            ),
            "slo_breaches": sum(
                bool(row["due_at"] and row["due_at"] <= stamp)
                for row in high_alert_rows
            ),
            "oldest_age_minutes": round(max(high_ages), 1) if high_ages else 0.0,
            "aged_24h_canary": any(age > 24 * 60 for age in high_ages),
            "aged_24h_count": sum(age > 24 * 60 for age in high_ages),
            "historical_cleanup_debt_7d": sum(
                bool(
                    (created := timestamp_to_datetime(row["created_at"]))
                    and created < seven_days_ago
                )
                for row in high_alert_rows
            ),
            "new_sla_violations_24h": sum(
                bool(
                    (created := timestamp_to_datetime(row["created_at"]))
                    and created >= one_day_ago
                    and row["due_at"]
                    and row["due_at"] <= stamp
                )
                for row in high_alert_rows
            ),
            "oldest_first": True,
            "human_escalation": sum(
                bool(row["has_human_escalation"]) for row in high_alert_rows
            ),
            "assigned_owner_count": sum(
                bool(row["has_escalation_owner"]) for row in high_alert_rows
            ),
        },
        "cost": {
            "total_usd": round(total_cost, 6),
            "today_usd": round(sum(float(row["cost_usd"] or 0) for row in attempts), 6),
            "model_calls": sum(int(row["model_calls"] or 0) for row in all_attempts),
            "source_calls": sum(int(row["source_calls"] or 0) for row in all_attempts),
            "input_tokens": sum(int(row["input_tokens"] or 0) for row in all_attempts),
            "output_tokens": sum(int(row["output_tokens"] or 0) for row in all_attempts),
            "provenance": {
                str(row["cost_status"] or "unknown"): sum(
                    1
                    for candidate in all_attempts
                    if (candidate["cost_status"] or "unknown")
                    == (row["cost_status"] or "unknown")
                )
                for row in all_attempts
            },
            "per_material_update_usd": (
                round(total_cost / material_outputs, 6) if material_outputs else None
            ),
            "per_resolution_usd": (
                round(total_cost / resolution_outputs, 6) if resolution_outputs else None
            ),
        },
        "history": [dict(row) for row in reversed(history_rows)],
        "latency": {
            "arrival_to_claim": latency_summary(arrival_to_claim),
            "claim_to_terminal": latency_summary(claim_to_terminal),
        },
        "rate_limits": [dict(row) for row in rate_limits],
        "utility": {
            **utility_backtest(ledger),
            "active_model": utility_model["id"] if utility_model else "utility-v1",
        },
    }


def claim_automation_budget(
    ledger,
    bucket: str,
    *,
    owner: str,
    now: str | None = None,
    min_interval_hours: float = 0.0,
    lease_seconds: int = 3600,
    reserved_spend: int = 0,
    force: bool = False,
) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    lease_expires = (
        now_dt + timedelta(seconds=max(int(lease_seconds), 1))
    ).isoformat().replace("+00:00", "Z")
    threshold = (
        now_dt - timedelta(hours=max(float(min_interval_hours), 0.0))
    ).isoformat().replace("+00:00", "Z")
    with ledger._connect() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO automation_budget_leases
                (bucket, updated_at)
            VALUES (?, ?)
            """,
            (bucket, stamp),
        )
        claimed = conn.execute(
            """
            UPDATE automation_budget_leases
            SET lease_owner = ?, lease_expires_at = ?, last_run_at = ?,
                last_spent = ?, updated_at = ?
            WHERE bucket = ?
              AND (lease_owner IS NULL OR lease_expires_at <= ?)
              AND (? = 1 OR last_run_at IS NULL OR last_run_at <= ?)
            """,
            (
                owner,
                lease_expires,
                stamp,
                max(int(reserved_spend), 0),
                stamp,
                bucket,
                stamp,
                1 if force else 0,
                threshold,
            ),
        )
        row = conn.execute(
            "SELECT * FROM automation_budget_leases WHERE bucket = ?", (bucket,)
        ).fetchone()
    data = dict(row)
    data["claimed"] = claimed.rowcount == 1
    data["blocked_reason"] = (
        None
        if data["claimed"]
        else "already_claimed"
        if data.get("lease_owner") and data.get("lease_expires_at", "") > stamp
        else "min_interval"
    )
    return data


def release_automation_budget(
    ledger,
    bucket: str,
    *,
    owner: str,
    spent: int,
    now: str | None = None,
    completed: bool = True,
) -> dict[str, Any]:
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    with ledger._connect() as conn:
        released = conn.execute(
            """
            UPDATE automation_budget_leases
            SET lease_owner = NULL, lease_expires_at = NULL,
                last_run_at = CASE WHEN ? = 1 THEN ? ELSE last_run_at END,
                last_spent = ?, updated_at = ?
            WHERE bucket = ? AND lease_owner = ?
            """,
            (1 if completed else 0, stamp, max(int(spent), 0), stamp, bucket, owner),
        )
        if released.rowcount != 1:
            raise ValueError("automation budget lease is not owned by this worker")
        row = conn.execute(
            "SELECT * FROM automation_budget_leases WHERE bucket = ?", (bucket,)
        ).fetchone()
    return dict(row)


def automation_budget_status(ledger, bucket: str) -> dict[str, Any] | None:
    with ledger._connect() as conn:
        row = conn.execute(
            "SELECT * FROM automation_budget_leases WHERE bucket = ?", (bucket,)
        ).fetchone()
    return dict(row) if row is not None else None


def acquire_watch_source_token(
    ledger,
    watch: dict[str, Any],
    *,
    now: str | None = None,
) -> dict[str, Any]:
    """Acquire one adapter/account token shared by all watches in this ledger."""
    source_type = str(watch.get("source_type") or "unknown")
    if source_type in {"file", "manual"}:
        return {"granted": True, "bucket": None, "unlimited": True}
    metadata = watch.get("metadata") or {}
    config = metadata.get("rate_limit") or {}
    account_key = str(
        config.get("account_key")
        or metadata.get("account_id")
        or metadata.get("credential_id")
        or "default"
    )
    capacity = max(float(config.get("capacity") or 60.0), 1.0)
    refill = max(float(config.get("refill_per_second") or 1.0), 0.000001)
    cost = max(float(config.get("tokens_per_request") or 1.0), 0.000001)
    bucket = f"{source_type}:{account_key}"
    stamp = parse_timestamp(now, field_name="now") or utc_now_iso()
    now_dt = timestamp_to_datetime(stamp)
    assert now_dt is not None
    with ledger._connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT * FROM source_token_buckets WHERE bucket = ?", (bucket,)
        ).fetchone()
        if row is None:
            tokens = capacity
            last_dt = now_dt
        else:
            last_dt = timestamp_to_datetime(row["updated_at"]) or now_dt
            elapsed = max((now_dt - last_dt).total_seconds(), 0.0)
            tokens = min(float(row["capacity"]), float(row["tokens"]) + elapsed * refill)
        granted = tokens >= cost
        remaining = tokens - cost if granted else tokens
        if row is None:
            conn.execute(
                """
                INSERT INTO source_token_buckets (
                    bucket, source_type, account_key, tokens, capacity,
                    refill_per_second, updated_at, granted_count, denied_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    bucket,
                    source_type,
                    account_key,
                    remaining,
                    capacity,
                    refill,
                    stamp,
                    1 if granted else 0,
                    0 if granted else 1,
                ),
            )
        else:
            conn.execute(
                """
                UPDATE source_token_buckets
                SET tokens = ?, capacity = ?, refill_per_second = ?, updated_at = ?,
                    granted_count = granted_count + ?, denied_count = denied_count + ?
                WHERE bucket = ?
                """,
                (
                    remaining,
                    capacity,
                    refill,
                    stamp,
                    1 if granted else 0,
                    0 if granted else 1,
                    bucket,
                ),
            )
    retry_after = 0.0 if granted else max((cost - remaining) / refill, 0.0)
    return {
        "granted": granted,
        "bucket": bucket,
        "tokens_remaining": round(remaining, 6),
        "retry_after_seconds": round(retry_after, 3),
    }


def list_source_token_buckets(ledger) -> list[dict[str, Any]]:
    with ledger._connect() as conn:
        rows = conn.execute(
            "SELECT * FROM source_token_buckets ORDER BY bucket"
        ).fetchall()
    return [dict(row) for row in rows]


def set_question_service_mode(
    ledger,
    question_id: str,
    mode: str,
) -> dict[str, Any]:
    modes = {"actively_serviced", "monitor_only", "resolution_only", "archived"}
    if mode not in modes:
        raise ValueError("service mode must be actively_serviced, monitor_only, resolution_only, or archived")
    question = ledger.get_question(question_id)
    active_watches = ledger.list_watched_sources(
        scope_type="question", scope_ref=question_id, status="active"
    )
    if mode == "monitor_only" and not active_watches:
        raise ValueError("monitor_only requires at least one active watched source")
    metadata = dict(question.metadata or {})
    metadata["service_mode"] = mode
    stamp = utc_now_iso()
    with ledger._connect() as conn:
        conn.execute(
            "UPDATE forecast_questions SET metadata = ? WHERE id = ?",
            (json_dumps(metadata), question_id),
        )
        if mode != "actively_serviced":
            conn.execute(
                "UPDATE scheduled_reviews SET enabled = 0, lease_owner = NULL, lease_expires_at = NULL "
                "WHERE scope_type = 'question' AND scope_ref = ?",
                (question_id,),
            )
            conn.execute(
                "UPDATE autopilot_policies SET enabled = 0, updated_at = ? WHERE question_id = ?",
                (stamp, question_id),
            )
        if mode == "resolution_only":
            conn.execute(
                """
                UPDATE watched_sources SET status = 'inactive'
                WHERE scope_type = 'question' AND scope_ref = ? AND status = 'active'
                  AND COALESCE(role, '') NOT IN ('resolver', 'official_primary')
                """,
                (question_id,),
            )
        elif mode == "archived":
            conn.execute(
                "UPDATE forecast_questions SET status = 'archived' WHERE id = ?",
                (question_id,),
            )
            conn.execute(
                "UPDATE watched_sources SET status = 'inactive' "
                "WHERE scope_type = 'question' AND scope_ref = ? AND status = 'active'",
                (question_id,),
            )
            conn.execute(
                """
                UPDATE alert_events SET acknowledged_at = ?, disposition = 'not_actionable',
                    ack_note = COALESCE(ack_note, 'auto_close:question_archived')
                WHERE scope_type = 'question' AND scope_ref = ? AND acknowledged_at IS NULL
                """,
                (stamp, question_id),
            )
    if mode == "resolution_only":
        deadline = question.resolution_time or question.close_time or question.decision_deadline
        deadline_dt = timestamp_to_datetime(deadline)
        stamp_dt = timestamp_to_datetime(stamp)
        next_run_at = deadline if deadline_dt and stamp_dt and deadline_dt > stamp_dt else stamp
        ledger.schedule_review(
            scope_type="question",
            scope_ref=question_id,
            cadence="7d",
            next_run_at=next_run_at,
            trigger_reason="resolution_only",
            enabled=True,
            auto_score=True,
            auto_postmortem=True,
            stale_days=0,
        )
    elif mode == "actively_serviced":
        reviews = [
            review for review in ledger.list_scheduled_reviews()
            if review["scope_type"] == "question" and review["scope_ref"] == question_id
        ]
        if reviews:
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE scheduled_reviews SET enabled = 1 WHERE id = ?",
                    (reviews[0]["id"],),
                )
        else:
            ledger.schedule_review(
                scope_type="question",
                scope_ref=question_id,
                cadence="7d",
                next_run_at=stamp,
                trigger_reason="service_mode",
                enabled=True,
            )
    return {
        "question": ledger.get_question(question_id),
        "service_mode": mode,
        "scheduled_reviews": [
            review
            for review in ledger.list_scheduled_reviews()
            if review["scope_type"] == "question" and review["scope_ref"] == question_id
        ],
        "watched_sources": ledger.list_watched_sources(
            scope_type="question", scope_ref=question_id, status=None
        ),
    }


def classify_active_question_service_modes(
    ledger, *, dry_run: bool = True
) -> dict[str, Any]:
    """Classify every previously-unclassified active question conservatively."""
    rows: list[dict[str, Any]] = []
    counts = {
        "actively_serviced": 0,
        "monitor_only": 0,
        "resolution_only": 0,
    }
    reviews = ledger.list_scheduled_reviews()
    scheduled = {
        row["scope_ref"]
        for row in reviews
        if row.get("enabled") and row.get("scope_type") == "question"
    }
    for question in ledger.list_questions(status="active"):
        if (question.metadata or {}).get("service_mode"):
            continue
        watches = ledger.list_watched_sources(
            scope_type="question", scope_ref=question.id, status="active"
        )
        if question.id in scheduled:
            mode = "actively_serviced"
            reason = "enabled question review schedule"
        elif any(
            str(watch.get("role") or "") in {"resolver", "official_primary"}
            for watch in watches
        ):
            mode = "resolution_only"
            reason = "resolution source only; no active review schedule"
        elif watches:
            mode = "monitor_only"
            reason = "watched sources present; no active review schedule"
        else:
            mode = "resolution_only"
            reason = "no maintenance schedule or watch; retain only for settlement"
        counts[mode] += 1
        rows.append({"question_id": question.id, "mode": mode, "reason": reason})
        if not dry_run:
            result = set_question_service_mode(ledger, question.id, mode)
            metadata = dict(result["question"].metadata or {})
            metadata["service_mode_reason"] = reason
            with ledger._connect() as conn:
                conn.execute(
                    "UPDATE forecast_questions SET metadata = ? WHERE id = ?",
                    (json_dumps(metadata), question.id),
                )
    return {
        "dry_run": dry_run,
        "classified": len(rows),
        "counts": counts,
        "rows": rows,
    }


def _event_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    for field in ("old_state", "new_state", "materiality", "metadata"):
        data[field] = json_loads(data[field], {})
    return data


def _task_dict(row: sqlite3.Row) -> dict[str, Any]:
    data = dict(row)
    data["result"] = json_loads(data["result"], {})
    data["utility_components"] = json_loads(data.get("utility_components"), {})
    return data
