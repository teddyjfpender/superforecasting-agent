import json
import os
import sys
import threading
import time
import types
from pathlib import Path
from unittest.mock import patch

import pytest

from tui_gateway import server


@pytest.fixture(autouse=True)
def _stop_leaked_notification_pollers(monkeypatch):
    """Own test workers and poller stops explicitly, without Thread internals."""
    from superforecasting_agent.hosting.workers import RuntimeWorkers
    workers = RuntimeWorkers()
    monkeypatch.setattr(server, "_pool", workers)
    original = server._start_notification_poller
    pollers = []
    def start(sid, session):
        stop = original(sid, session)
        pollers.append((stop, session))
        return stop
    monkeypatch.setattr(server, "_start_notification_poller", start)
    yield
    for stop, session in pollers:
        stop.set()
        session["_finalized"] = True
    workers.stop()
    assert workers.drain(3), "test left runtime workers active"


class _ChunkyStdout:
    def __init__(self):
        self.parts: list[str] = []

    def write(self, text: str) -> int:
        for ch in text:
            self.parts.append(ch)
            time.sleep(0.0001)
        return len(text)

    def flush(self) -> None:
        return None


class _BrokenStdout:
    def write(self, text: str) -> int:
        raise BrokenPipeError

    def flush(self) -> None:
        return None


def test_write_json_serializes_concurrent_writes(monkeypatch):
    out = _ChunkyStdout()
    monkeypatch.setattr(server, "_real_stdout", out)

    threads = [
        threading.Thread(target=server.write_json, args=({"seq": i, "text": "x" * 24},))
        for i in range(8)
    ]

    for t in threads:
        t.start()

    for t in threads:
        t.join()

    lines = "".join(out.parts).splitlines()

    assert len(lines) == 8
    assert {json.loads(line)["seq"] for line in lines} == set(range(8))


def test_write_json_returns_false_on_broken_pipe(monkeypatch):
    monkeypatch.setattr(server, "_real_stdout", _BrokenStdout())

    assert server.write_json({"ok": True}) is False


def test_theme_list_returns_skins_with_colors():
    resp = server.handle_request({"id": "1", "method": "theme.list", "params": {}})
    assert "result" in resp, resp
    result = resp["result"]
    themes = result["themes"]
    # Built-in skins must be present, each with a usable color map for preview.
    by_name = {t["name"]: t for t in themes}
    assert {"default", "mono", "slate"} <= set(by_name)
    assert by_name["slate"]["colors"]  # non-empty color map
    assert all("name" in t and "colors" in t for t in themes)
    assert isinstance(result.get("active"), str)
    # The light/dark appearance override is reported for the picker.
    assert result.get("appearance") in {"light", "dark", "auto"}


