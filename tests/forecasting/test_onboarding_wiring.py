"""PR5: run/re-run paths read metadata.onboarding (toggles + per-source priors)."""

from __future__ import annotations

import json

from forecasting.ledger import ForecastLedger
from forecasting.protocol import build_context_packet
from forecasting.question_spec import onboarding_settings
from tools.forecasting_tool import forecast_ledger_tool


def _ledger(tmp_path):
    led = ForecastLedger(db_path=str(tmp_path / "w.db"))
    led.initialize_schema()
    return led


def test_onboarding_settings_defaults_and_override():
    assert onboarding_settings(None) == {"allow_evidence_gathering": True, "panel_by_default": False, "autonomy": "ask"}
    got = onboarding_settings({"onboarding": {"allow_evidence_gathering": False, "panel_by_default": True, "autonomy": "full"}})
    assert got == {"allow_evidence_gathering": False, "panel_by_default": True, "autonomy": "full"}


def test_context_packet_surfaces_onboarding_preferences(tmp_path):
    led = _ledger(tmp_path)
    q = led.create_question(
        title="CPI print exceeds 3pct in June 2026",
        resolution_criteria="Resolves yes if BLS June 2026 CPI YoY exceeds 3.0 percent.",
        metadata={"onboarding": {"allow_evidence_gathering": False, "panel_by_default": True, "autonomy": "full"}},
    )
    packet = build_context_packet(led, led.get_question(q.id), None)
    assert "## Onboarding Preferences" in packet
    assert "MANUAL ONLY" in packet
    assert "panel_by_default: True" in packet
    assert "autonomy: full" in packet


def test_import_inherits_watched_source_reliability_prior(tmp_path):
    db = str(tmp_path / "imp.db")
    qid = json.loads(forecast_ledger_tool({
        "action": "create_question", "db": db, "title": "Gas prices rise by close",
        "resolution_criteria": "Resolves yes if retail gasoline rises above 4.00 USD by close.",
    }))["question"]["id"]
    feed = tmp_path / "feed.xml"
    feed.write_text(
        '<?xml version="1.0"?><rss><channel>'
        '<item><guid>g1</guid><title>Gasoline prices rise sharply</title>'
        '<link>https://example.test/g1</link><pubDate>Sat, 02 May 2026 00:00:00 GMT</pubDate></item>'
        '</channel></rss>',
        encoding="utf-8",
    )
    # Watch the source with a reliability prior of 0.3.
    forecast_ledger_tool({
        "action": "add_watched_source", "db": db, "scope_type": "question", "scope_ref": qid,
        "source": str(feed), "source_type": "rss", "metadata": {"reliability_prior": 0.3},
    })
    imported = json.loads(forecast_ledger_tool({
        "action": "import_source_evidence", "db": db, "question_id": qid,
        "source_type": "rss", "source": str(feed), "keywords": ["gasoline"],
    }))
    assert imported["success"] is True
    assert imported["imported_count"] >= 1
    # imported evidence inherited the source's reliability prior
    assert imported["imported"][0]["evidence"]["reliability_rating"] == 0.3