def test_appearance_config_set_persists_and_validates(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    ok = server.handle_request(
        {"id": "1", "method": "config.set", "params": {"key": "appearance", "value": "dark"}}
    )
    assert "result" in ok, ok
    assert ok["result"]["value"] == "dark"
    # theme.list and resolve_skin both report the persisted choice.
    listed = server.handle_request({"id": "2", "method": "theme.list", "params": {}})
    assert listed["result"]["appearance"] == "dark"
    assert server.resolve_skin().get("appearance") == "dark"
    # Invalid values are rejected, not silently coerced.
    bad = server.handle_request(
        {"id": "3", "method": "config.set", "params": {"key": "appearance", "value": "bogus"}}
    )
    assert "error" in bad, bad


def test_forecast_config_read_and_write_roundtrip(tmp_path, monkeypatch):
    """forecast.config resolves the per-forecast settings; forecast.config.set
    writes cadence + decision + hook gate/threshold overrides and returns the
    freshly-resolved config (so the desk + modal refresh)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger()  # default home DB (under the patched HERMES_HOME)
    question = ledger.create_question(
        title="Will CPI YoY exceed 3.0% in 2027?",
        resolution_criteria="Resolved by the official BLS CPI-U release for 2027.",
    )

    read = server.handle_request(
        {"id": "1", "method": "forecast.config", "params": {"id": question.id}}
    )
    assert "result" in read, read
    assert read["result"]["question_id"] == question.id
    assert read["result"]["gates"], read
    assert read["result"]["thresholds"], read

    written = server.handle_request(
        {
            "id": "2",
            "method": "forecast.config.set",
            "params": {
                "id": question.id,
                "review_cadence": "weekly",
                "decision": {"decision_owner": "desk lead"},
                "hooks": {
                    "overrides": {"quorum_participation": "off"},
                    "thresholds": {"min_perspectives": 2},
                },
            },
        }
    )
    assert "result" in written, written
    res = written["result"]
    assert res["cadence"] == "weekly"
    assert res["decision"]["decision_owner"] == "desk lead"
    gates = {g["id"]: g for g in res["gates"]}
    assert gates["quorum_participation"]["severity"] == "off"
    assert gates["quorum_participation"]["looser"] is True
    thr = {t["key"]: t for t in res["thresholds"]}
    assert thr["min_perspectives"]["value"] == 2
    assert thr["min_perspectives"]["looser"] is True


def _seed_questions_with_snapshots(ledger, n_with: int, n_without: int):
    """Create ``n_with`` questions carrying a committed snapshot (0 evidence) and
    ``n_without`` questions with none. Returns the with-snapshot question ids."""
    from forecasting.ledger import allow_ledger_writes

    with_ids: list[str] = []
    with allow_ledger_writes(reason="test_seed"):
        for i in range(n_with):
            q = ledger.create_question(
                title=f"Seeded question {i}?",
                resolution_criteria="Resolved by the official release.",
            )
            ledger.create_snapshot(
                question_id=q.id,
                probability_or_distribution=0.4,
                rationale="seed snapshot",
            )
            with_ids.append(q.id)
        for j in range(n_without):
            ledger.create_question(
                title=f"No-snapshot question {j}?",
                resolution_criteria="Resolved by the official release.",
            )
    return with_ids


def test_hooks_preview_batches_and_skips_snapshotless_questions(tmp_path, monkeypatch):
    """forecast.hooks.preview counts only questions with a committed snapshot and
    resolves the current snapshot from a single batched fetch (P4)."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger()
    _seed_questions_with_snapshots(ledger, n_with=4, n_without=2)

    # A rule that fails for any question with < 1 evidence item (all seeds have 0)
    # → applies to every snapshot-carrying question, blocks them all.
    rule = {
        "id": "needs-evidence",
        "severity": "warn",
        "check": {"signal": "evidence.count", "op": ">=", "value": 1},
        "message": "collect at least one evidence item",
    }
    resp = server.handle_request(
        {"id": "1", "method": "forecast.hooks.preview", "params": {"rule": rule}}
    )
    assert "result" in resp, resp
    out = json.loads(resp["result"]["output"]) if "output" in resp["result"] else resp["result"]
    assert out["valid"] is True
    assert out["applies"] == 4  # the 2 snapshotless questions are skipped
    assert out["would_block"] == 4
    assert len(out["failing"]) == 4
    assert "capped_at" not in out


def test_hooks_preview_snapshot_matches_get_current_snapshot(tmp_path, monkeypatch):
    """The batched snapshot handed to the context builder must be the SAME one
    ``get_current_snapshot`` returns — spy on the batch call to prove it ran once."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    import tui_gateway.server as srv
    from forecasting.ledger import ForecastLedger
    import forecasting.ledger as ledger_mod

    ledger = ForecastLedger()
    _seed_questions_with_snapshots(ledger, n_with=3, n_without=0)

    calls = {"batch": 0, "per_q": 0}
    real_batch = ledger_mod.ForecastLedger.snapshots_by_question
    real_single = ledger_mod.ForecastLedger.get_current_snapshot

    def spy_batch(self, ids):
        calls["batch"] += 1
        return real_batch(self, ids)

    def spy_single(self, qid):
        calls["per_q"] += 1
        return real_single(self, qid)

    monkeypatch.setattr(ledger_mod.ForecastLedger, "snapshots_by_question", spy_batch)
    monkeypatch.setattr(ledger_mod.ForecastLedger, "get_current_snapshot", spy_single)

    rule = {
        "id": "always-applies",
        "severity": "warn",
        "check": {"signal": "evidence.count", "op": ">=", "value": 0},
        "message": "ok",
    }
    resp = srv.handle_request(
        {"id": "1", "method": "forecast.hooks.preview", "params": {"rule": rule}}
    )
    out = json.loads(resp["result"]["output"]) if "output" in resp["result"] else resp["result"]
    assert out["applies"] == 3
    assert out["would_block"] == 0  # evidence.count >= 0 always passes
    # One batched snapshot fetch for the whole panel; no per-question snapshot
    # query from the preview loop (the old code did one per question, twice).
    assert calls["batch"] == 1
    assert calls["per_q"] == 0


def test_hooks_preview_max_scan_caps_the_scan(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger()
    _seed_questions_with_snapshots(ledger, n_with=5, n_without=0)

    rule = {
        "id": "needs-evidence",
        "severity": "warn",
        "check": {"signal": "evidence.count", "op": ">=", "value": 1},
        "message": "collect evidence",
    }
    resp = server.handle_request(
        {"id": "1", "method": "forecast.hooks.preview", "params": {"rule": rule, "max_scan": 2}}
    )
    out = json.loads(resp["result"]["output"]) if "output" in resp["result"] else resp["result"]
    assert out["applies"] == 2
    assert out["capped_at"] == 2


def test_forecast_config_set_rejects_lesson_demotion(tmp_path, monkeypatch):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger

    ledger = ForecastLedger()
    question = ledger.create_question(
        title="Will the index close above 5000 by 2027-06-30?",
        resolution_criteria="Resolved by the official close on 2027-06-30.",
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.config.set",
            "params": {"id": question.id, "hooks": {"overrides": {"lesson:foo": "off"}}},
        }
    )
    # The lesson:* guardrail surfaces as an RPC error, not a silent demotion.
    assert "error" in resp, resp


def test_forecast_command_runs_forecast_cli_with_raw_args(tmp_path):
    db_path = tmp_path / "forecast.sqlite"
    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.command",
            "params": {"arg": f"--db {db_path} status --json"},
        }
    )

    assert "result" in resp, resp
    assert resp["result"]["code"] == 0
    payload = json.loads(resp["result"]["output"])
    assert payload["slug"] == "superforecasting-agent"
    assert payload["ledger_path"] == str(db_path)


def test_forecast_command_accepts_argv_without_shell_splitting(tmp_path):
    from forecasting.ledger import ForecastLedger

    db_path = tmp_path / "forecast.sqlite"
    question = ForecastLedger(db_path).create_question(
        title="Will CPI exceed consensus?",
        resolution_criteria="Resolved by the official release.",
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.command",
            "params": {
                "argv": [
                    "--db",
                    str(db_path),
                    "update",
                    question.id,
                    "--probability",
                    "0.66",
                    # Live updates hard-require structured reasoning (gate
                    # default flipped ON); satisfy it so the test stays about
                    # argv passthrough, not the policy.
                    "--reason-up",
                    "shelter inflation sticky",
                    "--reason-down",
                    "energy base effects",
                    "--change-my-mind",
                    "next CPI print below 0.2% m/m",
                    "--rationale",
                    "May CPI (all-items) and BLS's release shifted higher",
                ]
            },
        }
    )

    assert "result" in resp, resp
    assert resp["result"]["code"] == 0
    snapshot = ForecastLedger(db_path).get_current_snapshot(question.id)
    assert snapshot is not None
    assert snapshot.rationale == "May CPI (all-items) and BLS's release shifted higher"


def test_forecast_command_tolerates_raw_update_rationale_tail(tmp_path):
    from forecasting.ledger import ForecastLedger

    db_path = tmp_path / "forecast.sqlite"
    question = ForecastLedger(db_path).create_question(
        title="Will CPI exceed consensus?",
        resolution_criteria="Resolved by the official release.",
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.command",
            "params": {
                "arg": (
                    f"--db {db_path} update {question.id} --probability 0.67 "
                    # Reasons satisfy the live structured-reasoning gate; they
                    # sit BEFORE --rationale so the unquoted tail under test
                    # still ends the command line.
                    '--reason-up "shelter sticky" --reason-down "base effects" '
                    '--change-my-mind "sub-0.2 print" '
                    "--rationale May CPI (all-items) and BLS's release shifted higher"
                )
            },
        }
    )

    assert "result" in resp, resp
    assert resp["result"]["code"] == 0
    snapshot = ForecastLedger(db_path).get_current_snapshot(question.id)
    assert snapshot is not None
    assert snapshot.rationale == "May CPI (all-items) and BLS's release shifted higher"


def test_forecast_command_reports_parse_errors():
    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.command",
            "params": {"arg": 'new "unterminated'},
        }
    )

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4003


def test_forecast_question_returns_exported_packet(monkeypatch):
    class FakeLedger:
        def export_question(self, question_id: str, *, fmt: str = "json") -> str:
            assert question_id == "fq_cpi"
            assert fmt == "json"
            return json.dumps({"question": {"id": question_id, "title": "Will CPI surprise?"}})

    import forecasting.ledger as ledger_module

    monkeypatch.setattr(ledger_module, "ForecastLedger", FakeLedger)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.question",
            "params": {"id": "fq_cpi"},
        }
    )

    assert resp["result"]["packet"]["question"]["title"] == "Will CPI surprise?"


def test_forecast_workspace_returns_payload(monkeypatch):
    import forecasting.dashboard as dashboard_module

    def fake_build_workspace_payload(*, limit: int = 50, **kwargs):
        assert limit == 25
        # The desk gates these for speed; the detail RPC carries them instead.
        assert kwargs.get("include_related") is False
        assert kwargs.get("include_lessons") is False
        return {
            "product": "Superforecasting Agent",
            "active_count": 1,
            "open_alert_count": 0,
            "closing_soon_count": 0,
            "forecasts": [{"id": "fq_x", "title": "Will it?", "history": []}],
        }

    monkeypatch.setattr(dashboard_module, "build_workspace_payload", fake_build_workspace_payload)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "forecast.workspace",
            "params": {"limit": 25},
        }
    )

    assert resp["result"]["active_count"] == 1
    assert resp["result"]["forecasts"][0]["id"] == "fq_x"


def test_forecast_workspace_is_routed_to_thread_pool():
    assert "forecast.workspace" in server._LONG_HANDLERS


def test_network_market_rpcs_are_routed_to_thread_pool():
    """Venue HTTP must never stall the stdin dispatcher or later searches."""
    assert {
        "market.quotes",
        "market.search",
        "pm.book",
        "pm.detail",
        "pm.history",
        "pm.list",
    } <= server._LONG_HANDLERS


def test_forecast_theses_returns_standalone_thesis_list(monkeypatch):
    from forecasting.application import aggregate_summaries as dashboard_module

    monkeypatch.setattr(
        dashboard_module, "build_thesis_summary",
        lambda **_: [{"id": "fq_t", "title": "AI scarcity", "health_probability": 0.6, "health_display": "60%"}],
    )
    monkeypatch.setattr(dashboard_module, "build_factor_summary", lambda **_: [])

    resp = server.handle_request({"id": "1", "method": "forecast.theses", "params": {}})

    assert resp["result"]["theses"][0]["id"] == "fq_t"
    assert resp["result"]["factors"] == []


def test_forecast_theses_is_routed_to_thread_pool():
    # it aggregates per-thesis (N+1), so it must not block the dispatch thread
    assert "forecast.theses" in server._LONG_HANDLERS


def test_async_completion_routes_to_originating_session():
    R = server._route_async_completion
    # an async-delegation result is consumed only by its own session's poller
    assert R({"type": "async_delegation", "session_key": "A"}, "A") == "consume"
    # a foreign session re-enqueues it for the right poller (and counts the bounce)
    foreign = {"type": "async_delegation", "session_key": "A"}
    assert R(foreign, "B") == "requeue"
    assert foreign["_route_attempts"] == 1
    # CLI single-session (no key) and non-async events are always consumed
    assert R({"type": "async_delegation", "session_key": ""}, "B") == "consume"
    assert R({"type": "async_delegation"}, "B") == "consume"
    assert R({"type": "completion", "session_id": "X"}, "B") == "consume"
    # orphan fallback: a foreign event no live session claims is taken, never dropped
    orphan = {"type": "async_delegation", "session_key": "A", "_route_attempts": server._MAX_ASYNC_ROUTE_ATTEMPTS}
    assert R(orphan, "B") == "consume"


def _fake_calibration_ledger(*, bias_raises: bool = False):
    """A FakeLedger mirroring the ForecastLedger calibration surface."""

    class FakeLedger:
        bias_calls: list = []
        summary_calls: list = []

        def calibration_summary(self, *, domain=None, forecast_origin=None, horizon=None, calibration_eligible=True):
            FakeLedger.summary_calls.append((domain, forecast_origin))
            assert calibration_eligible is True
            return {
                "count": 12 if domain is None and forecast_origin is None else 4,
                "mean_brier": 0.18,
                "expected_calibration_error": 0.052,
                "max_calibration_error": 0.09,
                "calibration_curve_sample_count": 10,
                "mean_predicted": 0.61,
                "observed_frequency": 0.55,
                "calibration_curve": [
                    {
                        "bucket": "0.6-0.7",
                        "count": 10,
                        "mean_predicted": 0.64,
                        "observed_frequency": 0.58,
                        "calibration_gap": 0.06,
                        "sample_status": "ok",
                    }
                ],
                "buckets": [],
                "domain": domain,
                "forecast_origin": forecast_origin,
            }

        def calibration_bias(self, *, domain=None):
            FakeLedger.bias_calls.append(domain)
            if bias_raises:
                raise RuntimeError("no bias table")
            return {
                "scope_type": "domain" if domain else "global",
                "scope_ref": domain,
                "status": "underconfident" if domain == "macro" else "calibrated",
                "n": 12,
                "ess": 11.0,
                "sce_shrunk": -0.06 if domain == "macro" else 0.0,
                "advisory_text": "under-confident in macro" if domain == "macro" else None,
            }

        def list_scores(self, *, calibration_eligible=True):
            assert calibration_eligible is True
            return [
                types.SimpleNamespace(domain="macro", forecast_origin="live"),
                types.SimpleNamespace(domain="macro", forecast_origin="backtest"),
                types.SimpleNamespace(domain="geopolitics", forecast_origin="live"),
                types.SimpleNamespace(domain=None, forecast_origin="live"),
            ]

    return FakeLedger


def test_forecast_calibration_returns_summary_bias_and_breakdowns(monkeypatch):
    import forecasting.ledger as ledger_module

    monkeypatch.setattr(ledger_module, "ForecastLedger", _fake_calibration_ledger())

    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {}}
    )

    result = resp["result"]
    assert result["summary"]["count"] == 12
    assert result["summary"]["expected_calibration_error"] == 0.052
    assert result["bias"]["scope_type"] == "global"
    # Domain breakdown: sorted distinct domains, each with a lite summary + bias.
    assert [row["domain"] for row in result["domains"]] == ["geopolitics", "macro"]
    macro = result["domains"][1]
    assert macro["count"] == 4
    assert macro["bias"]["status"] == "underconfident"
    assert macro["bias"]["advisory_text"] == "under-confident in macro"
    # Lite rows carry headline metrics only, never the full curve.
    assert "calibration_curve" not in macro
    # Origin breakdown: sorted distinct origins, no bias (bias is scope=domain/global).
    assert [row["origin"] for row in result["origins"]] == ["backtest", "live"]
    assert "bias" not in result["origins"][0]


def test_forecast_calibration_domain_filter_skips_breakdowns(monkeypatch):
    import forecasting.ledger as ledger_module

    fake = _fake_calibration_ledger()
    monkeypatch.setattr(ledger_module, "ForecastLedger", fake)

    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {"domain": "macro"}}
    )

    result = resp["result"]
    assert result["domain"] == "macro"
    assert result["domains"] == []
    assert result["origins"] == []
    assert result["bias"]["status"] == "underconfident"
    # Only the single filtered summary was computed.
    assert fake.summary_calls == [("macro", None)]


def test_forecast_calibration_survives_bias_failure(monkeypatch):
    import forecasting.ledger as ledger_module

    monkeypatch.setattr(
        ledger_module, "ForecastLedger", _fake_calibration_ledger(bias_raises=True)
    )

    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {}}
    )

    result = resp["result"]
    assert result["bias"] is None
    assert result["summary"]["count"] == 12
    assert all(row["bias"] is None for row in result["domains"])


def test_forecast_calibration_rejects_non_string_filters():
    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {"domain": 7}}
    )

    assert resp["error"]["code"] == 4003


def test_forecast_calibration_empty_ledger_reports_zero_counts(tmp_path, monkeypatch):
    # A real, empty ledger: the RPC must report honest zeros (count 0, no curve
    # samples), never fabricate buckets — the TUI renders its empty state off this.
    from forecasting.ledger import ForecastLedger

    db_path = tmp_path / "forecast.sqlite"
    ForecastLedger(db_path)  # create the schema

    import forecasting.ledger as ledger_module

    real = ledger_module.ForecastLedger
    monkeypatch.setattr(
        ledger_module, "ForecastLedger", lambda *a, **k: real(db_path)
    )

    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {}}
    )

    result = resp["result"]
    assert result["summary"]["count"] == 0
    assert result["summary"]["expected_calibration_error"] is None
    assert result["domains"] == []
    assert result["origins"] == []
    bias = result["bias"]
    assert bias is None or bias["status"] == "insufficient_evidence"


def test_forecast_calibration_carries_cohort_scoreboard(tmp_path, monkeypatch):
    # The forecast.calibration RPC must ship the by-cohort scoreboard so the TUI
    # renders scores SEPARATED BY COHORT (never a pooled all-artifact headline).
    from forecasting.ledger import ForecastLedger

    db_path = tmp_path / "forecast.sqlite"
    ForecastLedger(db_path)

    import forecasting.ledger as ledger_module

    real = ledger_module.ForecastLedger
    monkeypatch.setattr(ledger_module, "ForecastLedger", lambda *a, **k: real(db_path))

    resp = server.handle_request(
        {"id": "1", "method": "forecast.calibration", "params": {}}
    )
    board = resp["result"]["cohort_scoreboard"]
    assert board is not None
    assert "live_calibration_eligible" in board["cohorts"]
    assert "continuous_scorecard" in board
    assert "not a skill claim" in board["pooled_diagnostic"]["label"].lower()


def test_forecast_calibration_is_routed_to_thread_pool():
    assert "forecast.calibration" in server._LONG_HANDLERS


def test_dispatch_rejects_non_object_request():
    resp = server.dispatch([])

    assert resp == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "invalid request: expected an object"},
    }


def test_dispatch_rejects_non_object_params():
    resp = server.dispatch({"id": "1", "method": "session.create", "params": []})

    assert resp == {
        "jsonrpc": "2.0",
        "id": "1",
        "error": {"code": -32602, "message": "invalid params: expected an object"},
    }


def test_voice_toggle_returns_configured_record_key(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"voice": {"record_key": "ctrl+o"}},
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(
            check_voice_requirements=lambda: {"available": True, "details": ""}
        ),
    )
    # Voice state belongs to the session that owns the mic. The process
    # defaults must remain unchanged for other sessions and future launches.
    monkeypatch.setenv("SUPERFORECASTING_AGENT_VOICE", "0")
    monkeypatch.setenv("FORECAST_VOICE", "0")
    monkeypatch.setenv("HERMES_VOICE", "0")
    server._sessions["voice-session"] = {"session_key": "voice-key"}
    server._session_toggles.pop("voice-key", None)
    try:
        on_resp = server.dispatch(
            {
                "id": "voice-on",
                "method": "voice.toggle",
                "params": {"action": "on", "session_id": "voice-session"},
            }
        )
        status_resp = server.dispatch(
            {
                "id": "voice-status",
                "method": "voice.toggle",
                "params": {"action": "status", "session_id": "voice-session"},
            }
        )

        assert on_resp["result"]["record_key"] == "ctrl+o"
        assert status_resp["result"]["record_key"] == "ctrl+o"
        assert status_resp["result"]["enabled"] is True
        assert server._session_toggles["voice-key"]["VOICE"] == "1"
        assert os.environ["SUPERFORECASTING_AGENT_VOICE"] == "0"
        assert os.environ["FORECAST_VOICE"] == "0"
        assert os.environ["HERMES_VOICE"] == "0"
    finally:
        server._sessions.pop("voice-session", None)
        server._session_toggles.pop("voice-key", None)


def test_voice_status_prefers_fork_native_runtime_env(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"voice": {}})
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(
            check_voice_requirements=lambda: {"available": True, "details": ""}
        ),
    )
    monkeypatch.setenv("SUPERFORECASTING_AGENT_VOICE", "0")
    monkeypatch.setenv("FORECAST_VOICE", "1")
    monkeypatch.setenv("HERMES_VOICE", "1")

    resp = server.dispatch(
        {"id": "voice-status", "method": "voice.toggle", "params": {"action": "status"}}
    )

    assert resp["result"]["enabled"] is False


def test_voice_toggle_handles_non_dict_voice_cfg(monkeypatch):
    """Round-3 Copilot review regression on #19835.

    ``_load_cfg()`` is raw ``yaml.safe_load()`` output — a hand-edited
    ``voice: true`` / ``voice: cmd+b`` / ``voice: null`` leaves ``voice``
    as a bool/str/None, not a dict. Previously ``.get("record_key")``
    on a non-dict broke every ``voice.toggle`` branch. Now it falls
    back to the documented default.
    """
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(
            check_voice_requirements=lambda: {"available": True, "details": ""}
        ),
    )

    for bad in (True, "cmd+b", None, 42, ["ctrl+b"]):
        monkeypatch.setattr(server, "_load_cfg", lambda b=bad: {"voice": b})

        status_resp = server.dispatch(
            {
                "id": "voice-status",
                "method": "voice.toggle",
                "params": {"action": "status"},
            }
        )

        assert (
            status_resp["result"]["record_key"] == "ctrl+b"
        ), f"voice.record_key fell back to default for voice={bad!r}"

    # Round-4 follow-up: the YAML root itself may be a non-dict. A
    # hand-edit that collapses config.yaml to a scalar / list would
    # otherwise crash ``.get("voice")`` before the inner isinstance
    # guard gets a chance to run.
    for bad_root in (True, None, [], "ctrl+b", 42):
        monkeypatch.setattr(server, "_load_cfg", lambda r=bad_root: r)

        status_resp = server.dispatch(
            {
                "id": "voice-status-root",
                "method": "voice.toggle",
                "params": {"action": "status"},
            }
        )

        assert (
            status_resp["result"]["record_key"] == "ctrl+b"
        ), f"voice.record_key fell back to default for root={bad_root!r}"


def test_voice_record_start_handles_non_dict_voice_cfg(monkeypatch):
    """Round-7 Copilot review regression on #19835.

    The ``voice.record`` start path previously read
    ``_load_cfg().get("voice", {}).get(...)`` without any shape checks.
    When ``voice`` is a non-dict (bool/scalar/list) ``get`` raises
    AttributeError and the handler returns 5025 instead of falling
    back to the VAD defaults. Now it uses ``_voice_cfg_dict()`` and
    non-numeric silence values are coerced to the documented defaults.
    """
    captured: dict = {}

    def fake_start_continuous(**kwargs):
        captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.voice",
        types.SimpleNamespace(
            start_continuous=fake_start_continuous, stop_continuous=lambda: None
        ),
    )
    monkeypatch.setenv("HERMES_VOICE", "1")

    for bad in (True, "cmd+b", None, 42, ["ctrl+b"], {"silence_threshold": "loud"}):
        captured.clear()
        monkeypatch.setattr(server, "_load_cfg", lambda b=bad: {"voice": b})

        resp = server.dispatch(
            {
                "id": "voice-record",
                "method": "voice.record",
                "params": {"action": "start"},
            }
        )

        assert (
            "result" in resp
        ), f"voice.record raised for voice={bad!r}: {resp.get('error')}"
        assert resp["result"]["status"] == "recording"
        assert captured["silence_threshold"] == 200
        assert captured["silence_duration"] == 3.0
        assert captured["auto_restart"] is False

    # Round-12 Copilot review regression on #19835: ``bool`` is a subclass
    # of ``int``, so the naive ``isinstance(threshold, (int, float))``
    # guard would forward ``silence_threshold: true`` as ``1`` instead
    # of falling back to the documented 200 default.
    for bad_bool_cfg in (
        {"silence_threshold": True, "silence_duration": False},
        {"silence_threshold": False},
        {"silence_duration": True},
    ):
        captured.clear()
        monkeypatch.setattr(server, "_load_cfg", lambda c=bad_bool_cfg: {"voice": c})

        resp = server.dispatch(
            {
                "id": "voice-record-bool",
                "method": "voice.record",
                "params": {"action": "start"},
            }
        )

        assert "result" in resp, f"voice.record raised for bool cfg={bad_bool_cfg!r}"
        assert (
            captured["silence_threshold"] == 200
        ), f"bool silence_threshold leaked through for {bad_bool_cfg!r}"
        assert (
            captured["silence_duration"] == 3.0
        ), f"bool silence_duration leaked through for {bad_bool_cfg!r}"
        assert captured["auto_restart"] is False


def test_voice_record_stop_forces_transcription(monkeypatch):
    captured: dict = {}

    def fake_stop_continuous(**kwargs):
        captured.update(kwargs)

    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.voice",
        types.SimpleNamespace(
            start_continuous=lambda **_kwargs: None,
            stop_continuous=fake_stop_continuous,
        ),
    )

    resp = server.dispatch(
        {
            "id": "voice-record-stop",
            "method": "voice.record",
            "params": {"action": "stop"},
        }
    )

    assert resp["result"]["status"] == "stopped"
    assert captured["force_transcribe"] is True


def test_voice_record_stop_updates_event_session_id(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.voice",
        types.SimpleNamespace(
            start_continuous=lambda **_kwargs: True,
            stop_continuous=lambda **_kwargs: None,
        ),
    )
    monkeypatch.setattr(server, "_voice_event_sid", "old-session")

    resp = server.dispatch(
        {
            "id": "voice-record-stop-session",
            "method": "voice.record",
            "params": {"action": "stop", "session_id": "new-session"},
        }
    )

    assert resp["result"]["status"] == "stopped"
    assert server._voice_event_sid == "new-session"


def test_voice_record_start_reports_busy_when_stop_is_in_progress(monkeypatch):
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.voice",
        types.SimpleNamespace(
            start_continuous=lambda **_kwargs: False,
            stop_continuous=lambda **_kwargs: None,
        ),
    )
    monkeypatch.setenv("HERMES_VOICE", "1")
    monkeypatch.setattr(server, "_load_cfg", lambda: {"voice": {}})

    resp = server.dispatch(
        {
            "id": "voice-record-busy",
            "method": "voice.record",
            "params": {"action": "start"},
        }
    )

    assert resp["result"]["status"] == "busy"


def test_voice_toggle_tts_branch_also_carries_record_key(monkeypatch):
    """Round-2 Copilot review regression on #19835.

    The ``tts`` branch used to omit ``record_key`` from its response, so a
    TUI client would parse ``r.record_key ?? 'ctrl+b'`` and reset a
    custom binding to the default on every TTS toggle. Every branch of
    ``voice.toggle`` now carries the configured key so frontend state
    stays authoritative.
    """
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"voice": {"record_key": "ctrl+space"}},
    )
    monkeypatch.setitem(
        sys.modules,
        "tools.voice_mode",
        types.SimpleNamespace(
            check_voice_requirements=lambda: {"available": True, "details": ""}
        ),
    )
    monkeypatch.setenv("SUPERFORECASTING_AGENT_VOICE", "0")
    monkeypatch.setenv("FORECAST_VOICE", "0")
    monkeypatch.setenv("HERMES_VOICE", "0")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_VOICE_TTS", "0")
    monkeypatch.setenv("FORECAST_VOICE_TTS", "0")
    monkeypatch.setenv("HERMES_VOICE_TTS", "0")
    server._sessions["voice-session"] = {"session_key": "voice-key"}
    server._session_toggles["voice-key"] = {"VOICE": "1"}
    try:
        tts_resp = server.dispatch(
            {
                "id": "voice-tts",
                "method": "voice.toggle",
                "params": {"action": "tts", "session_id": "voice-session"},
            }
        )

        assert tts_resp["result"]["record_key"] == "ctrl+space"
        assert tts_resp["result"]["tts"] is True
        assert server._session_toggles["voice-key"]["VOICE_TTS"] == "1"
        assert os.environ["SUPERFORECASTING_AGENT_VOICE_TTS"] == "0"
        assert os.environ["FORECAST_VOICE_TTS"] == "0"
        assert os.environ["HERMES_VOICE_TTS"] == "0"
    finally:
        server._sessions.pop("voice-session", None)
        server._session_toggles.pop("voice-key", None)


def test_load_enabled_toolsets_prefers_tui_env(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_TOOLSETS", "web, terminal, ,memory")
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "all")

    assert server._load_enabled_toolsets() == ["web", "terminal", "memory"]


def test_load_enabled_toolsets_accepts_legacy_tui_env(monkeypatch):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "web, terminal")

    assert server._load_enabled_toolsets() == ["web", "terminal"]


def test_load_enabled_toolsets_filters_invalid_tui_env(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "web, nope")
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )

    assert server._load_enabled_toolsets() == ["web"]
    assert "nope" in capsys.readouterr().err


def test_load_enabled_toolsets_accepts_plugin_env_after_discovery(monkeypatch):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "plugin_demo")

    from superforecasting_agent.tooling import toolsets as toolsets

    discovered = {"ready": False}
    original_validate = toolsets.validate_toolset

    def fake_validate(name):
        return name == "plugin_demo" and discovered["ready"] or original_validate(name)

    monkeypatch.setattr(toolsets, "validate_toolset", fake_validate)
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.plugins",
        types.SimpleNamespace(
            discover_plugins=lambda: discovered.update({"ready": True})
        ),
    )

    assert server._load_enabled_toolsets() == ["plugin_demo"]


def test_load_enabled_toolsets_rejects_disabled_mcp_env(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "mcp-off")
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )

    import superforecasting_agent.runtime.config as config_mod

    monkeypatch.setattr(
        config_mod,
        "read_raw_config",
        lambda: {"mcp_servers": {"mcp-off": {"enabled": False}}},
    )
    monkeypatch.setattr(
        config_mod, "load_config", lambda: {"platform_toolsets": {"cli": ["memory"]}}
    )

    assert server._load_enabled_toolsets() == ["memory"]
    err = capsys.readouterr().err
    assert "ignoring disabled MCP servers" in err
    assert "mcp-off" in err
    assert "using configured CLI toolsets" in err


def test_load_enabled_toolsets_falls_back_when_tui_env_invalid(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "nope")
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )

    import superforecasting_agent.runtime.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config", lambda: {"platform_toolsets": {"cli": ["memory"]}}
    )

    assert server._load_enabled_toolsets() == ["memory"]
    assert "using configured CLI toolsets" in capsys.readouterr().err


def test_load_enabled_toolsets_warns_when_config_fallback_fails(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "nope")
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )

    import superforecasting_agent.runtime.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert server._load_enabled_toolsets() is None
    assert "could not be loaded" in capsys.readouterr().err


def test_load_enabled_toolsets_honors_builtin_env_if_config_fails(monkeypatch):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "web")

    import superforecasting_agent.runtime.config as config_mod

    monkeypatch.setattr(
        config_mod, "load_config", lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    assert server._load_enabled_toolsets() == ["web"]


def test_load_enabled_toolsets_all_env_means_all(monkeypatch):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "all")

    assert server._load_enabled_toolsets() is None


def test_load_enabled_toolsets_all_env_warns_about_ignored_extra_entries(
    monkeypatch, capsys
):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "all,nope")

    assert server._load_enabled_toolsets() is None
    assert "ignoring additional entries: nope" in capsys.readouterr().err


def test_load_enabled_toolsets_reports_disabled_mcp_separately(monkeypatch, capsys):
    monkeypatch.setenv("HERMES_TUI_TOOLSETS", "web,mcp-off,nope")
    monkeypatch.setitem(
        sys.modules,
        "superforecasting_agent.runtime.plugins",
        types.SimpleNamespace(discover_plugins=lambda: None),
    )

    import superforecasting_agent.runtime.config as config_mod

    monkeypatch.setattr(
        config_mod,
        "read_raw_config",
        lambda: {"mcp_servers": {"mcp-off": {"enabled": False}}},
    )

    assert server._load_enabled_toolsets() == ["web"]
    err = capsys.readouterr().err
    assert "ignoring unknown SUPERFORECASTING_AGENT_TUI_TOOLSETS entries: nope" in err
    assert "ignoring disabled MCP servers" in err
    assert "mcp-off" in err


def test_history_to_messages_preserves_tool_calls_for_resume_display():
    history = [
        {"role": "user", "content": "first prompt"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {
                        "name": "search_files",
                        "arguments": json.dumps({"pattern": "resume"}),
                    },
                }
            ],
        },
        {"role": "tool", "content": "{}", "tool_call_id": "call_1"},
        {"role": "assistant", "content": "first answer"},
        {"role": "user", "content": "second prompt"},
    ]

    assert server._history_to_messages(history) == [
        {"role": "user", "text": "first prompt"},
        {"context": "resume", "name": "search_files", "role": "tool"},
        {"role": "assistant", "text": "first answer"},
        {"role": "user", "text": "second prompt"},
    ]


def test_history_to_messages_renders_multimodal_content():
    history = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "look here"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,abc"}},
            ],
        },
        {"role": "assistant", "content": "saw it"},
    ]

    assert server._history_to_messages(history) == [
        {"role": "user", "text": "look here\n[image]"},
        {"role": "assistant", "text": "saw it"},
    ]


def test_session_resume_uses_parent_lineage_for_display(monkeypatch):
    captured = {}

    class FakeDB:
        def get_session(self, target):
            return {"id": target}

        def reopen_session(self, target):
            captured["reopened"] = target

        def get_messages_as_conversation(self, target, include_ancestors=False):
            captured.setdefault("history_calls", []).append((target, include_ancestors))
            return (
                [
                    {"role": "user", "content": "root prompt"},
                    {"role": "assistant", "content": "root answer"},
                ]
                if include_ancestors
                else [{"role": "user", "content": "tip prompt"}]
            )

    monkeypatch.setattr(server, "_get_db", lambda: FakeDB())
    monkeypatch.setattr(server, "_enable_gateway_prompts", lambda: None)
    monkeypatch.setattr(server, "_set_session_context", lambda target: [])
    monkeypatch.setattr(server, "_clear_session_context", lambda tokens: None)
    monkeypatch.setattr(
        server,
        "_make_agent",
        lambda *args, **kwargs: types.SimpleNamespace(model="test"),
    )
    monkeypatch.setattr(
        server,
        "_session_info",
        lambda agent: {"model": "test", "tools": {}, "skills": {}},
    )
    monkeypatch.setattr(
        server, "_init_session", lambda sid, key, agent, history, cols=80: None
    )

    resp = server.handle_request(
        {"id": "1", "method": "session.resume", "params": {"session_id": "tip"}}
    )

    assert resp["result"]["messages"] == [
        {"role": "user", "text": "root prompt"},
        {"role": "assistant", "text": "root answer"},
    ]
    assert captured["history_calls"] == [("tip", False), ("tip", True)]


def test_status_callback_emits_kind_and_text():
    with patch("tui_gateway.server._emit") as emit:
        cb = server._agent_cbs("sid")["status_callback"]
        cb("context_pressure", "85% to compaction")

    emit.assert_called_once_with(
        "status.update",
        "sid",
        {"kind": "context_pressure", "text": "85% to compaction"},
    )


def test_status_callback_accepts_single_message_argument():
    with patch("tui_gateway.server._emit") as emit:
        cb = server._agent_cbs("sid")["status_callback"]
        cb("thinking...")

    emit.assert_called_once_with(
        "status.update",
        "sid",
        {"kind": "status", "text": "thinking..."},
    )


def test_resolve_model_uses_inference_model_env(monkeypatch):
    monkeypatch.delenv("HERMES_MODEL", raising=False)
    monkeypatch.setenv("HERMES_INFERENCE_MODEL", " anthropic/claude-sonnet-4.6\n")

    assert server._resolve_model() == "anthropic/claude-sonnet-4.6"


def test_resolve_model_prefers_forecast_native_model_env(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_MODEL", "anthropic/native")
    monkeypatch.setenv("FORECAST_MODEL", "anthropic/short")
    monkeypatch.setenv("HERMES_MODEL", "anthropic/legacy")

    assert server._resolve_model() == "anthropic/native"


def test_resolve_model_strips_config_model(monkeypatch):
    monkeypatch.delenv("HERMES_MODEL", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_MODEL", raising=False)
    monkeypatch.setattr(
        server, "_load_cfg", lambda: {"model": {"default": " nous/hermes-test "}}
    )

    assert server._resolve_model() == "nous/hermes-test"


def test_startup_runtime_uses_tui_provider_env(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "nous/hermes-test")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_PROVIDER", "nous")
    monkeypatch.setenv("HERMES_TUI_PROVIDER", "openrouter")
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)

    assert server._resolve_startup_runtime() == ("nous/hermes-test", "nous")


def test_startup_runtime_accepts_legacy_tui_provider_env(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "nous/hermes-test")
    monkeypatch.delenv("SUPERFORECASTING_AGENT_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("FORECAST_TUI_PROVIDER", raising=False)
    monkeypatch.setenv("HERMES_TUI_PROVIDER", "nous")
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)

    assert server._resolve_startup_runtime() == ("nous/hermes-test", "nous")


def test_startup_runtime_does_not_treat_inference_provider_as_explicit(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "nous/hermes-test")
    monkeypatch.delenv("HERMES_TUI_PROVIDER", raising=False)
    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "nous")
    monkeypatch.setattr(
        "superforecasting_agent.runtime.models.detect_static_provider_for_model",
        lambda model, provider: None,
    )

    assert server._resolve_startup_runtime() == ("nous/hermes-test", None)


def test_startup_runtime_reads_forecast_native_inference_provider(monkeypatch):
    monkeypatch.setenv("SUPERFORECASTING_AGENT_MODEL", "anthropic/native-model")
    monkeypatch.delenv("HERMES_TUI_PROVIDER", raising=False)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_INFERENCE_PROVIDER", "anthropic")
    monkeypatch.setattr(server, "_load_cfg", lambda: {"model": {"provider": ""}})

    def fake_detect(model, provider):
        assert model == "anthropic/native-model"
        assert provider == "anthropic"
        return "anthropic", model

    monkeypatch.setattr("superforecasting_agent.runtime.models.detect_static_provider_for_model", fake_detect)

    assert server._resolve_startup_runtime() == ("anthropic/native-model", "anthropic")


def test_startup_runtime_detects_provider_for_model_env(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "sonnet")
    monkeypatch.delenv("HERMES_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(server, "_load_cfg", lambda: {"model": {"provider": "auto"}})

    def fake_detect(model, current_provider):
        assert model == "sonnet"
        assert current_provider == "auto"
        return "anthropic", "anthropic/claude-sonnet-4.6"

    monkeypatch.setattr(
        "superforecasting_agent.runtime.models.detect_static_provider_for_model", fake_detect
    )

    assert server._resolve_startup_runtime() == (
        "anthropic/claude-sonnet-4.6",
        "anthropic",
    )


def test_startup_runtime_resolves_short_alias_without_network(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "sonnet")
    monkeypatch.delenv("HERMES_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(server, "_load_cfg", lambda: {"model": {"provider": "auto"}})
    monkeypatch.setattr(
        "superforecasting_agent.runtime.models.fetch_openrouter_models",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network lookup should not run")
        ),
    )

    model, provider = server._resolve_startup_runtime()

    assert provider == "anthropic"
    assert model.startswith("claude-sonnet")


def test_startup_runtime_does_not_call_network_detector(monkeypatch):
    monkeypatch.setenv("HERMES_MODEL", "sonnet")
    monkeypatch.delenv("HERMES_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(server, "_load_cfg", lambda: {"model": {"provider": "auto"}})
    monkeypatch.setattr(
        "superforecasting_agent.runtime.models.detect_provider_for_model",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("network detector called")
        ),
    )

    model, provider = server._resolve_startup_runtime()

    assert model
    assert provider in {None, "anthropic"}


def _session(agent=None, **extra):
    return {
        "agent": agent if agent is not None else types.SimpleNamespace(),
        "session_key": "session-key",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        **extra,
    }


def test_compress_session_history_folds_concurrent_tail_on_cas_miss():
    """A concurrent append during compaction must not lose either side.

    The compression call runs WITHOUT the history_lock held; if another
    handler appends to history while it runs (bumping history_version), the
    old behaviour silently discarded the compressed result. We now OR-merge:
    the compacted prefix AND the concurrent tail both survive.
    """
    # Original history: 6 messages. The compressor will collapse the first 5
    # into a single summary, yielding a 2-message compacted baseline.
    original = [
        {"role": "user", "content": "m0"},
        {"role": "assistant", "content": "m1"},
        {"role": "user", "content": "m2"},
        {"role": "assistant", "content": "m3"},
        {"role": "user", "content": "m4"},
        {"role": "assistant", "content": "m5"},
    ]
    compacted = [
        {"role": "system", "content": "summary"},
        {"role": "assistant", "content": "m5"},
    ]
    # The concurrent message that lands DURING compaction.
    concurrent = {"role": "user", "content": "concurrent-while-compacting"}

    session = _session(history=list(original), history_version=0)

    def _fake_compress(history, system_message, **kwargs):
        # Simulate another handler appending under the lock mid-compaction:
        # this is what prompt.submit does (append + version bump).
        with session["history_lock"]:
            session["history"].append(concurrent)
            session["history_version"] += 1
        return list(compacted), {}

    agent = types.SimpleNamespace(model="m")
    agent._compress_context = _fake_compress
    agent._cached_system_prompt = "sys"
    agent.tools = None
    session["agent"] = agent

    removed, _usage = server._compress_session_history(session)

    final = session["history"]
    # Both survive: the compacted baseline (the compaction work) PLUS the
    # concurrent tail folded onto the end (the concurrent addition).
    assert final[: len(compacted)] == compacted
    assert final[len(compacted):] == [concurrent]
    assert concurrent in final
    # `removed` is the TRUE net removal relative to the snapshot: the snapshot
    # held len(original) messages and the session now holds len(final). The
    # folded concurrent tail is NOT something compaction removed, so removed
    # must reconcile with the surfaced before/after counts (before_count -
    # after_count), not over-report by len(tail).
    assert removed == len(original) - len(final)
    assert removed == len(original) - len(compacted) - 1  # 1 = folded tail
    # Version advanced past the concurrent writer's bump, staying monotonic.
    assert session["history_version"] >= 2


def test_compress_session_history_discards_when_concurrent_rewrite_on_cas_miss():
    """A concurrent TRUNCATE/REWRITE (retry/rewind, /new) must DISCARD, not fold.

    The fold path assumes the concurrent mutation is APPEND-ONLY — that the
    snapshot `before_messages` is a strict prefix of `current`. Mutators that
    truncate or rewrite history in place (session retry/rewind, /new) ALSO
    bump history_version, but there `before_messages` is NOT a prefix of
    `current`; folding the compacted prefix back on would corrupt history.
    For those we must fall back to the original safe behaviour: drop the
    stale compaction result, leave the concurrent `current` intact, report 0.
    """
    original = [
        {"role": "user", "content": "m0"},
        {"role": "assistant", "content": "m1"},
        {"role": "user", "content": "m2"},
        {"role": "assistant", "content": "m3"},
        {"role": "user", "content": "m4"},
        {"role": "assistant", "content": "m5"},
    ]
    compacted = [
        {"role": "system", "content": "summary"},
        {"role": "assistant", "content": "m5"},
    ]
    # The concurrent REWRITE: a totally different history (e.g. a rewind that
    # truncated to a single earlier message). NOT a prefix of `original`.
    rewritten = [{"role": "user", "content": "rewound-to-here"}]

    session = _session(history=list(original), history_version=0)

    def _fake_compress(history, system_message, **kwargs):
        # Simulate a retry/rewind replacing history wholesale under the lock.
        with session["history_lock"]:
            session["history"] = list(rewritten)
            session["history_version"] += 1
        return list(compacted), {}

    agent = types.SimpleNamespace(model="m")
    agent._compress_context = _fake_compress
    agent._cached_system_prompt = "sys"
    agent.tools = None
    session["agent"] = agent

    removed, _usage = server._compress_session_history(session)

    # The concurrent rewrite is preserved verbatim — the compaction work and
    # the would-be-folded tail are BOTH dropped (no prefix → no fold).
    assert session["history"] == rewritten
    # We did not adopt the compacted baseline anywhere in history.
    assert compacted[0] not in session["history"]
    # Discard reports no removal.
    assert removed == 0
    # Version is the one the concurrent rewriter set — we did NOT bump again.
    assert session["history_version"] == 1


def test_compress_session_history_normal_path_replaces_history():
    """No concurrent mutation: compaction replaces history and bumps version."""
    original = [
        {"role": "user", "content": "a"},
        {"role": "assistant", "content": "b"},
        {"role": "user", "content": "c"},
        {"role": "assistant", "content": "d"},
    ]
    compacted = [{"role": "system", "content": "summary"}]
    session = _session(history=list(original), history_version=3)

    agent = types.SimpleNamespace(model="m")
    agent._compress_context = lambda history, system_message, **kw: (
        list(compacted),
        {},
    )
    agent._cached_system_prompt = "sys"
    agent.tools = None
    session["agent"] = agent

    server._compress_session_history(session)

    assert session["history"] == compacted
    assert session["history_version"] == 4


def test_session_close_commits_memory_and_fires_finalize_hook(monkeypatch):
    calls = {"hooks": []}

    agent = types.SimpleNamespace(session_id="session-key")
    agent.commit_memory_session = lambda history: calls.setdefault("history", history)
    server._sessions["sid"] = _session(
        agent=agent, history=[{"role": "user", "content": "hello"}]
    )
    monkeypatch.setattr(
        server,
        "_notify_session_boundary",
        lambda event, session_id: calls["hooks"].append((event, session_id)),
    )

    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.close", "params": {"session_id": "sid"}}
        )
        assert resp["result"]["closed"] is True
        assert calls["history"] == [{"role": "user", "content": "hello"}]
        assert ("on_session_finalize", "session-key") in calls["hooks"]
    finally:
        server._sessions.pop("sid", None)


def test_session_save_writes_forecast_transcript_snapshot(monkeypatch, tmp_path):
    home = tmp_path / "agent-home"
    history = [{"role": "user", "content": "Will ACME default by year-end?"}]
    agent = types.SimpleNamespace(model="forecast-model")
    server._sessions["sid"] = _session(agent=agent, history=history)
    monkeypatch.setattr(server, "_hermes_home", home)

    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.save", "params": {"session_id": "sid"}}
        )

        assert "result" in resp, resp
        saved = Path(resp["result"]["file"])
        assert saved.parent == home / "sessions" / "saved"
        assert saved.name.startswith("forecast_transcript_")
        assert saved.suffix == ".json"
        assert "hermes_conversation" not in saved.name

        payload = json.loads(saved.read_text(encoding="utf-8"))
        assert payload == {
            "model": "forecast-model",
            "session_id": "sid",
            "session_key": "session-key",
            "messages": history,
        }
    finally:
        server._sessions.pop("sid", None)


def test_init_session_fires_reset_hook(monkeypatch):
    hooks = []

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key

        def close(self):
            return None

    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        server,
        "_notify_session_boundary",
        lambda event, session_id: hooks.append((event, session_id)),
    )

    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)
    # Don't start the real notification poller: this test doesn't exercise
    # it, and a leaked poller daemon consumes the process-global
    # completion_queue, starving later async-delegation tests on the worker.
    monkeypatch.setattr(
        server, "_start_notification_poller", lambda _sid, _session: threading.Event()
    )

    sid = "sid"
    try:
        server._init_session(
            sid,
            "session-key",
            types.SimpleNamespace(model="x"),
            history=[],
            cols=80,
        )
        assert ("on_session_reset", "session-key") in hooks
    finally:
        # _init_session starts the notification-poller daemon thread. Stop it,
        # or it outlives this test consuming the process-global
        # process_registry.completion_queue and starves any later
        # async-delegation test on the same xdist worker.
        _sess = server._sessions.pop(sid, None)
        if _sess is not None:
            _sess["_finalized"] = True
            _stop = _sess.get("_notif_stop")
            if _stop is not None:
                _stop.set()


def test_session_title_queues_when_db_row_not_ready(monkeypatch):
    class _FakeDB:
        def get_session_title(self, _key):
            return None

        def get_session(self, _key):
            return None

        def set_session_title(self, _key, _title):
            return False

    server._sessions["sid"] = _session(pending_title=None)
    monkeypatch.setattr(server, "_get_db", lambda: _FakeDB())
    try:
        set_resp = server.handle_request(
            {
                "id": "1",
                "method": "session.title",
                "params": {"session_id": "sid", "title": "queued title"},
            }
        )

        assert set_resp["result"]["pending"] is True
        assert set_resp["result"]["title"] == "queued title"
        assert server._sessions["sid"]["pending_title"] == "queued title"

        get_resp = server.handle_request(
            {"id": "2", "method": "session.title", "params": {"session_id": "sid"}}
        )
        assert get_resp["result"]["title"] == "queued title"
    finally:
        server._sessions.pop("sid", None)


def test_session_title_clears_pending_after_persist(monkeypatch):
    class _FakeDB:
        def __init__(self):
            self.title = "old"

        def get_session_title(self, _key):
            return self.title

        def get_session(self, _key):
            return {"id": _key, "title": self.title}

        def set_session_title(self, _key, title):
            self.title = title
            return True

    db = _FakeDB()
    server._sessions["sid"] = _session(pending_title="stale")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.title",
                "params": {"session_id": "sid", "title": "fresh"},
            }
        )

        assert resp["result"]["pending"] is False
        assert resp["result"]["title"] == "fresh"
        assert server._sessions["sid"]["pending_title"] is None
    finally:
        server._sessions.pop("sid", None)


def test_session_title_does_not_queue_noop_when_row_exists(monkeypatch):
    class _FakeDB:
        def __init__(self):
            self.title = "same title"

        def get_session_title(self, _key):
            return self.title

        def get_session(self, _key):
            return {"id": _key, "title": self.title}

        def set_session_title(self, _key, _title):
            # Simulate sqlite UPDATE rowcount==0 for no-op update.
            return False

    server._sessions["sid"] = _session(pending_title="stale")
    monkeypatch.setattr(server, "_get_db", lambda: _FakeDB())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.title",
                "params": {"session_id": "sid", "title": "same title"},
            }
        )

        assert resp["result"]["pending"] is False
        assert resp["result"]["title"] == "same title"
        assert server._sessions["sid"]["pending_title"] is None
    finally:
        server._sessions.pop("sid", None)


def test_session_title_get_falls_back_to_pending_when_db_read_throws(monkeypatch):
    class _FakeDB:
        def get_session_title(self, _key):
            raise RuntimeError("db temporarily locked")

    server._sessions["sid"] = _session(pending_title="queued title")
    monkeypatch.setattr(server, "_get_db", lambda: _FakeDB())
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.title", "params": {"session_id": "sid"}}
        )
        assert resp["result"]["title"] == "queued title"
    finally:
        server._sessions.pop("sid", None)


def test_session_title_get_retries_persist_for_pending_title(monkeypatch):
    class _FakeDB:
        def __init__(self):
            self.title = ""

        def get_session_title(self, _key):
            return self.title

        def set_session_title(self, _key, title):
            self.title = title
            return True

        def get_session(self, _key):
            return {"id": _key, "title": self.title}

    db = _FakeDB()
    server._sessions["sid"] = _session(pending_title="queued title")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.title", "params": {"session_id": "sid"}}
        )
        assert resp["result"]["title"] == "queued title"
        assert server._sessions["sid"]["pending_title"] is None
    finally:
        server._sessions.pop("sid", None)


def test_session_title_get_retries_pending_even_when_db_has_title(monkeypatch):
    class _FakeDB:
        def __init__(self):
            self.title = "auto title"

        def get_session_title(self, _key):
            return self.title

        def set_session_title(self, _key, title):
            self.title = title
            return True

        def get_session(self, _key):
            return {"id": _key, "title": self.title}

    db = _FakeDB()
    server._sessions["sid"] = _session(pending_title="queued title")
    monkeypatch.setattr(server, "_get_db", lambda: db)
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.title", "params": {"session_id": "sid"}}
        )
        assert resp["result"]["title"] == "queued title"
        assert server._sessions["sid"]["pending_title"] is None
    finally:
        server._sessions.pop("sid", None)


def test_session_title_rejects_empty_title_with_specific_error_code(monkeypatch):
    class _FakeDB:
        def get_session_title(self, _key):
            return ""

    server._sessions["sid"] = _session()
    monkeypatch.setattr(server, "_get_db", lambda: _FakeDB())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.title",
                "params": {"session_id": "sid", "title": "   "},
            }
        )
        assert "error" in resp
        assert resp["error"]["code"] == 4021
    finally:
        server._sessions.pop("sid", None)


def test_session_title_set_maps_valueerror_to_user_error(monkeypatch):
    class _FakeDB:
        def get_session_title(self, _key):
            return ""

        def get_session(self, _key):
            return {"id": _key}

        def set_session_title(self, _key, _title):
            raise ValueError("Title already in use")

    server._sessions["sid"] = _session()
    monkeypatch.setattr(server, "_get_db", lambda: _FakeDB())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.title",
                "params": {"session_id": "sid", "title": "dup"},
            }
        )
        assert "error" in resp
        assert resp["error"]["code"] == 4022
        assert "already in use" in resp["error"]["message"]
    finally:
        server._sessions.pop("sid", None)


def test_session_title_set_errors_when_row_lookup_fails_after_noop(monkeypatch):
    class _FakeDB:
        def get_session_title(self, _key):
            return ""

        def get_session(self, _key):
            raise RuntimeError("row lookup failed")

        def set_session_title(self, _key, _title):
            return False

    server._sessions["sid"] = _session()
    monkeypatch.setattr(server, "_get_db", lambda: _FakeDB())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.title",
                "params": {"session_id": "sid", "title": "fresh"},
            }
        )
        assert "error" in resp
        assert resp["error"]["code"] == 5007
        assert "row lookup failed" in resp["error"]["message"]
    finally:
        server._sessions.pop("sid", None)


def test_session_create_drops_pending_title_on_valueerror(monkeypatch):
    """When set_session_title raises ValueError during post-message title flush,
    pending_title should be dropped (non-retryable). Updated for post-#18370
    lazy session creation where title is applied post-first-message.
    """

    class _Agent:
        session_id = "test-session"
        model = "x"
        provider = "openrouter"
        base_url = ""
        api_key = ""
        _cached_system_prompt = ""

        def run_conversation(self, prompt, **kw):
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _FakeDB:
        def set_session_title(self, _key, _title):
            raise ValueError("Title already in use")

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, **kw):
            self._target = target

        def start(self):
            self._target()

    agent = _Agent()
    session = {
        "agent": agent,
        "session_key": "test-session",
        "history": [],
        "history_lock": threading.Lock(),
        "history_version": 0,
        "running": False,
        "attached_images": [],
        "image_counter": 0,
        "cols": 80,
        "slash_worker": None,
        "show_reasoning": False,
        "tool_progress_mode": "all",
        "pending_title": "duplicate title",
    }

    server._sessions["sid"] = session
    from superforecasting_agent.storage.session import SessionDB
    db = SessionDB()
    monkeypatch.setattr(db, "set_session_title", _FakeDB().set_session_title)
    monkeypatch.setattr(server, "_get_db", lambda: db)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setattr(
        server, "_sync_session_key_after_compress", lambda *a, **kw: None
    )
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)

    try:
        server.handle_request(
            {"id": "1", "method": "prompt.submit", "params": {"session_id": "sid", "text": "hello"}}
        )
        assert session["pending_title"] is None
    finally:
        server._sessions.pop("sid", None)


def test_config_set_yolo_toggles_session_scope():
    from tools.approval import clear_session, is_session_yolo_enabled

    server._sessions["sid"] = _session()
    try:
        resp_on = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )
        assert resp_on["result"]["value"] == "1"
        assert is_session_yolo_enabled("session-key") is True

        resp_off = server.handle_request(
            {
                "id": "2",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "yolo"},
            }
        )
        assert resp_off["result"]["value"] == "0"
        assert is_session_yolo_enabled("session-key") is False
    finally:
        clear_session("session-key")
        server._sessions.clear()


def test_config_set_fast_updates_live_agent_and_config(monkeypatch):
    writes = []
    emits = []
    agent = types.SimpleNamespace(
        model="openai/gpt-5.4",
        request_overrides={"foo": "bar", "speed": "slow"},
        service_tier=None,
    )
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server, "_write_config_key", lambda path, value: writes.append((path, value))
    )
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "x"})
    monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
    monkeypatch.setattr(
        "superforecasting_agent.runtime.models.resolve_fast_mode_overrides",
        lambda _model_id: {"service_tier": "priority"},
    )

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "fast", "value": "fast"},
            }
        )
        assert resp["result"]["value"] == "fast"
        assert agent.service_tier == "priority"
        assert agent.request_overrides == {
            "foo": "bar",
            "service_tier": "priority",
        }
        assert ("agent.service_tier", "fast") in writes
        assert ("session.info", "sid", {"model": "x"}) in emits

        resp_normal = server.handle_request(
            {
                "id": "2",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "fast", "value": "normal"},
            }
        )
        assert resp_normal["result"]["value"] == "normal"
        assert agent.service_tier is None
        assert agent.request_overrides == {"foo": "bar"}
        assert ("agent.service_tier", "normal") in writes
    finally:
        server._sessions.pop("sid", None)


def test_config_set_fast_status_is_non_mutating(monkeypatch):
    writes = []
    emits = []
    agent = types.SimpleNamespace(service_tier="priority")
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server, "_write_config_key", lambda path, value: writes.append((path, value))
    )
    monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "fast", "value": "status"},
            }
        )
        assert resp["result"]["value"] == "fast"
        assert writes == []
        assert emits == []
    finally:
        server._sessions.pop("sid", None)


def test_config_set_fast_rejects_unsupported_model(monkeypatch):
    writes = []
    agent = types.SimpleNamespace(
        model="unsupported-model",
        request_overrides={},
        service_tier=None,
    )
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server, "_write_config_key", lambda path, value: writes.append((path, value))
    )
    monkeypatch.setattr(
        "superforecasting_agent.runtime.models.resolve_fast_mode_overrides",
        lambda _model_id: None,
    )

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "fast", "value": "fast"},
            }
        )
        assert resp["error"]["code"] == 4002
        assert "not available" in resp["error"]["message"]
        assert agent.service_tier is None
        assert agent.request_overrides == {}
        assert writes == []
    finally:
        server._sessions.pop("sid", None)


def test_config_set_fast_rejects_missing_model(monkeypatch):
    writes = []
    agent = types.SimpleNamespace(
        model="",
        request_overrides={},
        service_tier=None,
    )
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server, "_write_config_key", lambda path, value: writes.append((path, value))
    )

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "fast", "value": "fast"},
            }
        )
        assert resp["error"]["code"] == 4002
        assert "without a selected model" in resp["error"]["message"]
        assert agent.service_tier is None
        assert agent.request_overrides == {}
        assert writes == []
    finally:
        server._sessions.pop("sid", None)


def test_config_busy_get_and_set(monkeypatch):
    writes = []

    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"display": {"busy_input_mode": "steer"}},
    )
    monkeypatch.setattr(
        server, "_write_config_key", lambda path, value: writes.append((path, value))
    )

    get_resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "busy"}}
    )
    assert get_resp["result"]["value"] == "steer"

    set_resp = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"key": "busy", "value": "interrupt"},
        }
    )
    assert set_resp["result"]["value"] == "interrupt"
    assert ("display.busy_input_mode", "interrupt") in writes


def test_config_set_yolo_process_scope_treats_false_like_env_as_disabled(monkeypatch):
    monkeypatch.setenv("HERMES_YOLO_MODE", "false")
    monkeypatch.delenv("SUPERFORECASTING_AGENT_YOLO_MODE", raising=False)
    monkeypatch.delenv("FORECAST_YOLO_MODE", raising=False)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "yolo"},
        }
    )

    assert resp["result"]["value"] == "1"
    assert os.environ.get("SUPERFORECASTING_AGENT_YOLO_MODE") == "1"
    assert os.environ.get("FORECAST_YOLO_MODE") == "1"
    assert os.environ.get("HERMES_YOLO_MODE") == "1"


def test_config_get_statusbar_survives_non_dict_display(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"display": "broken"})

    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "statusbar"}}
    )

    assert resp["result"]["value"] == "top"


def test_config_get_busy_survives_non_dict_display(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"display": "broken"})

    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "busy"}}
    )

    assert resp["result"]["value"] == "interrupt"


def test_config_set_statusbar_survives_non_dict_display(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(yaml.safe_dump({"display": "broken"}))
    monkeypatch.setattr(server, "_hermes_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "statusbar", "value": "bottom"},
        }
    )

    assert resp["result"]["value"] == "bottom"
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["tui_statusbar"] == "bottom"


def test_config_set_details_mode_pins_all_sections(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"display": {"sections": {"tools": "expanded", "activity": "hidden"}}}
        )
    )
    monkeypatch.setattr(server, "_hermes_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode", "value": "collapsed"},
        }
    )

    assert resp["result"] == {"key": "details_mode", "value": "collapsed"}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["details_mode"] == "collapsed"
    assert saved["display"]["sections"] == {
        "thinking": "collapsed",
        "tools": "collapsed",
        "subagents": "collapsed",
        "activity": "collapsed",
    }


def test_config_set_section_writes_per_section_override(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    monkeypatch.setattr(server, "_hermes_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.activity", "value": "hidden"},
        }
    )

    assert resp["result"] == {"key": "details_mode.activity", "value": "hidden"}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["sections"] == {"activity": "hidden"}


def test_config_set_section_clears_override_on_empty_value(tmp_path, monkeypatch):
    import yaml

    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"display": {"sections": {"activity": "hidden", "tools": "expanded"}}}
        )
    )
    monkeypatch.setattr(server, "_hermes_home", tmp_path)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.activity", "value": ""},
        }
    )

    assert resp["result"] == {"key": "details_mode.activity", "value": ""}
    saved = yaml.safe_load(cfg_path.read_text())
    assert saved["display"]["sections"] == {"tools": "expanded"}


def test_config_set_section_rejects_unknown_section_or_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_hermes_home", tmp_path)

    bad_section = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "details_mode.bogus", "value": "hidden"},
        }
    )
    assert bad_section["error"]["code"] == 4002

    bad_mode = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"key": "details_mode.tools", "value": "maximised"},
        }
    )
    assert bad_mode["error"]["code"] == 4002


def test_config_mouse_uses_documented_key_with_legacy_fallback(monkeypatch):
    cfg = {"display": {"tui_mouse": False}}
    writes = []

    monkeypatch.setattr(server, "_load_cfg", lambda: cfg)
    monkeypatch.setattr(
        server, "_write_config_key", lambda path, value: writes.append((path, value))
    )

    get_legacy = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "mouse"}}
    )
    assert get_legacy["result"]["value"] == "off"

    set_toggle = server.handle_request(
        {"id": "2", "method": "config.set", "params": {"key": "mouse"}}
    )
    assert set_toggle["result"] == {"key": "mouse", "value": "on"}
    assert writes == [("display.mouse_tracking", True)]

    cfg["display"] = {"mouse_tracking": 0, "tui_mouse": True}
    get_canonical = server.handle_request(
        {"id": "3", "method": "config.get", "params": {"key": "mouse"}}
    )
    assert get_canonical["result"]["value"] == "off"

    cfg["display"] = {"mouse_tracking": None, "tui_mouse": False}
    get_null = server.handle_request(
        {"id": "4", "method": "config.get", "params": {"key": "mouse"}}
    )
    assert get_null["result"]["value"] == "on"


def test_enable_gateway_prompts_sets_gateway_env(monkeypatch):
    monkeypatch.delenv("SUPERFORECASTING_AGENT_EXEC_ASK", raising=False)
    monkeypatch.delenv("FORECAST_EXEC_ASK", raising=False)
    monkeypatch.delenv("HERMES_EXEC_ASK", raising=False)
    monkeypatch.delenv("HERMES_GATEWAY_SESSION", raising=False)
    monkeypatch.delenv("HERMES_INTERACTIVE", raising=False)

    server._enable_gateway_prompts()

    assert server.os.environ["HERMES_GATEWAY_SESSION"] == "1"
    assert server.os.environ["SUPERFORECASTING_AGENT_EXEC_ASK"] == "1"
    assert server.os.environ["FORECAST_EXEC_ASK"] == "1"
    assert server.os.environ["HERMES_EXEC_ASK"] == "1"
    assert server.os.environ["HERMES_INTERACTIVE"] == "1"


def test_setup_status_reports_provider_config(monkeypatch):
    monkeypatch.setattr("superforecasting_agent.runtime.main._has_any_provider_configured", lambda: False)

    resp = server.handle_request({"id": "1", "method": "setup.status", "params": {}})

    assert resp["result"]["provider_configured"] is False


def test_complete_slash_includes_provider_alias():
    resp = server.handle_request(
        {"id": "1", "method": "complete.slash", "params": {"text": "/pro"}}
    )

    assert any(item["text"] == "provider" for item in resp["result"]["items"])


def test_complete_slash_includes_tui_details_command():
    resp = server.handle_request(
        {"id": "1", "method": "complete.slash", "params": {"text": "/det"}}
    )

    assert any(item["text"] == "/details" for item in resp["result"]["items"])


def test_complete_slash_includes_tui_mouse_command():
    resp = server.handle_request(
        {"id": "1", "method": "complete.slash", "params": {"text": "/mou"}}
    )

    assert any(item["text"] == "/mouse" for item in resp["result"]["items"])


def test_complete_slash_details_args():
    resp_root = server.handle_request(
        {"id": "0", "method": "complete.slash", "params": {"text": "/details"}}
    )
    resp_section = server.handle_request(
        {"id": "1", "method": "complete.slash", "params": {"text": "/details t"}}
    )
    resp_mode = server.handle_request(
        {
            "id": "2",
            "method": "complete.slash",
            "params": {"text": "/details thinking e"},
        }
    )

    assert resp_root["result"]["replace_from"] == len("/details")
    assert any(item["text"] == " thinking" for item in resp_root["result"]["items"])
    assert any(item["text"] == "thinking" for item in resp_section["result"]["items"])
    assert any(item["text"] == "expanded" for item in resp_mode["result"]["items"])


def test_config_set_reasoning_updates_live_session_and_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_hermes_home", tmp_path)
    agent = types.SimpleNamespace(reasoning_config=None)
    server._sessions["sid"] = _session(agent=agent)

    resp_effort = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "low"},
        }
    )
    assert resp_effort["result"]["value"] == "low"
    assert agent.reasoning_config == {"enabled": True, "effort": "low"}

    resp_show = server.handle_request(
        {
            "id": "2",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "show"},
        }
    )
    assert resp_show["result"]["value"] == "show"
    assert server._sessions["sid"]["show_reasoning"] is True
    assert server._load_cfg()["display"]["sections"]["thinking"] == "expanded"

    resp_hide = server.handle_request(
        {
            "id": "3",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "reasoning", "value": "hide"},
        }
    )
    assert resp_hide["result"]["value"] == "hide"
    assert server._sessions["sid"]["show_reasoning"] is False
    assert server._load_cfg()["display"]["sections"]["thinking"] == "hidden"


def test_config_set_verbose_updates_session_mode_and_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "_hermes_home", tmp_path)
    agent = types.SimpleNamespace(verbose_logging=False)
    server._sessions["sid"] = _session(agent=agent)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "verbose", "value": "cycle"},
        }
    )

    assert resp["result"]["value"] == "verbose"
    assert server._sessions["sid"]["tool_progress_mode"] == "verbose"
    assert agent.verbose_logging is True


def test_config_set_model_uses_live_switch_path(monkeypatch):
    server._sessions["sid"] = _session()
    seen = {}

    def _fake_apply(sid, session, raw):
        seen["args"] = (sid, session["session_key"], raw)
        return {"value": "new/model", "warning": "catalog unreachable"}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "model", "value": "new/model"},
        }
    )

    assert resp["result"]["value"] == "new/model"
    assert resp["result"]["warning"] == "catalog unreachable"
    assert seen["args"] == ("sid", "session-key", "new/model")


def test_config_set_model_global_persists(monkeypatch):
    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-old"

        def switch_model(self, **kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="anthropic/claude-sonnet-4.6",
        target_provider="anthropic",
        api_key="sk-new",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
        warning_message="",
    )
    seen = {}
    saved = {}

    def _switch_model(**kwargs):
        seen.update(kwargs)
        return result

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr("superforecasting_agent.runtime.model_switch.switch_model", _switch_model)
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr("superforecasting_agent.runtime.config.save_config", lambda cfg: saved.update(cfg))

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {
                "session_id": "sid",
                "key": "model",
                "value": "anthropic/claude-sonnet-4.6 --global",
            },
        }
    )

    assert resp["result"]["value"] == "anthropic/claude-sonnet-4.6"
    assert seen["is_global"] is True
    assert saved["model"]["default"] == "anthropic/claude-sonnet-4.6"
    assert saved["model"]["provider"] == "anthropic"
    assert saved["model"]["base_url"] == "https://api.anthropic.com"


def test_config_set_model_keeps_provider_switch_session_scoped(monkeypatch):
    """One session's provider switch must not mutate another's environment."""

    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-or"

        def switch_model(self, **_kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="claude-sonnet-4.6",
        target_provider="anthropic",
        api_key="sk-ant",
        base_url="https://api.anthropic.com",
        api_mode="anthropic_messages",
        warning_message="",
    )

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setenv("HERMES_INFERENCE_PROVIDER", "openrouter")
    monkeypatch.setattr(
        "superforecasting_agent.runtime.model_switch.switch_model", lambda **_kwargs: result
    )
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

    server._session_toggles.pop("session-key", None)
    try:
        server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "model",
                    "value": "claude-sonnet-4.6 --provider anthropic",
                },
            }
        )

        assert os.environ["HERMES_INFERENCE_PROVIDER"] == "openrouter"
        toggles = server._session_toggles["session-key"]
        assert toggles["INFERENCE_PROVIDER"] == "anthropic"
        assert toggles["TUI_PROVIDER"] == "anthropic"
    finally:
        server._sessions.pop("sid", None)
        server._session_toggles.pop("session-key", None)


def test_config_set_model_stores_provider_without_process_env(monkeypatch):

    class _Agent:
        provider = "openrouter"
        model = "old/model"
        base_url = ""
        api_key = "sk-or"

        def switch_model(self, **_kwargs):
            return None

    result = types.SimpleNamespace(
        success=True,
        new_model="deepseek-v4-pro",
        target_provider="custom:xuanji",
        api_key="sk-xuanji",
        base_url="https://xuanji.example/v1",
        api_mode="chat_completions",
        warning_message="",
    )

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.delenv("SUPERFORECASTING_AGENT_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("FORECAST_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_TUI_PROVIDER", raising=False)
    monkeypatch.delenv("HERMES_INFERENCE_PROVIDER", raising=False)
    monkeypatch.setattr(
        "superforecasting_agent.runtime.model_switch.switch_model", lambda **_kwargs: result
    )
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

    server._session_toggles.pop("session-key", None)
    try:
        server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "model",
                    "value": "deepseek-v4-pro --provider custom:xuanji",
                },
            }
        )

        for name in (
            "SUPERFORECASTING_AGENT_TUI_PROVIDER",
            "FORECAST_TUI_PROVIDER",
            "HERMES_TUI_PROVIDER",
            "SUPERFORECASTING_AGENT_INFERENCE_PROVIDER",
            "FORECAST_INFERENCE_PROVIDER",
            "HERMES_INFERENCE_PROVIDER",
        ):
            assert name not in os.environ
        toggles = server._session_toggles["session-key"]
        assert toggles["MODEL"] == "deepseek-v4-pro"
        assert toggles["TUI_PROVIDER"] == "custom:xuanji"
    finally:
        server._sessions.pop("sid", None)
        server._session_toggles.pop("session-key", None)


def test_config_set_model_does_not_replace_process_default(monkeypatch):
    class Agent:
        model = "gpt-5.3-codex"
        provider = "openai-codex"
        base_url = ""
        api_key = ""

        def switch_model(self, **kwargs):
            self.model = kwargs["new_model"]
            self.provider = kwargs["new_provider"]

    agent = Agent()
    server._sessions["sid"] = _session(agent=agent)
    monkeypatch.setenv("SUPERFORECASTING_AGENT_TUI_PROVIDER", "openai-codex")
    monkeypatch.setattr(server, "_restart_slash_worker", lambda session: None)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)

    def fake_switch_model(**kwargs):
        return types.SimpleNamespace(
            success=True,
            new_model="anthropic/claude-sonnet-4.6",
            target_provider="anthropic",
            api_key="key",
            base_url="https://api.anthropic.com",
            api_mode="anthropic_messages",
            warning_message="",
        )

    monkeypatch.setattr("superforecasting_agent.runtime.model_switch.switch_model", fake_switch_model)

    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "model",
                    "value": "anthropic/claude-sonnet-4.6 --provider anthropic",
                },
            }
        )

        assert resp["result"]["value"] == "anthropic/claude-sonnet-4.6"
        assert os.environ["SUPERFORECASTING_AGENT_TUI_PROVIDER"] == "openai-codex"
        assert "SUPERFORECASTING_AGENT_MODEL" not in os.environ
        assert "SUPERFORECASTING_AGENT_INFERENCE_MODEL" not in os.environ
        toggles = server._session_toggles["session-key"]
        assert toggles["MODEL"] == "anthropic/claude-sonnet-4.6"
        assert toggles["TUI_PROVIDER"] == "anthropic"
    finally:
        server._sessions.clear()
        server._session_toggles.pop("session-key", None)


def test_config_set_personality_rejects_unknown_name(monkeypatch):
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda cfg=None: {"helpful": "You are helpful."},
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "personality", "value": "bogus"},
        }
    )

    assert "error" in resp
    assert "Unknown forecast style" in resp["error"]["message"]


def test_config_set_personality_preserves_history_and_returns_info(monkeypatch):
    agent = types.SimpleNamespace(
        ephemeral_system_prompt=None, _cached_system_prompt="old"
    )
    session = _session(
        agent=agent,
        history=[{"role": "user", "text": "hi"}],
        history_version=4,
    )
    emits = []

    server._sessions["sid"] = session
    monkeypatch.setattr(
        server,
        "_available_personalities",
        lambda cfg=None: {"helpful": "You are helpful."},
    )
    monkeypatch.setattr(
        server, "_session_info", lambda agent: {"model": getattr(agent, "model", "?")}
    )
    monkeypatch.setattr(server, "_emit", lambda *args: emits.append(args))
    monkeypatch.setattr(server, "_write_config_key", lambda path, value: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"session_id": "sid", "key": "personality", "value": "helpful"},
        }
    )

    assert resp["result"]["history_reset"] is False
    assert resp["result"]["info"] == {"model": "?"}
    # History is preserved with a pivot marker appended
    assert len(session["history"]) == 2
    assert session["history"][0] == {"role": "user", "text": "hi"}
    assert session["history"][1]["role"] == "user"
    assert "persona" in session["history"][1]["content"].lower()
    assert "You are helpful." in session["history"][1]["content"]
    assert session["history_version"] == 5
    # Agent's system prompt was updated in-place with the forecast desk base
    # prompt plus the selected forecast style overlay; cached prompt untouched.
    assert "Superforecasting Agent" in agent.ephemeral_system_prompt
    assert "You are helpful." in agent.ephemeral_system_prompt
    assert agent._cached_system_prompt == "old"
    assert ("session.info", "sid", {"model": "?"}) in emits


def test_session_compress_uses_compress_helper(monkeypatch):
    agent = types.SimpleNamespace()
    server._sessions["sid"] = _session(agent=agent)

    monkeypatch.setattr(
        server,
        "_compress_session_history",
        lambda session, focus_topic=None, **_kw: (2, {"total": 42}),
    )
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "x"})

    with patch("tui_gateway.server._emit") as emit:
        resp = server.handle_request(
            {"id": "1", "method": "session.compress", "params": {"session_id": "sid"}}
        )

    assert resp["result"]["removed"] == 2
    assert resp["result"]["usage"]["total"] == 42
    emit.assert_any_call("session.info", "sid", {"model": "x"})
    # Final status.update clears the pinned "compressing" indicator so the
    # status bar can revert to the neutral state when compaction finishes.
    emit.assert_any_call("status.update", "sid", {"kind": "status", "text": "ready"})


def test_session_compress_syncs_session_key_after_rotation(monkeypatch):
    """When AIAgent._compress_context rotates session_id (compression split),
    the gateway session_key must follow so subsequent approval routing,
    DB title/history lookups, and slash worker resume target the new
    continuation session — mirrors HermesCLI._manual_compress's
    session_id sync (cli.py).
    """
    agent = types.SimpleNamespace(session_id="rotated-id")
    server._sessions["sid"] = _session(agent=agent)
    server._sessions["sid"]["session_key"] = "old-key"
    server._sessions["sid"]["pending_title"] = "stale title"

    monkeypatch.setattr(
        server,
        "_compress_session_history",
        lambda session, focus_topic=None, **_kw: (2, {"total": 42}),
    )
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "x"})
    restart_calls = []
    monkeypatch.setattr(
        server, "_restart_slash_worker", lambda s: restart_calls.append(s)
    )

    try:
        with patch("tui_gateway.server._emit"):
            server.handle_request(
                {
                    "id": "1",
                    "method": "session.compress",
                    "params": {"session_id": "sid"},
                }
            )

        assert server._sessions["sid"]["session_key"] == "rotated-id"
        assert server._sessions["sid"]["pending_title"] is None
        assert len(restart_calls) == 1
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_sets_approval_session_key(monkeypatch):
    from tools.approval import get_current_session_key

    captured = {}

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            captured["session_key"] = get_current_session_key(default="")
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "ping"},
        }
    )

    assert resp["result"]["status"] == "streaming"
    assert captured["session_key"] == "session-key"


def test_prompt_submit_expands_context_refs(monkeypatch):
    captured = {}

    class _Agent:
        model = "test/model"
        base_url = ""
        api_key = ""

        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            captured["prompt"] = prompt
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self):
            self._target()

    fake_ctx = types.ModuleType("agent.context_references")
    fake_ctx.preprocess_context_references = (
        lambda message, **kwargs: types.SimpleNamespace(
            blocked=False,
            message="expanded prompt",
            warnings=[],
            references=[],
            injected_tokens=0,
        )
    )
    fake_meta = types.ModuleType("agent.model_metadata")
    fake_meta.get_model_context_length = lambda *args, **kwargs: 100000

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setitem(sys.modules, "agent.context_references", fake_ctx)
    monkeypatch.setitem(sys.modules, "agent.model_metadata", fake_meta)

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "@diff"},
        }
    )

    assert captured["prompt"] == "expanded prompt"


def test_image_attach_appends_local_image(monkeypatch):
    # The handler imports the file-drop helpers from the lightweight
    # superforecasting_agent.runtime.file_drop module (kept off cli.py's heavy import graph), so the
    # fakes are injected there.
    fake_cli = types.ModuleType("superforecasting_agent.runtime.file_drop")
    fake_cli._IMAGE_EXTENSIONS = {".png"}
    fake_cli._detect_file_drop = lambda raw: {
        "path": Path("/tmp/cat.png"),
        "is_image": True,
        "remainder": "",
    }
    fake_cli._split_path_input = lambda raw: (raw, "")
    fake_cli._resolve_attachment_path = lambda raw: Path("/tmp/cat.png")

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "superforecasting_agent.runtime.file_drop", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "image.attach",
            "params": {"session_id": "sid", "path": "/tmp/cat.png"},
        }
    )

    assert resp["result"]["attached"] is True
    assert resp["result"]["name"] == "cat.png"
    assert len(server._sessions["sid"]["attached_images"]) == 1


def test_image_attach_accepts_unquoted_screenshot_path_with_spaces(monkeypatch):
    screenshot = Path("/tmp/Screenshot 2026-04-21 at 1.04.43 PM.png")
    fake_cli = types.ModuleType("superforecasting_agent.runtime.file_drop")
    fake_cli._IMAGE_EXTENSIONS = {".png"}
    fake_cli._detect_file_drop = lambda raw: {
        "path": screenshot,
        "is_image": True,
        "remainder": "",
    }
    fake_cli._split_path_input = lambda raw: (
        "/tmp/Screenshot",
        "2026-04-21 at 1.04.43 PM.png",
    )
    fake_cli._resolve_attachment_path = lambda raw: None

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "superforecasting_agent.runtime.file_drop", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "image.attach",
            "params": {"session_id": "sid", "path": str(screenshot)},
        }
    )

    assert resp["result"]["attached"] is True
    assert resp["result"]["path"] == str(screenshot)
    assert resp["result"]["remainder"] == ""
    assert len(server._sessions["sid"]["attached_images"]) == 1


def test_commands_catalog_surfaces_quick_commands(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {
            "quick_commands": {
                "build": {"type": "exec", "command": "npm run build"},
                "git": {"type": "alias", "target": "/shell git"},
                "notes": {
                    "type": "exec",
                    "command": "cat NOTES.md",
                    "description": "Open design notes",
                },
            }
        },
    )

    resp = server.handle_request(
        {"id": "1", "method": "commands.catalog", "params": {}}
    )

    pairs = dict(resp["result"]["pairs"])
    assert "npm run build" in pairs["/build"]
    assert pairs["/git"].startswith("alias →")
    assert pairs["/notes"] == "Open design notes"

    user_cat = next(
        c for c in resp["result"]["categories"] if c["name"] == "User commands"
    )
    user_pairs = dict(user_cat["pairs"])
    assert set(user_pairs) == {"/build", "/git", "/notes"}

    assert resp["result"]["canon"]["/build"] == "/build"
    assert resp["result"]["canon"]["/notes"] == "/notes"


def test_commands_catalog_includes_tui_mouse_command():
    resp = server.handle_request(
        {"id": "1", "method": "commands.catalog", "params": {}}
    )

    pairs = dict(resp["result"]["pairs"])
    tui_cat = next(c for c in resp["result"]["categories"] if c["name"] == "TUI")
    tui_pairs = dict(tui_cat["pairs"])

    assert "/mouse" in pairs
    assert "/mouse" in tui_pairs


def test_commands_catalog_filters_gateway_only_commands_and_keeps_status_visible():
    resp = server.handle_request(
        {"id": "1", "method": "commands.catalog", "params": {}}
    )

    pairs = dict(resp["result"]["pairs"])
    canon = resp["result"]["canon"]

    assert "/status" in pairs
    assert canon["/status"] == "/status"

    assert "/topic" not in pairs
    assert "/approve" not in pairs
    assert "/deny" not in pairs
    assert "/sethome" not in pairs

    assert "/update" in pairs
    assert canon["/update"] == "/update"

    assert "/topic" not in canon
    assert "/approve" not in canon
    assert "/deny" not in canon
    assert "/set-home" not in canon


def test_session_status_reads_live_gateway_agent(monkeypatch):
    agent = types.SimpleNamespace(
        model="live-model",
        provider="live-provider",
        session_total_tokens=1234,
    )
    server._sessions["sid"] = _session(agent=agent, running=True)

    class _DB:
        def get_session(self, key):
            assert key == "session-key"
            return {
                "title": "Live TUI",
                "started_at": 1_700_000_000,
                "updated_at": 1_700_000_060,
            }

    monkeypatch.setattr(server, "_get_db", lambda: _DB())
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.status", "params": {"session_id": "sid"}}
        )
    finally:
        server._sessions.pop("sid", None)

    out = resp["result"]["output"]
    assert "Superforecasting Agent TUI Status" in out
    assert "Session ID: session-key" in out
    assert "Title: Live TUI" in out
    assert "Model: live-model (live-provider)" in out
    assert "Tokens: 1,234" in out
    assert "Agent Running: Yes" in out


def test_skills_reload_runs_in_gateway_process(monkeypatch):
    import agent.skill_commands as skill_commands

    called = {}
    monkeypatch.setattr(
        skill_commands,
        "reload_skills",
        lambda: called.setdefault(
            "result",
            {
                "added": [{"name": "new-skill", "description": "demo"}],
                "removed": [],
                "total": 42,
            },
        ),
    )

    resp = server.handle_request({"id": "1", "method": "skills.reload", "params": {}})

    assert called["result"]["total"] == 42
    assert "new-skill" in resp["result"]["output"]
    assert "42 skill(s) available" in resp["result"]["output"]


def test_snapshot_restore_is_blocked_from_tui_worker():
    server._sessions["sid"] = _session()
    try:
        worker_resp = server.handle_request(
            {
                "id": "1",
                "method": "slash.exec",
                "params": {"command": "snapshot restore latest", "session_id": "sid"},
            }
        )
        dispatch_resp = server.handle_request(
            {
                "id": "2",
                "method": "command.dispatch",
                "params": {
                    "arg": "restore latest",
                    "name": "snapshot",
                    "session_id": "sid",
                },
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert worker_resp["error"]["code"] == 4018
    assert (
        "snapshot restore mutates live config/state" in worker_resp["error"]["message"]
    )
    assert dispatch_resp["result"]["type"] == "exec"
    assert (
        "/snapshot restore is blocked in the TUI" in dispatch_resp["result"]["output"]
    )


def test_command_dispatch_exec_nonzero_surfaces_error(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"quick_commands": {"boom": {"type": "exec", "command": "boom"}}},
    )
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda *args, **kwargs: types.SimpleNamespace(
            returncode=1, stdout="", stderr="failed"
        ),
    )

    resp = server.handle_request(
        {"id": "1", "method": "command.dispatch", "params": {"name": "boom"}}
    )

    assert "error" in resp
    assert "failed" in resp["error"]["message"]


def test_plugins_list_surfaces_loader_error(monkeypatch):
    with patch("superforecasting_agent.runtime.plugins.get_plugin_manager", side_effect=Exception("boom")):
        resp = server.handle_request(
            {"id": "1", "method": "plugins.list", "params": {}}
        )

    assert "error" in resp
    assert "boom" in resp["error"]["message"]


def test_complete_slash_surfaces_completer_error(monkeypatch):
    with patch(
        "superforecasting_agent.runtime.commands.SlashCommandCompleter",
        side_effect=Exception("no completer"),
    ):
        resp = server.handle_request(
            {"id": "1", "method": "complete.slash", "params": {"text": "/mo"}}
        )

    assert "error" in resp
    assert "no completer" in resp["error"]["message"]


def test_input_detect_drop_attaches_image(monkeypatch):
    # input.detect_drop imports _detect_file_drop from the lightweight
    # superforecasting_agent.runtime.file_drop module (off cli.py's hot path), so patch it there.
    fake_cli = types.ModuleType("superforecasting_agent.runtime.file_drop")
    fake_cli._detect_file_drop = lambda raw: {
        "path": Path("/tmp/cat.png"),
        "is_image": True,
        "remainder": "",
    }

    server._sessions["sid"] = _session()
    monkeypatch.setitem(sys.modules, "superforecasting_agent.runtime.file_drop", fake_cli)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "input.detect_drop",
            "params": {"session_id": "sid", "text": "/tmp/cat.png"},
        }
    )

    assert resp["result"]["matched"] is True
    assert resp["result"]["is_image"] is True
    assert resp["result"]["text"] == "[User attached image: cat.png]"


def test_input_detect_drop_path_with_spaces(tmp_path):
    """input.detect_drop correctly handles image paths containing spaces."""
    # Create a minimal PNG file with a space in its name
    img = tmp_path / "screenshot with spaces.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n")  # valid PNG header

    server._sessions["sid"] = _session()

    resp = server.handle_request(
        {
            "id": "2",
            "method": "input.detect_drop",
            "params": {"session_id": "sid", "text": str(img)},
        }
    )

    assert resp["result"]["matched"] is True
    assert resp["result"]["is_image"] is True
    assert resp["result"]["path"] == str(img)
    assert resp["result"]["text"] == f"[User attached image: {img.name}]"
    # Verify attachment was recorded in the session
    assert len(server._sessions["sid"]["attached_images"]) == 1
    assert server._sessions["sid"]["attached_images"][0] == str(img)


def test_input_detect_drop_path_with_spaces_and_remainder(tmp_path):
    """input.detect_drop splits remainder when path contains spaces."""
    img = tmp_path / "photo with space.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"fakejpeg")  # minimal-ish JPEG header

    server._sessions["sid"] = _session()

    user_input = f"{img} describe this image"
    resp = server.handle_request(
        {
            "id": "3",
            "method": "input.detect_drop",
            "params": {"session_id": "sid", "text": user_input},
        }
    )

    assert resp["result"]["matched"] is True
    assert resp["result"]["is_image"] is True
    assert resp["result"]["path"] == str(img)
    # Remainder becomes the text sent to the model
    assert resp["result"]["text"] == "describe this image"
    assert server._sessions["sid"]["attached_images"][0] == str(img)


def test_rollback_restore_resolves_number_and_file_path():
    calls = {}

    class _Mgr:
        enabled = True

        def list_checkpoints(self, cwd):
            return [{"hash": "aaa111"}, {"hash": "bbb222"}]

        def restore(self, cwd, target, file_path=None):
            calls["args"] = (cwd, target, file_path)
            return {"success": True, "message": "done"}

    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(_checkpoint_mgr=_Mgr()), history=[]
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "rollback.restore",
            "params": {"session_id": "sid", "hash": "2", "file_path": "src/app.tsx"},
        }
    )

    assert resp["result"]["success"] is True
    assert calls["args"][1] == "bbb222"
    assert calls["args"][2] == "src/app.tsx"


# ── session.steer ────────────────────────────────────────────────────


def test_session_steer_calls_agent_steer_when_agent_supports_it():
    """The TUI RPC method must call agent.steer(text) and return a
    queued status without touching interrupt state.
    """
    calls = {}

    class _Agent:
        def steer(self, text):
            calls["steer_text"] = text
            return True

        def interrupt(self, *args, **kwargs):
            calls["interrupt_called"] = True

    server._sessions["sid"] = _session(agent=_Agent())
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "also check auth.log"},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "result" in resp, resp
    assert resp["result"]["status"] == "queued"
    assert resp["result"]["text"] == "also check auth.log"
    assert calls["steer_text"] == "also check auth.log"
    assert "interrupt_called" not in calls  # must NOT interrupt


def test_session_steer_rejects_empty_text():
    server._sessions["sid"] = _session(
        agent=types.SimpleNamespace(steer=lambda t: True)
    )
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "   "},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4002


def test_session_steer_errors_when_agent_has_no_steer_method():
    server._sessions["sid"] = _session(agent=types.SimpleNamespace())  # no steer()
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.steer",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
    finally:
        server._sessions.pop("sid", None)

    assert "error" in resp, resp
    assert resp["error"]["code"] == 4010


def test_session_info_includes_mcp_servers(monkeypatch):
    fake_status = [
        {"name": "github", "transport": "http", "tools": 12, "connected": True},
        {"name": "filesystem", "transport": "stdio", "tools": 4, "connected": True},
        {"name": "broken", "transport": "stdio", "tools": 0, "connected": False},
    ]
    fake_mod = types.ModuleType("tools.mcp_tool")
    fake_mod.get_mcp_status = lambda: fake_status
    monkeypatch.setitem(sys.modules, "tools.mcp_tool", fake_mod)

    info = server._session_info(types.SimpleNamespace(tools=[], model=""))

    assert info["mcp_servers"] == fake_status


# ---------------------------------------------------------------------------
# History-mutating commands must reject while session.running is True.
# Without these guards, prompt.submit's post-run history write either
# clobbers the mutation (version matches) or silently drops the agent's
# output (version mismatch) — both produce UI<->backend state desync.
# ---------------------------------------------------------------------------


def test_session_undo_rejects_while_running():
    """Fix for TUI silent-drop #1: /undo must not mutate history
    while the agent is mid-turn — would either clobber the undo or
    cause prompt.submit to silently drop the agent's response."""
    server._sessions["sid"] = _session(
        running=True,
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.undo", "params": {"session_id": "sid"}}
        )
        assert resp.get("error"), "session.undo should reject while running"
        assert resp["error"]["code"] == 4009
        assert "session busy" in resp["error"]["message"]
        # History must be unchanged
        assert len(server._sessions["sid"]["history"]) == 2
    finally:
        server._sessions.pop("sid", None)


def test_session_undo_allowed_when_idle():
    """Regression guard: when not running, /undo still works."""
    server._sessions["sid"] = _session(
        running=False,
        history=[
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ],
    )
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.undo", "params": {"session_id": "sid"}}
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"
        assert resp["result"]["removed"] == 2
        assert server._sessions["sid"]["history"] == []
    finally:
        server._sessions.pop("sid", None)


def test_session_compress_rejects_while_running(monkeypatch):
    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {"id": "1", "method": "session.compress", "params": {"session_id": "sid"}}
        )
        assert resp.get("error")
        assert resp["error"]["code"] == 4009
    finally:
        server._sessions.pop("sid", None)


def test_rollback_restore_rejects_full_history_while_running(monkeypatch):
    """Full-history rollback must reject; file-scoped rollback still allowed."""
    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "rollback.restore",
                "params": {"session_id": "sid", "hash": "abc"},
            }
        )
        assert resp.get("error"), "full-history rollback should reject while running"
        assert resp["error"]["code"] == 4009
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_history_version_mismatch_surfaces_warning(monkeypatch):
    """Fix for TUI silent-drop #2: the defensive backstop at prompt.submit
    must attach a 'warning' to message.complete when history was
    mutated externally during the turn (instead of silently dropping
    the agent's output)."""
    # Agent bumps history_version itself mid-run to simulate an external
    # mutation slipping past the guards.
    session_ref = {"s": None}

    class _RacyAgent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            # Simulate: something external bumped history_version
            # while we were running.
            with session_ref["s"]["history_lock"]:
                session_ref["s"]["history_version"] += 1
            return {
                "final_response": "agent reply",
                "messages": [{"role": "assistant", "content": "agent reply"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_RacyAgent())
    session_ref["s"] = server._sessions["sid"]
    emits: list[tuple] = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")
        monkeypatch.setattr(server, "_emit", lambda *a: emits.append(a))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"

        # History should NOT contain the agent's output (version mismatch)
        assert server._sessions["sid"]["history"] == []

        # message.complete must carry a 'warning' so the UI / operator
        # knows the output was not persisted.
        complete_calls = [a for a in emits if a[0] == "message.complete"]
        assert len(complete_calls) == 1
        _, _, payload = complete_calls[0]
        assert "warning" in payload, (
            "message.complete must include a 'warning' field on "
            "history_version mismatch — otherwise the UI silently "
            "shows output that was never persisted"
        )
        assert (
            "not saved" in payload["warning"].lower()
            or "changed" in payload["warning"].lower()
        )
    finally:
        server._sessions.pop("sid", None)


def test_prompt_submit_history_version_match_persists_normally(monkeypatch):
    """Regression guard: the backstop does not affect the happy path."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            return {
                "final_response": "reply",
                "messages": [{"role": "assistant", "content": "reply"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target

        def start(self):
            self._target()

    server._sessions["sid"] = _session(agent=_Agent())
    emits: list[tuple] = []
    try:
        monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
        monkeypatch.setattr(server, "_get_usage", lambda _a: {})
        monkeypatch.setattr(server, "render_message", lambda _t, _c: "")
        monkeypatch.setattr(server, "_emit", lambda *a: emits.append(a))

        resp = server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "hi"},
            }
        )
        assert resp.get("result")

        # History was written
        assert server._sessions["sid"]["history"] == [
            {"role": "assistant", "content": "reply"}
        ]
        assert server._sessions["sid"]["history_version"] == 1

        # No warning should be attached
        complete_calls = [a for a in emits if a[0] == "message.complete"]
        assert len(complete_calls) == 1
        _, _, payload = complete_calls[0]
        assert "warning" not in payload
    finally:
        server._sessions.pop("sid", None)


# ---------------------------------------------------------------------------
# session.interrupt must only cancel pending prompts owned by the calling
# session — it must not blast-resolve clarify/sudo/secret prompts on
# unrelated sessions sharing the same tui_gateway process.  Without
# session scoping the other sessions' prompts silently resolve to empty
# strings, unblocking their agent threads as if the user cancelled.
# ---------------------------------------------------------------------------


def test_interrupt_only_clears_own_session_pending():
    """session.interrupt on session A must NOT release pending prompts
    that belong to session B."""
    import types

    session_a = _session()
    session_a["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    session_b = _session()
    session_b["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    server._sessions["sid_a"] = session_a
    server._sessions["sid_b"] = session_b

    try:
        # Simulate pending prompts on both sessions (what _block creates
        # while a clarify/sudo/secret request is outstanding).
        ev_a = threading.Event()
        ev_b = threading.Event()
        server._pending["rid-a"] = ("sid_a", ev_a)
        server._pending["rid-b"] = ("sid_b", ev_b)
        server._answers.clear()

        # Interrupt session A.
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.interrupt",
                "params": {"session_id": "sid_a"},
            }
        )
        assert resp.get("result"), f"got error: {resp.get('error')}"

        # Session A's pending must be released to empty.
        assert ev_a.is_set(), "sid_a pending Event should be set after interrupt"
        assert server._answers.get("rid-a") == ""

        # Session B's pending MUST remain untouched — no cross-session blast.
        assert not ev_b.is_set(), (
            "CRITICAL: session.interrupt on sid_a released a pending prompt "
            "belonging to sid_b — other sessions' clarify/sudo/secret "
            "prompts are being silently cancelled"
        )
        assert "rid-b" not in server._answers
    finally:
        server._sessions.pop("sid_a", None)
        server._sessions.pop("sid_b", None)
        server._pending.pop("rid-a", None)
        server._pending.pop("rid-b", None)
        server._answers.pop("rid-a", None)
        server._answers.pop("rid-b", None)


def test_interrupt_clears_multiple_own_pending():
    """When a single session has multiple pending prompts (uncommon but
    possible via nested tool calls), interrupt must release all of them."""
    import types

    sess = _session()
    sess["agent"] = types.SimpleNamespace(interrupt=lambda: None)
    server._sessions["sid"] = sess

    try:
        ev1, ev2 = threading.Event(), threading.Event()
        server._pending["r1"] = ("sid", ev1)
        server._pending["r2"] = ("sid", ev2)

        resp = server.handle_request(
            {"id": "1", "method": "session.interrupt", "params": {"session_id": "sid"}}
        )
        assert resp.get("result")
        assert ev1.is_set() and ev2.is_set()
        assert server._answers.get("r1") == "" and server._answers.get("r2") == ""
    finally:
        server._sessions.pop("sid", None)
        for key in ("r1", "r2"):
            server._pending.pop(key, None)
            server._answers.pop(key, None)


def test_clear_pending_without_sid_clears_all():
    """_clear_pending(None) is the shutdown path — must still release
    every pending prompt regardless of owning session."""
    ev1, ev2, ev3 = threading.Event(), threading.Event(), threading.Event()
    server._pending["a"] = ("sid_x", ev1)
    server._pending["b"] = ("sid_y", ev2)
    server._pending["c"] = ("sid_z", ev3)
    try:
        server._clear_pending(None)
        assert ev1.is_set() and ev2.is_set() and ev3.is_set()
    finally:
        for key in ("a", "b", "c"):
            server._pending.pop(key, None)
            server._answers.pop(key, None)


def test_respond_unpacks_sid_tuple_correctly():
    """After the (sid, Event) tuple change, _respond must still work."""
    ev = threading.Event()
    server._pending["rid-x"] = ("sid_x", ev)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "clarify.respond",
                "params": {"request_id": "rid-x", "answer": "the answer"},
            }
        )
        assert resp.get("result")
        assert ev.is_set()
        assert server._answers.get("rid-x") == "the answer"
    finally:
        server._pending.pop("rid-x", None)
        server._answers.pop("rid-x", None)


# ---------------------------------------------------------------------------
# /model switch and other agent-mutating commands must reject while the
# session is running.  agent.switch_model() mutates self.model, self.provider,
# self.base_url, self.client etc. in place — the worker thread running
# agent.run_conversation is reading those on every iteration.  Same class of
# bug as the session.undo / session.compress mid-run silent-drop; same fix
# pattern: reject with 4009 while running.
# ---------------------------------------------------------------------------


def test_config_set_model_rejects_while_running(monkeypatch):
    """/model via config.set must reject during an in-flight turn."""
    seen = {"called": False}

    def _fake_apply(sid, session, raw):
        seen["called"] = True
        return {"value": raw, "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)

    server._sessions["sid"] = _session(running=True)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {
                    "session_id": "sid",
                    "key": "model",
                    "value": "anthropic/claude-sonnet-4.6",
                },
            }
        )
        assert resp.get("error")
        assert resp["error"]["code"] == 4009
        assert "session busy" in resp["error"]["message"]
        assert not seen["called"], (
            "_apply_model_switch was called mid-turn — would race with "
            "the worker thread reading agent.model / agent.client"
        )
    finally:
        server._sessions.pop("sid", None)


def test_config_set_model_allowed_when_idle(monkeypatch):
    """Regression guard: idle sessions can still switch models."""
    seen = {"called": False}

    def _fake_apply(sid, session, raw):
        seen["called"] = True
        return {"value": "newmodel", "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply)

    server._sessions["sid"] = _session(running=False)
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"session_id": "sid", "key": "model", "value": "newmodel"},
            }
        )
        assert resp.get("result")
        assert resp["result"]["value"] == "newmodel"
        assert seen["called"]
    finally:
        server._sessions.pop("sid", None)


# ---------------------------------------------------------------------------
# Switching AWAY from a dead provider must NEVER require that provider's
# credentials.  With codex UNAUTHENTICATED the session never builds an agent,
# so _apply_model_switch takes the no-agent branch — which used to resolve the
# CURRENT (codex) runtime eagerly just to learn the current provider slug,
# raising "No Codex credentials stored" and trapping the user on the very
# provider they were trying to leave.  Same trap-class as the setup Ctrl+C
# and copilot dead-token bugs.
# ---------------------------------------------------------------------------


def _dead_codex_resolver(*, requested=None, target_model=None, **_kw):
    """resolve_runtime_provider stub: the current (codex) provider is dead."""
    from superforecasting_agent.runtime.auth import AuthError

    if requested in {None, "", "openai-codex"}:
        raise AuthError(
            "No Codex credentials stored. Run `/auth` (in the TUI) to authenticate.",
            provider="openai-codex",
            code="codex_auth_missing",
            relogin_required=True,
        )
    raise AssertionError(f"unexpected provider resolution: {requested!r}")


def test_apply_model_switch_away_from_dead_codex_no_agent(monkeypatch):
    """Switching to a DIFFERENT provider with no live agent must not consult
    the dead current (codex) provider's credentials."""
    import superforecasting_agent.runtime.model_switch as ms
    import superforecasting_agent.runtime.runtime_provider as rp
    from superforecasting_agent.runtime.model_switch import ModelSwitchResult

    captured = {}

    def _fake_switch_model(**kwargs):
        captured.update(kwargs)
        return ModelSwitchResult(
            success=True,
            new_model="minimax/minimax-m2.7",
            target_provider="openrouter",
            provider_label="OpenRouter",
            is_global=False,
            api_key="sk-or",
            base_url="https://openrouter.ai/api/v1",
            api_mode="chat_completions",
        )

    monkeypatch.setattr(rp, "resolve_runtime_provider", _dead_codex_resolver)
    monkeypatch.setattr(
        rp, "resolve_requested_provider", lambda requested=None: "openai-codex"
    )
    monkeypatch.setattr(ms, "switch_model", _fake_switch_model)
    monkeypatch.setattr(server, "_store_session_toggle", lambda *a, **k: None)
    monkeypatch.setattr(server, "_resolve_model", lambda: "gpt-5.4")

    # No live agent — agent build died on the dead codex sign-in.
    result = server._apply_model_switch(
        "",
        {"agent": None},
        "minimax/minimax-m2.7 --provider openrouter --tui-session",
    )

    assert result["value"] == "minimax/minimax-m2.7"
    # switch_model was reached; the CURRENT provider was learned from
    # config/env (non-raising), NOT via the credential-demanding runtime
    # resolution.  The TARGET is validated inside switch_model.
    assert captured["current_provider"] == "openai-codex"
    assert captured["explicit_provider"] == "openrouter"


def test_apply_model_switch_no_agent_authed_current_unchanged(monkeypatch):
    """Regression guard: when the current provider resolves fine, the no-agent
    branch still passes its resolved provider/base_url/api_key to switch_model."""
    import superforecasting_agent.runtime.model_switch as ms
    import superforecasting_agent.runtime.runtime_provider as rp
    from superforecasting_agent.runtime.model_switch import ModelSwitchResult

    captured = {}

    def _resolve(*, requested=None, target_model=None, **_kw):
        assert requested is None
        return {
            "provider": "anthropic",
            "base_url": "https://api.anthropic.com",
            "api_key": "sk-ant",
            "api_mode": "anthropic_messages",
        }

    def _fake_switch_model(**kwargs):
        captured.update(kwargs)
        return ModelSwitchResult(
            success=True,
            new_model="minimax/minimax-m2.7",
            target_provider="openrouter",
            provider_label="OpenRouter",
            is_global=False,
            api_key="sk-or",
            base_url="https://openrouter.ai/api/v1",
            api_mode="chat_completions",
        )

    monkeypatch.setattr(rp, "resolve_runtime_provider", _resolve)
    monkeypatch.setattr(ms, "switch_model", _fake_switch_model)
    monkeypatch.setattr(server, "_store_session_toggle", lambda *a, **k: None)
    monkeypatch.setattr(server, "_resolve_model", lambda: "claude-sonnet-4.6")

    result = server._apply_model_switch(
        "",
        {"agent": None},
        "minimax/minimax-m2.7 --provider openrouter --tui-session",
    )

    assert result["value"] == "minimax/minimax-m2.7"
    assert captured["current_provider"] == "anthropic"
    assert captured["current_base_url"] == "https://api.anthropic.com"
    assert captured["current_api_key"] == "sk-ant"


def test_switch_model_to_dead_codex_returns_teaching_error(monkeypatch):
    """Switching TO an unauthenticated provider surfaces the teaching error
    naming that provider — the target's creds are validated, not the source's."""
    import superforecasting_agent.runtime.runtime_provider as rp
    from superforecasting_agent.runtime.auth import AuthError
    from superforecasting_agent.runtime.model_switch import switch_model

    def _resolve(*, requested=None, target_model=None, **_kw):
        if requested == "openai-codex":
            raise AuthError(
                "No Codex credentials stored. Run `/auth` (in the TUI) or "
                "`superforecasting-agent auth` to authenticate.",
                provider="openai-codex",
                code="codex_auth_missing",
                relogin_required=True,
            )
        raise AssertionError(f"unexpected provider resolution: {requested!r}")

    monkeypatch.setattr(rp, "resolve_runtime_provider", _resolve)

    result = switch_model(
        raw_input="gpt-5.4",
        current_provider="anthropic",
        current_model="claude-sonnet-4.6",
        current_base_url="",
        current_api_key="sk-ant",
        is_global=False,
        explicit_provider="openai-codex",
    )

    assert result.success is False
    assert result.target_provider == "openai-codex"
    assert "No Codex credentials stored" in (result.error_message or "")


def test_mirror_slash_side_effects_rejects_mutating_commands_while_running(monkeypatch):
    """Slash worker passthrough (e.g. /model, /style, /prompt,
    /compress) must reject during an in-flight turn.  Same race as
    config.set — mutates live agent state while run_conversation is
    reading it."""
    import types

    applied = {"model": False, "compress": False}

    def _fake_apply_model(sid, session, arg):
        applied["model"] = True
        return {"value": arg, "warning": ""}

    def _fake_compress(session, focus):
        applied["compress"] = True
        return (0, {})

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply_model)
    monkeypatch.setattr(server, "_compress_session_history", _fake_compress)

    session = _session(running=True)
    session["agent"] = types.SimpleNamespace(model="x")

    for cmd, expected_name in [
        ("/model new/model", "model"),
        ("/style default", "style"),
        ("/personality default", "personality"),
        ("/prompt", "prompt"),
        ("/compress", "compress"),
    ]:
        warning = server._mirror_slash_side_effects("sid", session, cmd)
        assert (
            "session busy" in warning
        ), f"{cmd} should have returned busy warning, got: {warning!r}"
        assert f"/{expected_name}" in warning

    # None of the mutating side-effect helpers should have fired.
    assert not applied["model"], "model switch fired despite running session"
    assert not applied["compress"], "compress fired despite running session"


def test_mirror_slash_side_effects_allowed_when_idle(monkeypatch):
    """Regression guard: idle session still runs the side effects."""
    import types

    applied = {"model": False}

    def _fake_apply_model(sid, session, arg):
        applied["model"] = True
        return {"value": arg, "warning": ""}

    monkeypatch.setattr(server, "_apply_model_switch", _fake_apply_model)

    session = _session(running=False)
    session["agent"] = types.SimpleNamespace(model="x")

    warning = server._mirror_slash_side_effects("sid", session, "/model foo")
    # Should NOT contain "session busy" — the switch went through.
    assert "session busy" not in warning
    assert applied["model"]


def test_mirror_slash_compress_does_not_prelock_history(monkeypatch):
    """Regression guard: /compress side effect must not hold history_lock
    when calling _compress_session_history (the helper snapshots under
    the same non-reentrant lock internally)."""
    import types

    seen = {"compress": False, "sync": False}
    emitted = []

    def _fake_compress(session, focus_topic=None, **_kw):
        seen["compress"] = True
        assert not session["history_lock"].locked()
        return (0, {"total": 0})

    def _fake_sync(_sid, _session):
        seen["sync"] = True

    monkeypatch.setattr(server, "_compress_session_history", _fake_compress)
    monkeypatch.setattr(server, "_sync_session_key_after_compress", _fake_sync)
    monkeypatch.setattr(server, "_session_info", lambda _agent: {"model": "x"})
    monkeypatch.setattr(server, "_emit", lambda *args: emitted.append(args))

    session = _session(running=False)
    session["agent"] = types.SimpleNamespace(model="x")

    warning = server._mirror_slash_side_effects("sid", session, "/compress")

    assert warning == ""
    assert seen["compress"]
    assert seen["sync"]
    assert ("session.info", "sid", {"model": "x"}) in emitted


# ---------------------------------------------------------------------------
# session.create / session.close race: fast /new churn must not orphan the
# slash_worker subprocess or the global approval-notify registration.
# ---------------------------------------------------------------------------


def test_session_create_close_race_does_not_orphan_worker(monkeypatch):
    """Busy close preserves initialization ownership; retry releases its resources."""
    import threading

    closed_workers: list[str] = []
    unregistered_keys: list[str] = []
    agent_closed = threading.Event()

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key
            self._closed = False

        def close(self):
            self._closed = True
            closed_workers.append(self.key)

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

        def close(self):
            agent_closed.set()

    # Make _build block until we release it — simulates slow agent init.
    # Also signal when _build actually reaches _make_agent so the test
    # can close the session at the right moment: session.create now
    # defers _start_agent_build behind a 50ms timer (see the
    # `_deferred_build` path in @method("session.create")), so closing
    # before the build thread has even started would skip the orphan
    # detection entirely and the test would race a non-event.
    build_started = threading.Event()
    release_build = threading.Event()
    build_entered = threading.Event()

    def _slow_make_agent(sid, key, session_id=None):
        build_started.set()
        build_entered.set()
        release_build.wait(timeout=3.0)
        return _FakeAgent()

    # Stub everything _build touches
    monkeypatch.setattr(server, "_make_agent", _slow_make_agent)
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(create_session=lambda *a, **kw: None),
    )
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)

    # Shim register/unregister to observe leaks
    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(
        _approval,
        "unregister_gateway_notify",
        lambda key: unregistered_keys.append(key),
    )
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    # Start: session.create spawns _build thread, returns synchronously
    resp = server.handle_request(
        {
            "id": "1",
            "method": "session.create",
            "params": {"cols": 80},
        }
    )
    assert resp.get("result"), f"got error: {resp.get('error')}"
    sid = resp["result"]["session_id"]
    session = server._sessions[sid]
    assert build_entered.wait(timeout=1.0), "deferred build did not start"

    # Wait until the (deferred) build thread has actually entered
    # _make_agent — otherwise session.close pops _sessions[sid] before
    # _build ever runs, _start_agent_build never calls _build, and we
    # never exercise the orphan-cleanup path.
    assert build_started.wait(timeout=2.0), "build thread never entered _make_agent"

    # Busy close must preserve the builder's ownership, then succeed on retry.
    try:
        close_resp = server.handle_request({
            "id": "2", "method": "session.close", "params": {"session_id": sid},
        })
        assert close_resp["error"]["code"] == 4009
        assert server._sessions[sid] is session
        assert not agent_closed.is_set()
    finally:
        release_build.set()
    assert session["agent_ready"].wait(timeout=2.0)
    close_resp = server.handle_request({
        "id": "3", "method": "session.close", "params": {"session_id": sid},
    })
    assert close_resp["result"]["closed"] is True
    assert agent_closed.wait(timeout=2.0)
    assert closed_workers == [session["session_key"]]
    assert unregistered_keys == [session["session_key"]]


def test_session_create_no_race_keeps_worker_alive(monkeypatch):
    """Regression guard: when session.close does NOT race, the build
    thread must install the worker + notify normally and leave them
    alone (no over-eager cleanup)."""
    closed_workers: list[str] = []
    unregistered_keys: list[str] = []

    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key

        def close(self):
            closed_workers.append(self.key)

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    monkeypatch.setattr(server, "_make_agent", lambda sid, key: _FakeAgent())
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(
        server,
        "_get_db",
        lambda: types.SimpleNamespace(create_session=lambda *a, **kw: None),
    )
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)

    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(
        _approval,
        "unregister_gateway_notify",
        lambda key: unregistered_keys.append(key),
    )
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    resp = server.handle_request(
        {
            "id": "1",
            "method": "session.create",
            "params": {"cols": 80},
        }
    )
    sid = resp["result"]["session_id"]

    # Wait for the build to finish (ready event inside session dict).
    session = server._sessions[sid]
    session["agent_ready"].wait(timeout=2.0)

    # Build finished without a close race — nothing should have been
    # cleaned up by the orphan check.
    assert (
        closed_workers == []
    ), f"build thread closed its own worker despite no race: {closed_workers}"
    assert (
        unregistered_keys == []
    ), f"build thread unregistered its own notify despite no race: {unregistered_keys}"

    # Session should have the live worker installed.
    assert session.get("slash_worker") is not None

    # Cleanup
    server._sessions.pop(sid, None)


def test_get_db_degrades_cleanly_when_sessiondb_init_fails(monkeypatch):
    fake_mod = types.ModuleType("superforecasting_agent.storage.session")

    class _BrokenSessionDB:
        def __init__(self):
            raise RuntimeError("locking protocol")

    fake_mod.SessionDB = _BrokenSessionDB
    monkeypatch.setitem(sys.modules, "superforecasting_agent.storage.session", fake_mod)
    monkeypatch.setattr(server._session_store, "_connection", None)
    monkeypatch.setattr(server._session_store, "last_error", None)

    assert server._get_db() is None
    assert server._session_store.last_error == "locking protocol"


def test_session_create_continues_when_state_db_is_unavailable(monkeypatch):
    class _FakeWorker:
        def __init__(self, key, model):
            self.key = key

        def close(self):
            return None

    class _FakeAgent:
        def __init__(self):
            self.model = "x"
            self.provider = "openrouter"
            self.base_url = ""
            self.api_key = ""

    emits = []

    monkeypatch.setattr(server, "_make_agent", lambda sid, key: _FakeAgent())
    monkeypatch.setattr(server, "_SlashWorker", _FakeWorker)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_session_info", lambda _a: {"model": "x"})
    monkeypatch.setattr(server, "_probe_credentials", lambda _a: None)
    monkeypatch.setattr(server, "_wire_callbacks", lambda _sid: None)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emits.append(a))

    import tools.approval as _approval

    monkeypatch.setattr(_approval, "register_gateway_notify", lambda key, cb: None)
    monkeypatch.setattr(_approval, "load_permanent_allowlist", lambda: None)

    resp = server.handle_request(
        {"id": "1", "method": "session.create", "params": {"cols": 80}}
    )
    sid = resp["result"]["session_id"]
    session = server._sessions[sid]
    session["agent_ready"].wait(timeout=2.0)

    assert session["agent_error"] is None
    assert session["agent"] is not None
    assert not any(args and args[0] == "error" for args in emits)

    server._sessions.pop(sid, None)


def test_session_list_returns_clean_error_when_state_db_is_unavailable(monkeypatch):
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server._session_store, "last_error", "locking protocol")

    resp = server.handle_request({"id": "1", "method": "session.list", "params": {}})

    assert "error" in resp
    assert "state.db unavailable: locking protocol" in resp["error"]["message"]


# --------------------------------------------------------------------------
# session.delete — TUI resume picker `d` key
# --------------------------------------------------------------------------


def test_session_delete_requires_session_id(monkeypatch):
    """Empty / missing session_id is a 4006 client error (no DB call)."""
    called: list[tuple] = []

    class _DB:
        def delete_session(self, *a, **kw):
            called.append((a, kw))
            return True

    monkeypatch.setattr(server, "_get_db", lambda: _DB())

    resp = server.handle_request({"id": "1", "method": "session.delete", "params": {}})
    assert "error" in resp
    assert resp["error"]["code"] == 4006
    assert called == []


def test_session_delete_returns_db_unavailable_when_no_db(monkeypatch):
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server._session_store, "last_error", "locked")

    resp = server.handle_request(
        {"id": "1", "method": "session.delete", "params": {"session_id": "abc"}}
    )

    assert "error" in resp
    assert resp["error"]["code"] == 5036
    assert "state.db unavailable" in resp["error"]["message"]


def test_session_delete_refuses_active_session(monkeypatch):
    """Cannot delete a session currently bound to a live TUI session."""
    called: list[str] = []

    class _DB:
        def delete_session(self, sid, sessions_dir=None):
            called.append(sid)
            return True

    monkeypatch.setattr(server, "_get_db", lambda: _DB())
    monkeypatch.setitem(server._sessions, "live", {"session_key": "key-live"})
    try:
        resp = server.handle_request(
            {
                "id": "1",
                "method": "session.delete",
                "params": {"session_id": "key-live"},
            }
        )
    finally:
        server._sessions.pop("live", None)

    assert "error" in resp
    assert resp["error"]["code"] == 4023
    assert "active forecast session" in resp["error"]["message"]
    assert called == [], "delete_session must not be called for active sessions"


def test_session_delete_fails_closed_when_active_snapshot_raises(monkeypatch):
    """Concurrent ``_sessions`` mutation from another RPC thread can raise
    ``RuntimeError: dictionary changed size during iteration``.  When the
    handler can't enumerate active sessions safely it must refuse the
    delete (fail closed) rather than fall through and allow it."""

    class _DB:
        def delete_session(self, *a, **kw):
            raise AssertionError("delete must not run when active snapshot fails")

    class _ExplodingDict(dict):
        def values(self):
            raise RuntimeError("dictionary changed size during iteration")

    monkeypatch.setattr(server, "_get_db", lambda: _DB())
    monkeypatch.setattr(server, "_sessions", _ExplodingDict())

    resp = server.handle_request(
        {"id": "1", "method": "session.delete", "params": {"session_id": "x"}}
    )

    assert "error" in resp
    assert resp["error"]["code"] == 5036
    assert "enumerate active forecast sessions" in resp["error"]["message"]


def test_session_delete_returns_4007_when_missing(monkeypatch):
    class _DB:
        def delete_session(self, sid, sessions_dir=None):
            return False

    monkeypatch.setattr(server, "_get_db", lambda: _DB())

    resp = server.handle_request(
        {"id": "1", "method": "session.delete", "params": {"session_id": "ghost"}}
    )

    assert "error" in resp
    assert resp["error"]["code"] == 4007


def test_session_delete_propagates_db_exception(monkeypatch):
    class _DB:
        def delete_session(self, sid, sessions_dir=None):
            raise RuntimeError("disk full")

    monkeypatch.setattr(server, "_get_db", lambda: _DB())

    resp = server.handle_request(
        {"id": "1", "method": "session.delete", "params": {"session_id": "x"}}
    )

    assert "error" in resp
    assert resp["error"]["code"] == 5036
    assert "disk full" in resp["error"]["message"]


def test_session_delete_success_returns_deleted_id(monkeypatch):
    """Happy path — DB delete succeeds, response carries the deleted id
    and the on-disk sessions dir is forwarded so transcript files get
    cleaned up alongside the row."""
    captured: dict = {}

    class _DB:
        def delete_session(self, sid, sessions_dir=None):
            captured["sid"] = sid
            captured["sessions_dir"] = sessions_dir
            return True

    monkeypatch.setattr(server, "_get_db", lambda: _DB())

    resp = server.handle_request(
        {"id": "1", "method": "session.delete", "params": {"session_id": "old-1"}}
    )

    assert "result" in resp, resp
    assert resp["result"] == {"deleted": "old-1"}
    assert captured["sid"] == "old-1"
    # sessions_dir must be forwarded so transcript files get cleaned up
    # too — not just the SQLite row.  The autouse _isolate_hermes_home
    # fixture pins HERMES_HOME to a temp dir; the handler should append
    # /sessions to it.
    assert captured["sessions_dir"] is not None
    assert str(captured["sessions_dir"]).endswith("sessions")


# --------------------------------------------------------------------------
# model.options — curated-list parity with `hermes model` and classic /model
# --------------------------------------------------------------------------


def test_model_options_does_not_overwrite_curated_models(monkeypatch):
    """The TUI model.options handler must surface the same curated model
    list as `hermes model` and the classic CLI /model picker.

    Regression: earlier versions of this handler unconditionally replaced
    each provider's curated ``models`` field with ``provider_model_ids()``
    (live /models catalog).  That pulled in hundreds of non-agentic models
    for providers like Nous whose /models endpoint returns image/video
    generators, rerankers, embeddings, and TTS models alongside chat models.
    """
    curated_providers = [
        {
            "slug": "nous",
            "name": "Nous",
            "models": ["moonshotai/kimi-k2.5", "anthropic/claude-opus-4.7"],
            "total_models": 30,
            "source": "built-in",
            "is_current": False,
            "is_user_defined": False,
        },
    ]

    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"providers": {}, "custom_providers": []},
    )

    with patch(
        "superforecasting_agent.runtime.model_switch.list_authenticated_providers",
        return_value=curated_providers,
    ) as listing:
        # If provider_model_ids gets called at all, the handler is still
        # overwriting curated with live — that's the regression we're
        # guarding against.
        with patch("superforecasting_agent.runtime.models.provider_model_ids") as live_fetch:
            resp = server._methods["model.options"](99, {"session_id": ""})

    assert "result" in resp, resp
    providers = resp["result"]["providers"]
    nous = next((p for p in providers if p.get("slug") == "nous"), None)
    assert nous is not None
    assert nous["models"] == [
        "moonshotai/kimi-k2.5",
        "anthropic/claude-opus-4.7",
    ]
    assert nous["total_models"] == 30
    # Handler must not consult the live catalog — curated is the truth.
    live_fetch.assert_not_called()
    # list_authenticated_providers is the single source.
    assert listing.call_count == 1


def test_model_options_propagates_list_exception(monkeypatch):
    """If list_authenticated_providers itself raises, surface as an RPC
    error rather than swallowing to a blank picker."""
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"providers": {}, "custom_providers": []},
    )
    with patch(
        "superforecasting_agent.runtime.model_switch.list_authenticated_providers",
        side_effect=RuntimeError("catalog blew up"),
    ):
        resp = server._methods["model.options"](77, {"session_id": ""})
    assert "error" in resp
    assert resp["error"]["code"] == 5033
    assert "catalog blew up" in resp["error"]["message"]


# ---------------------------------------------------------------------------
# prompt.submit — auto-title
# ---------------------------------------------------------------------------


class _ImmediateThread:
    """Runs the target callable synchronously so assertions can follow."""

    def __init__(self, target=None, daemon=None, name=None):
        self._target = target

    def start(self):
        self._target()


def test_prompt_submit_auto_titles_session_on_complete(monkeypatch):
    """maybe_auto_title is called after a successful (complete) prompt."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            return {
                "final_response": "Rome was founded in 753 BC.",
                "messages": [
                    {"role": "user", "content": "Tell me about Rome"},
                    {"role": "assistant", "content": "Rome was founded in 753 BC."},
                ],
            }

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)

    with patch("agent.title_generator.maybe_auto_title") as mock_title:
        server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "Tell me about Rome"},
            }
        )

    mock_title.assert_called_once()
    args = mock_title.call_args.args
    assert args[1] == "session-key"
    assert args[2] == "Tell me about Rome"
    assert args[3] == "Rome was founded in 753 BC."


def test_prompt_submit_skips_auto_title_when_interrupted(monkeypatch):
    """maybe_auto_title must NOT be called when the agent was interrupted."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            return {
                "final_response": "partial answer",
                "interrupted": True,
                "messages": [],
            }

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)

    with patch("agent.title_generator.maybe_auto_title") as mock_title:
        server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "Tell me about Rome"},
            }
        )

    mock_title.assert_not_called()


def test_prompt_submit_skips_auto_title_when_response_empty(monkeypatch):
    """maybe_auto_title must NOT be called when the agent returns an empty reply."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            return {
                "final_response": "",
                "messages": [],
            }

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *args, **kwargs: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)

    with patch("agent.title_generator.maybe_auto_title") as mock_title:
        server.handle_request(
            {
                "id": "1",
                "method": "prompt.submit",
                "params": {"session_id": "sid", "text": "Tell me about Rome"},
            }
        )

    mock_title.assert_not_called()


def test_prompt_submit_surfaces_backend_error_as_visible_text(monkeypatch):
    """When the backend fails with no visible response (e.g. invalid model slug
    → provider 4xx), the TUI must surface result['error'] as visible text
    instead of emitting a blank message.complete turn."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            return {
                "final_response": None,
                "messages": [],
                "api_calls": 0,
                "completed": False,
                "failed": True,
                "error": "HTTP 400: invalid model id 'kimi-k2.6'",
            }

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)

    emitted: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event, sid, payload=None: emitted.append((event, sid, payload or {})),
    )
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "hello"},
        }
    )

    complete_events = [e for e in emitted if e[0] == "message.complete"]
    assert complete_events, "expected message.complete to be emitted"
    payload = complete_events[-1][2]
    assert payload.get("status") == "error"
    assert payload.get("text", "").startswith("Error:")
    assert "kimi-k2.6" in payload.get("text", "")


def test_prompt_submit_preserves_empty_response_without_error(monkeypatch):
    """An empty final_response with NO backend error must stay empty — do not
    synthesize an error string. Preserves the existing None/empty-sentinel
    semantics owned by downstream handlers."""

    class _Agent:
        def run_conversation(
            self, prompt, conversation_history=None, stream_callback=None
        ):
            return {
                "final_response": None,
                "messages": [],
                "api_calls": 1,
                "completed": True,
            }

    server._sessions["sid"] = _session(agent=_Agent())
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)

    emitted: list[tuple[str, str, dict]] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda event, sid, payload=None: emitted.append((event, sid, payload or {})),
    )
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)

    server.handle_request(
        {
            "id": "1",
            "method": "prompt.submit",
            "params": {"session_id": "sid", "text": "hello"},
        }
    )

    complete_events = [e for e in emitted if e[0] == "message.complete"]
    assert complete_events, "expected message.complete to be emitted"
    payload = complete_events[-1][2]
    # Status stays "complete" because no error flag was set
    assert payload.get("status") == "complete"
    # Text stays empty — we did NOT fabricate an "Error:" string
    text = payload.get("text", "")
    assert text in {"", None}, f"expected empty text, got {text!r}"


# ── session.most_recent ──────────────────────────────────────────────


def test_session_most_recent_returns_first_non_denied(monkeypatch):
    """Drops `tool` rows like session.list does, returns the first hit."""

    class _DB:
        def list_sessions_rich(self, *, source=None, limit=200, offset=0, exclude_sources=None):
            return [
                {"id": "tool-1", "source": "tool", "title": "noise", "started_at": 100},
                {"id": "tui-1", "source": "tui", "title": "real", "started_at": 99},
            ]

    monkeypatch.setattr(server, "_get_db", lambda: _DB())

    resp = server.handle_request(
        {"id": "1", "method": "session.most_recent", "params": {}}
    )

    assert resp["result"]["session_id"] == "tui-1"
    assert resp["result"]["title"] == "real"
    assert resp["result"]["source"] == "tui"


def test_session_most_recent_returns_null_when_only_tool_rows(monkeypatch):
    class _DB:
        def list_sessions_rich(self, *, source=None, limit=200, offset=0, exclude_sources=None):
            return [{"id": "tool-1", "source": "tool", "started_at": 1}]

    monkeypatch.setattr(server, "_get_db", lambda: _DB())

    resp = server.handle_request(
        {"id": "1", "method": "session.most_recent", "params": {}}
    )

    assert resp["result"]["session_id"] is None


def test_session_most_recent_preserves_storage_failure(monkeypatch):
    class _BrokenDB:
        def list_sessions_rich(self, *, source=None, limit=200, offset=0, exclude_sources=None):
            raise RuntimeError("db locked")

    monkeypatch.setattr(server, "_get_db", lambda: _BrokenDB())

    resp = server.handle_request(
        {"id": "1", "method": "session.most_recent", "params": {}}
    )

    assert resp["error"]["code"] == 5006
    assert "db locked" in resp["error"]["message"]


def test_session_most_recent_handles_db_unavailable(monkeypatch):
    monkeypatch.setattr(server, "_get_db", lambda: None)

    resp = server.handle_request(
        {"id": "1", "method": "session.most_recent", "params": {}}
    )

    assert resp["error"]["code"] == 5006
    assert "state.db unavailable" in resp["error"]["message"]


# ── browser.manage ───────────────────────────────────────────────────


def _stub_urlopen(monkeypatch, *, ok: bool):
    """Patch urllib.request.urlopen used by browser.manage to short-circuit probes."""

    class _Resp:
        status = 200 if ok else 503

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _opener(_url, timeout=2.0):  # noqa: ARG001 — match urllib signature
        if not ok:
            raise OSError("probe failed")
        return _Resp()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _opener)


def _stub_urlopen_capture(monkeypatch, *, ok: bool):
    urls: list[str] = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    def _opener(url, timeout=2.0):  # noqa: ARG001 — match urllib signature
        urls.append(url)
        if not ok:
            raise OSError("probe failed")
        return _Resp()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _opener)
    return urls


def test_browser_manage_status_reads_env_var(monkeypatch):
    """Status returns the env var verbatim (no network I/O)."""
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9222")

    resp = server.handle_request(
        {"id": "1", "method": "browser.manage", "params": {"action": "status"}}
    )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == "http://127.0.0.1:9222"


def test_browser_manage_status_falls_back_to_config_cdp_url(monkeypatch):
    """When env is unset, status surfaces ``browser.cdp_url`` from
    config.yaml so users see what the next tool call will read."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)

    fake_cfg = types.SimpleNamespace(
        read_raw_config=lambda: {"browser": {"cdp_url": "http://lan:9222"}}
    )
    with patch.dict(sys.modules, {"superforecasting_agent.runtime.config": fake_cfg}):
        resp = server.handle_request(
            {"id": "1", "method": "browser.manage", "params": {"action": "status"}}
        )

    assert resp["result"] == {"connected": True, "url": "http://lan:9222"}


def test_browser_manage_status_does_not_call_get_cdp_override(monkeypatch):
    """Regression guard for Copilot's "status must not block" review:
    status must NOT route through `_get_cdp_override`, which performs a
    `/json/version` HTTP probe with a multi-second timeout."""
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9222")

    fake = types.SimpleNamespace(
        _get_cdp_override=lambda: pytest.fail(  # noqa: PT015 — fail loudly if called
            "_get_cdp_override must not run on /browser status (network I/O)"
        )
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        resp = server.handle_request(
            {"id": "1", "method": "browser.manage", "params": {"action": "status"}}
        )

    assert resp["result"]["connected"] is True


def test_browser_manage_connect_sets_env_and_cleans_twice(monkeypatch):
    """`/browser connect` must reach the live process: set env, reap browser
    sessions before AND after publishing the new URL.  The double-cleanup
    closes the supervisor swap window where ``_ensure_cdp_supervisor``
    could re-attach to the *old* CDP endpoint between steps."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    cleanup_calls: list[str] = []

    def _cleanup_all():
        cleanup_calls.append(os.environ.get("BROWSER_CDP_URL", ""))

    fake = types.SimpleNamespace(
        cleanup_all_browsers=_cleanup_all,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=True)
        resp = server.handle_request(
            {
                "id": "1",
                "method": "browser.manage",
                "params": {"action": "connect", "url": "http://127.0.0.1:9222"},
            }
        )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == "http://127.0.0.1:9222"
    assert resp["result"]["messages"] == ["Chromium-family browser is already listening on port 9222"]
    assert os.environ.get("BROWSER_CDP_URL") == "http://127.0.0.1:9222"
    # First cleanup runs against the OLD env (none here), second against the NEW.
    assert cleanup_calls == ["", "http://127.0.0.1:9222"]


def test_browser_manage_connect_defaults_to_loopback(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        urls = _stub_urlopen_capture(monkeypatch, ok=True)
        resp = server.handle_request(
            {"id": "1", "method": "browser.manage", "params": {"action": "connect"}}
        )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == "http://127.0.0.1:9222"
    assert resp["result"]["messages"] == ["Chromium-family browser is already listening on port 9222"]
    assert urls[0] == "http://127.0.0.1:9222/json/version"


def test_browser_manage_connect_default_local_reports_launch_hint(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda evt, sid, payload=None: emitted.append((evt, payload or {})),
    )
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=False)
        with (
            patch(
                "superforecasting_agent.runtime.browser_connect.try_launch_chrome_debug", return_value=False
            ),
            patch(
                "superforecasting_agent.runtime.browser_connect.get_chrome_debug_candidates",
                return_value=[],
            ),
        ):
            resp = server.handle_request(
                {
                    "id": "1",
                    "method": "browser.manage",
                    "params": {
                        "action": "connect",
                        "session_id": "sess-1",
                        "url": "http://localhost:9222",
                    },
                }
            )

    assert resp["result"]["connected"] is False
    assert resp["result"]["url"] == "http://127.0.0.1:9222"
    assert (
        resp["result"]["messages"][0]
        == "Chromium-family browser isn't running with remote debugging — attempting to launch..."
    )
    assert any(
        "No supported Chromium-family browser executable was found" in line
        or "Start a Chromium-family browser with remote debugging" in line
        for line in resp["result"]["messages"]
    )
    assert any(
        "--remote-debugging-port=9222" in line for line in resp["result"]["messages"]
    )
    assert "BROWSER_CDP_URL" not in os.environ
    progress = [p["message"] for evt, p in emitted if evt == "browser.progress"]
    assert progress == resp["result"]["messages"]


def test_browser_manage_connect_no_session_skips_progress_events(monkeypatch):
    """Without a session_id the TUI prints messages from the response;
    emitting ``browser.progress`` events would double-render. Gate the
    emit so callers without a session see the bundled list only."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    emitted: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        server,
        "_emit",
        lambda evt, sid, payload=None: emitted.append((evt, payload or {})),
    )
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=False)
        with (
            patch(
                "superforecasting_agent.runtime.browser_connect.try_launch_chrome_debug", return_value=False
            ),
            patch(
                "superforecasting_agent.runtime.browser_connect.get_chrome_debug_candidates",
                return_value=[],
            ),
        ):
            resp = server.handle_request(
                {
                    "id": "1",
                    "method": "browser.manage",
                    "params": {"action": "connect", "url": "http://localhost:9222"},
                }
            )

    assert resp["result"]["connected"] is False
    assert resp["result"]["messages"]  # bundled list still populated
    assert [evt for evt, _ in emitted if evt == "browser.progress"] == []


def test_browser_manage_connect_handles_null_url(monkeypatch):
    """Explicit ``{"url": null}`` (or empty string) must fall back to the
    default loopback URL instead of raising a TypeError that gets swallowed
    by the outer 5031 catch."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=True)
        resp = server.handle_request(
            {
                "id": "1",
                "method": "browser.manage",
                "params": {"action": "connect", "url": None},
            }
        )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == "http://127.0.0.1:9222"


def test_browser_manage_connect_rejects_non_string_url(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "browser.manage",
            "params": {"action": "connect", "url": 9222},
        }
    )

    assert resp["error"]["code"] == 4015
    assert "must be a string" in resp["error"]["message"]
    assert "BROWSER_CDP_URL" not in os.environ


def test_browser_manage_connect_default_local_retries_after_launch(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    monkeypatch.setattr(server.time, "sleep", lambda _seconds: None)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    attempts = {"n": 0}

    def _opener(_url, timeout=2.0):  # noqa: ARG001 — match urllib signature
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise OSError("not ready")
        return _Resp()

    import urllib.request

    monkeypatch.setattr(urllib.request, "urlopen", _opener)
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        with patch(
            "superforecasting_agent.runtime.browser_connect.try_launch_chrome_debug", return_value=True
        ):
            resp = server.handle_request(
                {"id": "1", "method": "browser.manage", "params": {"action": "connect"}}
            )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == "http://127.0.0.1:9222"
    assert resp["result"]["messages"] == [
        "Chromium-family browser isn't running with remote debugging — attempting to launch...",
        "Chromium-family browser launched and listening on port 9222",
    ]
    assert os.environ["BROWSER_CDP_URL"] == "http://127.0.0.1:9222"


def test_browser_manage_connect_rejects_unreachable_endpoint(monkeypatch):
    """An unreachable endpoint must NOT mutate the env or reap sessions."""
    monkeypatch.setenv("BROWSER_CDP_URL", "http://existing:9222")
    cleanup_calls: list[str] = []
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: cleanup_calls.append(
            os.environ.get("BROWSER_CDP_URL", "")
        ),
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=False)
        resp = server.handle_request(
            {
                "id": "1",
                "method": "browser.manage",
                "params": {"action": "connect", "url": "http://unreachable:9222"},
            }
        )

    assert "error" in resp
    # Env preserved; nothing reaped.
    assert os.environ["BROWSER_CDP_URL"] == "http://existing:9222"
    assert cleanup_calls == []


def test_browser_manage_connect_normalizes_bare_host_port(monkeypatch):
    """Persist a parsed `scheme://host:port` URL so `_get_cdp_override`
    can normalize it; storing a bare host:port would break subsequent
    tool calls (Copilot review on #17120)."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=True)
        resp = server.handle_request(
            {
                "id": "1",
                "method": "browser.manage",
                "params": {"action": "connect", "url": "127.0.0.1:9222"},
            }
        )

    assert resp["result"]["connected"] is True
    # Bare host:port got promoted to a full URL with explicit scheme.
    assert resp["result"]["url"].startswith("http://")
    assert os.environ["BROWSER_CDP_URL"].startswith("http://")


def test_browser_manage_connect_strips_discovery_path(monkeypatch):
    """User-supplied discovery paths like `/json` or `/json/version`
    must collapse to bare `scheme://host:port`; otherwise
    ``_resolve_cdp_override`` will append ``/json/version`` again and
    produce a duplicate path (Copilot review round-2 on #17120)."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        _stub_urlopen(monkeypatch, ok=True)
        resp = server.handle_request(
            {
                "id": "1",
                "method": "browser.manage",
                "params": {"action": "connect", "url": "http://127.0.0.1:9222/json"},
            }
        )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == "http://127.0.0.1:9222"
    assert os.environ["BROWSER_CDP_URL"] == "http://127.0.0.1:9222"


def test_browser_manage_connect_preserves_devtools_browser_endpoint(monkeypatch):
    """Concrete devtools websocket endpoints (e.g. Browserbase) must
    survive verbatim — we only collapse discovery-style paths."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    concrete = "ws://browserbase.example/devtools/browser/abc123"

    class _OkSocket:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        # If urlopen is reached for a concrete ws endpoint, the test
        # would still pass because _stub_urlopen returned ok=True before;
        # patch it to assert-fail so we prove the HTTP probe is skipped.
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("urlopen called")
        ):
            with patch("socket.create_connection", return_value=_OkSocket()):
                resp = server.handle_request(
                    {
                        "id": "1",
                        "method": "browser.manage",
                        "params": {"action": "connect", "url": concrete},
                    }
                )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == concrete
    assert os.environ["BROWSER_CDP_URL"] == concrete


def test_browser_manage_connect_local_devtools_ws_preserves_path(monkeypatch):
    """Regression: ``ws://127.0.0.1:9222/devtools/browser/<id>`` is a real
    connectable endpoint; default-local normalization must not strip the
    ``/devtools/browser/...`` path or it breaks valid local CDP connects."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    concrete = "ws://127.0.0.1:9222/devtools/browser/abc123"

    class _OkSocket:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        with patch("socket.create_connection", return_value=_OkSocket()):
            resp = server.handle_request(
                {
                    "id": "1",
                    "method": "browser.manage",
                    "params": {"action": "connect", "url": concrete},
                }
            )

    assert resp["result"]["connected"] is True
    assert resp["result"]["url"] == concrete
    assert os.environ["BROWSER_CDP_URL"] == concrete


def test_browser_manage_connect_rejects_invalid_port(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "browser.manage",
            "params": {"action": "connect", "url": "http://localhost:abc"},
        }
    )

    assert resp["error"]["code"] == 4015
    assert "invalid port" in resp["error"]["message"]
    assert "BROWSER_CDP_URL" not in os.environ


def test_browser_manage_connect_rejects_missing_host(monkeypatch):
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "browser.manage",
            "params": {"action": "connect", "url": "http://:9222"},
        }
    )

    assert resp["error"]["code"] == 4015
    assert "missing host" in resp["error"]["message"]
    assert "BROWSER_CDP_URL" not in os.environ


def test_browser_manage_connect_concrete_ws_skips_http_probe(monkeypatch):
    """Regression for round-2 Copilot review: a hosted CDP endpoint
    (no HTTP discovery) must connect via TCP-only reachability check.
    The HTTP probe used to reject these even though they're valid."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    concrete = "wss://chrome.browserless.io/devtools/browser/sess-1"

    seen_targets: list[tuple[str, int]] = []

    class _OkSocket:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def _fake_create_connection(addr, timeout=None):
        seen_targets.append(addr)
        return _OkSocket()

    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        # urlopen would 404/ECONNREFUSED on a real hosted CDP endpoint;
        # asserting it's never called proves the probe was skipped.
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("urlopen called")
        ):
            with patch("socket.create_connection", side_effect=_fake_create_connection):
                resp = server.handle_request(
                    {
                        "id": "1",
                        "method": "browser.manage",
                        "params": {"action": "connect", "url": concrete},
                    }
                )

    assert resp["result"] == {"connected": True, "url": concrete}
    # wss → port 443, host preserved verbatim.
    assert seen_targets == [("chrome.browserless.io", 443)]


def test_browser_manage_connect_concrete_ws_tcp_unreachable(monkeypatch):
    """If the TCP reachability check fails for a concrete ws endpoint,
    return a clear 5031 error — no fallback to the HTTP probe (which
    can never succeed for these URLs anyway)."""
    monkeypatch.delenv("BROWSER_CDP_URL", raising=False)
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: None,
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    concrete = "ws://offline.example/devtools/browser/missing"

    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        with patch("socket.create_connection", side_effect=OSError("ECONNREFUSED")):
            resp = server.handle_request(
                {
                    "id": "1",
                    "method": "browser.manage",
                    "params": {"action": "connect", "url": concrete},
                }
            )

    assert "error" in resp
    assert resp["error"]["code"] == 5031


def test_browser_manage_disconnect_drops_env_and_cleans(monkeypatch):
    monkeypatch.setenv("BROWSER_CDP_URL", "http://127.0.0.1:9222")
    cleanup_count = {"n": 0}
    fake = types.SimpleNamespace(
        cleanup_all_browsers=lambda: cleanup_count.__setitem__(
            "n", cleanup_count["n"] + 1
        ),
        _get_cdp_override=lambda: os.environ.get("BROWSER_CDP_URL", ""),
    )
    with patch.dict(sys.modules, {"tools.browser_tool": fake}):
        resp = server.handle_request(
            {"id": "1", "method": "browser.manage", "params": {"action": "disconnect"}}
        )

    assert resp["result"] == {"connected": False}
    assert "BROWSER_CDP_URL" not in os.environ
    # Two cleanups: once before env removal, once after, matching connect.
    assert cleanup_count["n"] == 2


# ── config.get indicator normalization ───────────────────────────────


def test_config_get_indicator_returns_known_value_verbatim(monkeypatch):
    monkeypatch.setattr(
        server, "_load_cfg", lambda: {"display": {"tui_status_indicator": "emoji"}}
    )
    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "indicator"}}
    )
    assert resp["result"] == {"value": "emoji"}


def test_config_get_indicator_normalizes_casing_and_whitespace(monkeypatch):
    """Hand-edited config.yaml stays consistent with what the TUI shows.

    Frontend's `normalizeIndicatorStyle` lowercases + trims, so config.get
    must do the same — otherwise `/indicator` prints 'EMOJI ' while the
    UI is actually rendering the unicode default."""
    monkeypatch.setattr(
        server, "_load_cfg", lambda: {"display": {"tui_status_indicator": " EMOJI "}}
    )
    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "indicator"}}
    )
    assert resp["result"] == {"value": "emoji"}


def test_config_get_indicator_maps_legacy_kaomoji_to_markers(monkeypatch):
    monkeypatch.setattr(
        server, "_load_cfg", lambda: {"display": {"tui_status_indicator": "kaomoji"}}
    )
    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "indicator"}}
    )
    assert resp["result"] == {"value": "markers"}


def test_config_get_indicator_falls_back_to_default_for_unknown(monkeypatch):
    """An unknown value in config.yaml falls back to the same default
    the frontend uses (`_INDICATOR_DEFAULT`)."""
    monkeypatch.setattr(
        server, "_load_cfg", lambda: {"display": {"tui_status_indicator": "rainbow"}}
    )
    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "indicator"}}
    )
    assert resp["result"] == {"value": "unicode"}


def test_config_get_indicator_falls_back_when_unset(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"display": {}})
    resp = server.handle_request(
        {"id": "1", "method": "config.get", "params": {"key": "indicator"}}
    )
    assert resp["result"] == {"value": "unicode"}


# ── config.set indicator validation ──────────────────────────────────


def test_config_set_indicator_accepts_known_value(monkeypatch):
    written: dict = {}
    monkeypatch.setattr(
        server,
        "_write_config_key",
        lambda k, v: written.update({k: v}),
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "indicator", "value": "EMOJI"},
        }
    )
    assert resp["result"] == {"key": "indicator", "value": "emoji"}
    assert written == {"display.tui_status_indicator": "emoji"}


def test_config_set_indicator_accepts_legacy_kaomoji_alias(monkeypatch):
    written: dict = {}
    monkeypatch.setattr(
        server,
        "_write_config_key",
        lambda k, v: written.update({k: v}),
    )
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "indicator", "value": "kaomoji"},
        }
    )
    assert resp["result"] == {"key": "indicator", "value": "markers"}
    assert written == {"display.tui_status_indicator": "markers"}


def test_config_set_indicator_falsy_non_string_surfaces_in_error(monkeypatch):
    """`0` / `False` / `[]` are not valid styles, but the error message
    must still tell the user what they sent — `value or ""` would have
    erased them to a blank string."""
    monkeypatch.setattr(server, "_write_config_key", lambda *a, **k: None)

    for bad in (0, False, []):
        resp = server.handle_request(
            {
                "id": "1",
                "method": "config.set",
                "params": {"key": "indicator", "value": bad},
            }
        )
        assert "error" in resp
        msg = resp["error"]["message"]
        assert "unknown indicator" in msg
        # The exact repr varies; `0`/`False` stringify with content,
        # `[]` becomes an empty list — what matters is the diagnostic
        # is no longer just `unknown indicator: ` with nothing after.
        assert msg.split("; ")[0] != "unknown indicator: ''"


def test_config_set_indicator_none_keeps_blank_repr(monkeypatch):
    """`None` is the genuine 'no value' case — empty raw is acceptable."""
    monkeypatch.setattr(server, "_write_config_key", lambda *a, **k: None)
    resp = server.handle_request(
        {
            "id": "1",
            "method": "config.set",
            "params": {"key": "indicator", "value": None},
        }
    )
    assert "error" in resp
    assert "unknown indicator: ''" in resp["error"]["message"]


# ── reload.env ───────────────────────────────────────────────────────


def test_reload_env_rpc_calls_hermes_cli_reload_env(monkeypatch):
    """reload.env mirrors classic CLI's `/reload` — re-reads ~/.hermes/.env
    into the gateway process and reports the count of vars updated."""
    calls = {"n": 0}

    def _fake_reload():
        calls["n"] += 1
        return 7

    fake = types.SimpleNamespace(reload_env=_fake_reload)
    with patch.dict(sys.modules, {"superforecasting_agent.runtime.config": fake}):
        resp = server.handle_request({"id": "1", "method": "reload.env", "params": {}})

    assert resp["result"] == {"updated": 7}
    assert calls["n"] == 1


def test_reload_env_rpc_surfaces_errors(monkeypatch):
    def _broken():
        raise RuntimeError("env path locked")

    fake = types.SimpleNamespace(reload_env=_broken)
    with patch.dict(sys.modules, {"superforecasting_agent.runtime.config": fake}):
        resp = server.handle_request({"id": "1", "method": "reload.env", "params": {}})

    assert "error" in resp
    assert "env path locked" in resp["error"]["message"]


# ── max_iterations config reading ─────────────────────────────────────


def _setup_make_agent_mocks(monkeypatch, cfg):
    monkeypatch.setattr(server, "_load_cfg", lambda: cfg)
    monkeypatch.setattr(
        server, "_resolve_startup_runtime", lambda: ("test-model", None)
    )
    monkeypatch.setattr(
        "superforecasting_agent.runtime.runtime_provider.resolve_runtime_provider",
        # build_agent() now resolves via this entry point and passes the credential-
        # context kwargs (explicit_api_key/base_url) too — accept **kwargs.
        lambda requested=None, target_model=None, **_kwargs: {
            "provider": None,
            "base_url": None,
            "api_key": None,
            "api_mode": None,
            "command": None,
            "args": None,
            "credential_pool": None,
        },
    )
    monkeypatch.setattr(server, "_load_tool_progress_mode", lambda: "off")
    monkeypatch.setattr(server, "_load_reasoning_config", lambda: None)
    monkeypatch.setattr(server, "_load_service_tier", lambda: None)
    monkeypatch.setattr(server, "_load_enabled_toolsets", lambda: None)
    monkeypatch.setattr(server, "_get_db", lambda: None)
    monkeypatch.setattr(server, "_agent_cbs", lambda sid: {})


def test_make_agent_reads_nested_max_turns(monkeypatch):
    _setup_make_agent_mocks(monkeypatch, {"agent": {"max_turns": 200}})

    with patch("run_agent.AIAgent") as mock_agent:
        server._make_agent("sid1", "key1")

    assert mock_agent.call_args.kwargs["max_iterations"] == 200


def test_make_agent_nested_max_turns_takes_priority(monkeypatch):
    _setup_make_agent_mocks(
        monkeypatch, {"agent": {"max_turns": 500}, "max_turns": 100}
    )

    with patch("run_agent.AIAgent") as mock_agent:
        server._make_agent("sid1", "key1")

    assert mock_agent.call_args.kwargs["max_iterations"] == 500


def test_make_agent_defaults_to_90(monkeypatch):
    _setup_make_agent_mocks(monkeypatch, {})

    with patch("run_agent.AIAgent") as mock_agent:
        server._make_agent("sid1", "key1")

    assert mock_agent.call_args.kwargs["max_iterations"] == 90


def test_make_agent_handles_null_agent_config(monkeypatch):
    _setup_make_agent_mocks(monkeypatch, {"agent": None, "max_turns": 80})

    with patch("run_agent.AIAgent") as mock_agent:
        server._make_agent("sid1", "key1")

    assert mock_agent.call_args.kwargs["max_iterations"] == 80


class _FakeAgentForBackground:
    base_url = None
    api_key = None
    provider = None
    api_mode = None
    acp_command = None
    acp_args = None
    model = "test-model"
    enabled_toolsets = None
    ephemeral_system_prompt = None
    providers_allowed = None
    providers_ignored = None
    providers_order = None
    provider_sort = None
    provider_require_parameters = False
    provider_data_collection = None
    reasoning_config = None
    service_tier = None
    request_overrides = {}
    _fallback_model = None


def test_background_agent_kwargs_reads_nested_max_turns(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"agent": {"max_turns": 300}})

    kwargs = server._background_agent_kwargs(_FakeAgentForBackground(), "task_1")

    assert kwargs["max_iterations"] == 300


def test_background_agent_kwargs_falls_back_to_root_max_turns(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"max_turns": 50})

    kwargs = server._background_agent_kwargs(_FakeAgentForBackground(), "task_1")

    assert kwargs["max_iterations"] == 50


def test_background_agent_kwargs_defaults_to_25(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {})

    kwargs = server._background_agent_kwargs(_FakeAgentForBackground(), "task_1")

    assert kwargs["max_iterations"] == 25


def test_background_agent_kwargs_handles_null_agent_config(monkeypatch):
    monkeypatch.setattr(server, "_load_cfg", lambda: {"agent": None, "max_turns": 40})

    kwargs = server._background_agent_kwargs(_FakeAgentForBackground(), "task_1")

    assert kwargs["max_iterations"] == 40


def test_config_show_displays_nested_max_turns(monkeypatch):
    monkeypatch.setattr(
        server,
        "_load_cfg",
        lambda: {"agent": {"max_turns": 120}, "enabled_toolsets": [], "verbose": False},
    )
    monkeypatch.setattr(server, "_resolve_model", lambda: "test-model")

    resp = server.handle_request({"id": "1", "method": "config.show", "params": {}})
    sections = resp["result"]["sections"]
    agent_rows = next(
        section["rows"] for section in sections if section["title"] == "Agent"
    )

    assert ["Max Turns", "120"] in agent_rows


def test_notification_poller_delivers_completion(monkeypatch):
    """Poller picks up completion events and triggers agent turns."""
    from tools.process_registry import process_registry

    turns = []
    emitted = []

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, stream_callback=None):
            turns.append(prompt)
            return {
                "final_response": "ok",
                "messages": [{"role": "assistant", "content": "ok"}],
            }

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target
        def start(self):
            self._target()

    sess = _session(agent=_Agent())
    server._sessions["sid_poll"] = sess
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emitted.append(a))
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    # Clear queue
    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()
    process_registry._completion_consumed.discard("proc_poller_test")

    stop = threading.Event()

    # Put event on queue, then immediately signal stop so the poller
    # runs exactly one iteration.
    process_registry.completion_queue.put({
        "type": "completion",
        "session_id": "proc_poller_test",
        "command": "echo hello",
        "exit_code": 0,
        "output": "hello",
    })
    stop.set()

    try:
        server._notification_poller_loop(stop, "sid_poll", sess)

        # Should have emitted a status.update with kind=process
        status_calls = [a for a in emitted if a[0] == "status.update"]
        assert len(status_calls) >= 1
        assert status_calls[0][2]["kind"] == "process"

        # Should have triggered an agent turn
        assert len(turns) == 1
        assert "[IMPORTANT: Background process proc_poller_test completed" in turns[0]
    finally:
        server._sessions.pop("sid_poll", None)
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()


def test_notification_poller_skips_consumed(monkeypatch):
    """Already-consumed completions are not dispatched by the poller."""
    from tools.process_registry import process_registry

    turns = []

    class _Agent:
        def run_conversation(self, prompt, conversation_history=None, stream_callback=None):
            turns.append(prompt)
            return {"final_response": "ok", "messages": []}

    class _ImmediateThread:
        def __init__(self, target=None, daemon=None, name=None):
            self._target = target
        def start(self):
            self._target()

    sess = _session(agent=_Agent())
    server._sessions["sid_skip"] = sess
    monkeypatch.setattr(server.threading, "Thread", _ImmediateThread)
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: None)
    monkeypatch.setattr(server, "make_stream_renderer", lambda cols: None)
    monkeypatch.setattr(server, "render_message", lambda raw, cols: None)

    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()

    process_registry._completion_consumed.add("proc_already_done")
    process_registry.completion_queue.put({
        "type": "completion",
        "session_id": "proc_already_done",
        "command": "echo x",
        "exit_code": 0,
        "output": "x",
    })

    stop = threading.Event()
    stop.set()

    try:
        server._notification_poller_loop(stop, "sid_skip", sess)
        assert len(turns) == 0
    finally:
        server._sessions.pop("sid_skip", None)
        process_registry._completion_consumed.discard("proc_already_done")
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()


def test_notification_poller_requeues_when_busy(monkeypatch):
    """When the agent is busy, the poller requeues the event."""
    from tools.process_registry import process_registry

    emitted = []

    sess = _session(running=True)  # agent is busy
    server._sessions["sid_busy"] = sess
    monkeypatch.setattr(server, "_emit", lambda *a, **kw: emitted.append(a))

    while not process_registry.completion_queue.empty():
        process_registry.completion_queue.get_nowait()
    process_registry._completion_consumed.discard("proc_busy_test")

    evt = {
        "type": "completion",
        "session_id": "proc_busy_test",
        "command": "make build",
        "exit_code": 0,
        "output": "ok",
    }
    process_registry.completion_queue.put(evt)

    stop = threading.Event()
    stop.set()

    try:
        server._notification_poller_loop(stop, "sid_busy", sess)

        # Status update was emitted (user sees it)
        status_calls = [a for a in emitted if a[0] == "status.update"]
        assert len(status_calls) == 1

        # Event was requeued (agent was busy, no turn triggered)
        assert not process_registry.completion_queue.empty()
        requeued = process_registry.completion_queue.get_nowait()
        assert requeued["session_id"] == "proc_busy_test"
    finally:
        server._sessions.pop("sid_busy", None)
        while not process_registry.completion_queue.empty():
            process_registry.completion_queue.get_nowait()


# ── runtime RPC registration (register_method) ────────────────────────


def test_register_method_populates_dispatch_and_is_callable():
    name = "test.runtime.registered"

    def handler(rid, params):
        return {"jsonrpc": "2.0", "id": rid, "result": {"echo": params.get("x")}}

    try:
        assert name not in server._methods
        ret = server.register_method(name, handler)

        # Returns fn (usable as a decorator) and populates the same dict the
        # @method decorator writes to.
        assert ret is handler
        assert server._methods[name] is handler

        # Dispatches through the normal request path.
        resp = server.handle_request(
            {"jsonrpc": "2.0", "id": 7, "method": name, "params": {"x": 42}}
        )
        assert resp == {"jsonrpc": "2.0", "id": 7, "result": {"echo": 42}}
    finally:
        server._methods.pop(name, None)


def test_method_decorator_routes_through_register_method():
    name = "test.runtime.decorated"

    try:
        @server.method(name)
        def handler(rid, params):
            return {"jsonrpc": "2.0", "id": rid, "result": "ok"}

        # Decorator returns the original fn (byte-identical behavior) and
        # registers into the shared dict.
        assert handler.__name__ == "handler"
        assert server._methods[name] is handler
    finally:
        server._methods.pop(name, None)


def test_register_method_rejects_bad_args():
    import pytest

    def handler(rid, params):
        return None

    with pytest.raises(ValueError):
        server.register_method("", handler)
    with pytest.raises(TypeError):
        server.register_method("test.runtime.notcallable", object())


# ── T3 data surfaces: triage contested + relabel, schedule status ────────────


def _seed_contested_label(ledger, question_id):
    """Record one auto-labeled triage row + open its contested alert, mirroring the
    contested-routing loop. Returns (label_id, alert_id)."""
    from forecasting.ledger import allow_ledger_writes

    with allow_ledger_writes(reason="test_seed"):
        rows = ledger.record_triage_labels(
            question_id=question_id,
            verdicts=[
                {
                    "title": "a candidate reading",
                    "auto_label": "irrelevant",
                    "relevance": 0.5,
                    "rationale": "labeler near the decision boundary",
                    "materiality": "high",
                }
            ],
        )
        label_id = rows[0]["id"]
        alert = ledger.create_alert(
            severity="warning",
            scope_type="question",
            scope_ref=question_id,
            reason=f"contested_label:{label_id}",
            recommended_action="hand-label this triage item",
        )
        ledger.update_triage_label(label_id, contested=True, alert_id=alert.id)
    return label_id, alert.id


def test_forecast_triage_contested_and_relabel(tmp_path, monkeypatch):
    """forecast.triage.contested lists the open contested staging rows (question ref
    + rationale + linked alert); forecast.triage.relabel records the expert label,
    acks the alert, and drops the row from the contested list."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger, allow_ledger_writes

    ledger = ForecastLedger()
    with allow_ledger_writes(reason="test_seed"):
        question = ledger.create_question(
            title="Will CPI YoY exceed 3.0% in 2027?",
            resolution_criteria="Resolved by the official BLS CPI-U release for 2027.",
        )
    label_id, alert_id = _seed_contested_label(ledger, question.id)

    listed = server.handle_request(
        {"id": "1", "method": "forecast.triage.contested", "params": {}}
    )
    assert "result" in listed, listed
    res = listed["result"]
    assert res["count"] == 1, res
    row = res["contested"][0]
    assert row["id"] == label_id
    assert row["question_id"] == question.id
    assert row["auto_label"] == "irrelevant"
    assert row["alert_id"] == alert_id
    assert "boundary" in row["rationale"]

    relabel = server.handle_request(
        {
            "id": "2",
            "method": "forecast.triage.relabel",
            "params": {"label_id": label_id, "label": "relevant_interesting"},
        }
    )
    assert "result" in relabel, relabel
    assert relabel["result"].get("success") is True, relabel

    # The expert label is recorded and the linked alert acknowledged (real work).
    updated = ledger.get_triage_label(label_id)
    assert updated["expert_label"] == "relevant_interesting"
    assert updated["label_source"] == "expert"
    assert bool(updated["contested"]) is False
    assert ledger.get_alert(alert_id).acknowledged_at is not None

    # And it no longer appears in the contested list.
    after = server.handle_request(
        {"id": "3", "method": "forecast.triage.contested", "params": {}}
    )
    assert after["result"]["count"] == 0, after["result"]


def test_forecast_triage_relabel_requires_label(tmp_path, monkeypatch):
    """A relabel with neither adjudications nor label_id+label is a param error."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    resp = server.handle_request(
        {"id": "1", "method": "forecast.triage.relabel", "params": {"label_id": "tl_x"}}
    )
    assert "error" in resp, resp
    assert resp["error"]["code"] == 4003


def test_forecast_schedule_status(tmp_path, monkeypatch):
    """forecast.schedule.status returns cron health (defensive default when no jobs
    installed) joined with the enabled per-question scheduled reviews."""
    monkeypatch.setenv("HERMES_HOME", str(tmp_path / "home"))
    from forecasting.ledger import ForecastLedger, allow_ledger_writes

    ledger = ForecastLedger()
    with allow_ledger_writes(reason="test_seed"):
        question = ledger.create_question(
            title="Will CPI YoY exceed 3.0% in 2027?",
            resolution_criteria="Resolved by the official BLS CPI-U release for 2027.",
        )
        ledger.schedule_review(
            scope_type="question",
            scope_ref=question.id,
            cadence="weekly",
            next_run_at="2027-01-01T00:00:00Z",
            trigger_reason="scheduled",
        )

    resp = server.handle_request(
        {"id": "1", "method": "forecast.schedule.status", "params": {}}
    )
    assert "result" in resp, resp
    res = resp["result"]
    assert "cron" in res and "jobs" in res["cron"]
    assert res["healthy"] is True  # no errored/missed jobs
    assert res["scheduled_review_count"] >= 1
    refs = {r["scope_ref"] for r in res["scheduled_reviews"]}
    assert question.id in refs


# ── _get_usage wire semantics: CUMULATIVE input/output ────────────────────────
# The TUI liveness counter shows per-turn work as workTokens = (usage.input +
# usage.output) − a baseline captured at turn start. That delta is only honest
# if the input/output the gateway ships are the session CUMULATIVE totals (the
# running SUM of every call's fresh, cache-excluded work) — the same way
# usage.total accumulates. If they ever regressed to PER-CALL / last-message
# values, the delta would collapse to roughly the final call's fresh input
# (tiny once the prompt is cached) + its output — the ~25-50 undercount the
# operator hit. These tests pin the cumulative contract server-side so a future
# refactor of _get_usage (or the counters it reads) can't silently break it.


def _usage_agent(**counters) -> types.SimpleNamespace:
    """A minimal agent carrying just the session_* counters _get_usage reads.

    context_compressor=None skips the context block; estimate_usage_cost is
    already wrapped in try/except inside _get_usage, so no pricing table or
    network is needed here.
    """
    defaults = dict(
        model="anthropic/claude-opus-4",
        provider="anthropic",
        base_url=None,
        session_input_tokens=0,
        session_output_tokens=0,
        session_cache_read_tokens=0,
        session_cache_write_tokens=0,
        session_reasoning_tokens=0,
        session_prompt_tokens=0,
        session_completion_tokens=0,
        session_total_tokens=0,
        session_api_calls=0,
        context_compressor=None,
    )
    defaults.update(counters)
    return types.SimpleNamespace(**defaults)


def test_get_usage_ships_cumulative_input_output_not_last_call():
    """A simulated 10-call turn: _get_usage must surface the SUM of every call's
    fresh input+output, never just the last (cached, tiny) call."""
    agent = _usage_agent()
    # Realistic per-call fresh (cache-excluded) work: the first call pays full
    # input, later calls are mostly cache reads so their fresh input is small;
    # output varies per call. agent/conversation_loop folds each with += — we
    # mirror that accumulation here.
    per_call = [
        (12_000, 800),
        (900, 650),
        (1_100, 720),
        (850, 610),
        (1_300, 900),
        (700, 540),
        (1_500, 1_100),
        (600, 480),
        (1_000, 700),
        (400, 300),
    ]
    for fresh_in, out in per_call:
        agent.session_input_tokens += fresh_in
        agent.session_output_tokens += out
        agent.session_total_tokens += fresh_in + out
        agent.session_api_calls += 1

    usage = server._get_usage(agent)

    expected_in = sum(i for i, _ in per_call)  # 20_350
    expected_out = sum(o for _, o in per_call)  # 6_800
    assert usage["input"] == expected_in
    assert usage["output"] == expected_out
    assert usage["calls"] == len(per_call)

    # The honest per-turn work is the SUM (27,150), which the counter deltas to.
    work = usage["input"] + usage["output"]
    assert work == expected_in + expected_out == 27_150

    # Guard the exact regression: had _get_usage shipped only the LAST call, the
    # workTokens delta would collapse to a fraction of the real turn.
    last_in, last_out = per_call[-1]
    assert work > (last_in + last_out) * 10  # 27,150 vs 700


def test_get_usage_real_session_arithmetic_25e6cd08():
    """Operator's real session 25e6cd08 (53 calls): cumulative fresh input
    280,612 + output 32,315 = 312,927 honest work; the 4,760,671 total was 93%
    cache_read re-sends. _get_usage must ship the cumulative split (not the last
    call) so the counter reads 312.9k of work, not a cache-inflated 4.8M."""
    cache_read = 4_447_744
    agent = _usage_agent(
        session_input_tokens=280_612,
        session_output_tokens=32_315,
        session_cache_read_tokens=cache_read,
        session_prompt_tokens=280_612 + cache_read,  # provider "prompt" incl. cache
        session_completion_tokens=32_315,
        session_total_tokens=280_612 + cache_read + 32_315,  # 4,760,671
        session_api_calls=53,
    )

    usage = server._get_usage(agent)

    assert usage["input"] == 280_612
    assert usage["output"] == 32_315
    assert usage["calls"] == 53
    work = usage["input"] + usage["output"]
    assert work == 312_927
    # Honest work is ~15x smaller than the cache-inflated billing total.
    assert usage["total"] == 4_760_671
    assert round(usage["total"] / work, 1) == 15.2


def test_on_tool_complete_ships_cumulative_usage_climbing_across_a_two_call_turn():
    """tool.complete carries the CUMULATIVE session usage as of emit time, so a
    two-call turn shows the counter climb tool-by-tool. Ordering that makes this
    honest: conversation_loop folds each API call's usage into the session
    counters at RESPONSE time, and _execute_tool_calls fires the complete
    callback AFTERWARD — so _get_usage(agent) already includes the call that
    produced this very tool call (never a stale pre-fold number)."""
    sid = "sess-tool-usage"
    agent = _usage_agent()
    server._sessions[sid] = {"agent": agent}

    emitted: list[tuple[str, str, dict]] = []
    try:
        with patch.object(server, "_emit", side_effect=lambda *a, **k: emitted.append(a)):
            # ── API call #1 returns tool_calls → conversation_loop folds its
            #    usage BEFORE the tools run → then the tool completes.
            agent.session_input_tokens += 12_000
            agent.session_output_tokens += 800
            agent.session_total_tokens += 12_800
            agent.session_api_calls += 1
            server._on_tool_complete(sid, "tc_1", "web_search", {}, "found 5 results")

            # ── API call #2 (with the tool result) folds MORE usage, then its
            #    tool completes. The counter must be strictly larger now.
            agent.session_input_tokens += 900
            agent.session_output_tokens += 650
            agent.session_total_tokens += 1_550
            agent.session_api_calls += 1
            server._on_tool_complete(sid, "tc_2", "read", {}, "file contents")
    finally:
        server._sessions.pop(sid, None)

    completes = [(sid_, payload) for (event, sid_, payload) in emitted if event == "tool.complete"]
    assert len(completes) == 2

    usage_1 = completes[0][1]["usage"]
    usage_2 = completes[1][1]["usage"]

    # Each frame is CUMULATIVE (not per-call): call #1 sees only its own work,
    # call #2 sees the sum of both calls.
    work_1 = usage_1["input"] + usage_1["output"]
    work_2 = usage_2["input"] + usage_2["output"]
    assert work_1 == 12_800
    assert work_2 == 12_800 + 1_550
    # Monotonic climb — the whole point: the liveness counter grows mid-turn.
    assert work_2 > work_1
    assert usage_2["calls"] == 2
