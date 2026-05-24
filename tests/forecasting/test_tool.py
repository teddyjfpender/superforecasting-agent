from __future__ import annotations

import json
from pathlib import Path

import pytest

from forecasting import ForecastLedger
from forecasting.source_adapters import (
    BlueskyPost,
    CensusRecord,
    CkanDataset,
    CisaKevVulnerability,
    ClinicalTrialStudy,
    CoinGeckoMarketSnapshot,
    CrossrefWork,
    EiaObservation,
    FemaDisasterDeclaration,
    FiveThirtyEightPollObservation,
    HackerNewsItem,
    GitHubCommit,
    GitHubIssue,
    GitHubWorkflowRun,
    MastodonStatus,
    NasaEonetEvent,
    NpmPackageVersion,
    NwsAlert,
    OpenFdaDrugApplication,
    OpenMeteoAirQualityForecast,
    OpenMeteoHistoricalWeatherObservation,
    RedditPost,
    ReliefWebReport,
    PubMedArticle,
    PypiRelease,
    SecCompanyFact,
    SocrataRecord,
    StooqPriceObservation,
    TreasuryRecord,
    UsgsEarthquakeEvent,
    WikimediaPageviewObservation,
    WhoGhoObservation,
    YahooFinancePriceObservation,
)
from hermes_cli.tools_config import _get_platform_tools
from model_tools import get_tool_definitions
from tools.forecasting_tool import FORECAST_LEDGER_SCHEMA, forecast_ledger_tool
from tools.registry import discover_builtin_tools, registry
from toolsets import get_toolset, resolve_toolset, validate_toolset


def test_forecasting_toolset_is_discoverable():
    discover_builtin_tools()

    assert registry.get_entry("forecast_ledger") is not None
    assert "forecast_ledger" in resolve_toolset("forecasting")


def test_cli_default_toolsets_are_forecast_desk_scoped():
    enabled = _get_platform_tools({}, "cli", include_default_mcp_servers=False)

    assert "forecasting" in enabled
    assert "web" in enabled
    assert "browser" in enabled
    assert "terminal" in enabled
    assert "file" in enabled
    assert "code_execution" in enabled
    assert "cronjob" in enabled
    assert "memory" not in enabled
    assert "skills" not in enabled
    assert "image_gen" not in enabled
    assert "delegation" not in enabled

    tool_names = {
        tool["function"]["name"]
        for tool in get_tool_definitions(enabled_toolsets=sorted(enabled), quiet_mode=True)
    }
    assert "forecast_ledger" in tool_names
    assert "memory" not in tool_names
    assert "skill_manage" not in tool_names
    assert "image_generate" not in tool_names
    assert "delegate_task" not in tool_names


def test_fork_native_inherited_toolset_aliases_remain_available():
    alias_pairs = {
        "forecast-cli": "hermes-cli",
        "forecast-acp": "hermes-acp",
    }

    for alias, inherited in alias_pairs.items():
        assert validate_toolset(alias)
        assert get_toolset(alias) is not None
        assert resolve_toolset(alias) == resolve_toolset(inherited)


def test_forecast_platform_toolsets_are_scoped_to_forecasting():
    from hermes_cli.platforms import PLATFORMS

    for platform in ("telegram", "slack", "email", "cron", "api_server"):
        default_toolset = PLATFORMS[platform].default_toolset
        assert default_toolset.startswith("forecast-")
        tools = resolve_toolset(default_toolset)
        assert "forecast_ledger" in tools
        assert "memory" not in tools
        assert "skill_manage" not in tools
        assert "image_generate" not in tools
        assert "text_to_speech" not in tools
        assert "delegate_task" not in tools

    assert "discord" in resolve_toolset(PLATFORMS["discord"].default_toolset)
    assert "discord_admin" not in resolve_toolset(PLATFORMS["discord"].default_toolset)
    assert "ha_call_service" not in resolve_toolset(PLATFORMS["homeassistant"].default_toolset)
    assert "feishu_doc_read" in resolve_toolset(PLATFORMS["feishu"].default_toolset)
    assert "feishu_drive_add_comment" not in resolve_toolset(PLATFORMS["feishu"].default_toolset)
    assert "yb_send_sticker" not in resolve_toolset(PLATFORMS["yuanbao"].default_toolset)
    assert "hermes-telegram" in get_toolset("hermes-gateway")["includes"]
    assert "forecast-telegram" in get_toolset("forecast-gateway")["includes"]


def test_forecast_ledger_tool_watch_source_type_schema_is_current():
    source_types = set(
        FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["source_type"]["enum"]
    )

    assert {"github", "githubissues", "githubcommits", "githubactions", "coingecko", "pypi", "npm", "hackernews", "reddit", "bluesky", "mastodon", "reliefweb", "federalregister", "courtlistener", "nvd", "cisakev", "openmeteo", "airquality", "weatherhistory", "usgs", "eonet", "nws", "clinicaltrials", "openfda", "pubmed", "crossref", "owid", "whogho", "fema", "eia", "treasury", "census", "socrata", "ckan", "stooq", "yahoo", "secfacts", "fivethirtyeight", "wikipedia", "wikipediapageviews"} <= source_types


def test_forecast_ledger_tool_imports_airquality_forecasts(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will air-quality forecasts import through the tool?",
                "resolution_criteria": "Resolved yes if air-quality evidence is imported.",
            }
        )
    )
    question_id = created["question"]["id"]
    captured = {}

    def fake_airquality_forecasts(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            OpenMeteoAirQualityForecast(
                latitude=37.77,
                longitude=-122.42,
                forecast_time="2026-05-21T00:00:00Z",
                us_aqi=42,
                european_aqi=31,
                pm10=12.0,
                pm2_5=8.4,
                carbon_monoxide=220.0,
                nitrogen_dioxide=16.0,
                ozone=80.0,
                source_name="Open-Meteo Air Quality",
                entry_id="37.77,-122.42:2026-05-21T00:00:00Z",
                raw={"hourly_units": {"us_aqi": "US AQI"}},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_openmeteo_air_quality_forecasts", fake_airquality_forecasts)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "airquality",
                "source": "37.77,-122.42",
                "limit": 12,
                "since": "2026-05-21T00:00:00Z",
                "forecast_days": 3,
                "api_base_url": "https://airquality.test/v1/air-quality",
            }
        )
    )

    assert captured["source"] == "37.77,-122.42"
    assert captured["kwargs"]["limit"] == 12
    assert captured["kwargs"]["forecast_days"] == 3
    assert captured["kwargs"]["api_base_url"] == "https://airquality.test/v1/air-quality"
    assert imported["imported_count"] == 1
    evidence = imported["imported"][0]["evidence"]
    assert evidence["source_type"] == "adapter:airquality"
    assert evidence["source_name"] == "Open-Meteo Air Quality"
    assert evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert evidence["claim_type"] == "estimate"
    assert evidence["claim"].startswith("Open-Meteo air quality forecast for 37.77,-122.42")
    assert evidence["metadata"]["adapter"] == "airquality"
    assert evidence["metadata"]["adapter_item"]["us_aqi"] == 42


def test_forecast_ledger_tool_imports_who_gho_observations(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will WHO GHO observations import through the tool?",
                "resolution_criteria": "Resolved yes if WHO GHO evidence is imported.",
            }
        )
    )
    question_id = created["question"]["id"]
    captured = {}

    def fake_who_gho(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            WhoGhoObservation(
                indicator="WHOSIS_000001",
                spatial_dim="USA",
                time_dim="2025",
                dim1="BTSX",
                dim2=None,
                dim3=None,
                value=77.4,
                numeric_value=77.4,
                low=75.0,
                high=79.0,
                published_at="2025-01-01T00:00:00Z",
                source_url="https://ghoapi.azureedge.net/api/WHOSIS_000001",
                source_name="WHO Global Health Observatory",
                entry_id="WHOSIS_000001:USA:2025",
                raw={"NumericValue": 77.4},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_who_gho_observations", fake_who_gho)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "whogho",
                "source": "WHOSIS_000001",
                "limit": 5,
                "country": "USA",
                "dimension": ["Dim1=BTSX"],
                "api_base_url": "https://who.test/api",
            }
        )
    )

    assert captured["source"] == "WHOSIS_000001"
    assert captured["kwargs"]["limit"] == 5
    assert captured["kwargs"]["country"] == "USA"
    assert captured["kwargs"]["dimensions"] == ["Dim1=BTSX"]
    assert captured["kwargs"]["api_base_url"] == "https://who.test/api"
    assert imported["imported_count"] == 1
    evidence = imported["imported"][0]["evidence"]
    assert evidence["source_type"] == "adapter:whogho"
    assert evidence["source_name"] == "WHO Global Health Observatory"
    assert evidence["published_at"] == "2025-01-01T00:00:00Z"
    assert evidence["claim"] == "WHO GHO WHOSIS_000001 USA 2025: 77.4"
    assert evidence["metadata"]["adapter"] == "whogho"
    assert evidence["metadata"]["adapter_item"]["numeric_value"] == 77.4


def test_forecast_ledger_tool_imports_fema_declarations(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will FEMA declarations import through the tool?",
                "resolution_criteria": "Resolved yes if FEMA evidence is imported.",
            }
        )
    )
    question_id = created["question"]["id"]
    captured = {}

    def fake_fema(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            FemaDisasterDeclaration(
                disaster_number=5001,
                declaration_string="DR-5001-CA",
                state="CA",
                declaration_type="DR",
                declaration_date="2025-01-03T00:00:00Z",
                fiscal_year=2025,
                incident_type="Fire",
                title="California Wildfires",
                designated_area="Los Angeles County",
                incident_begin_date="2025-01-01T00:00:00Z",
                incident_end_date=None,
                individual_assistance=True,
                public_assistance=False,
                hazard_mitigation=True,
                last_refresh="2025-01-04T00:00:00Z",
                source_url="https://www.fema.gov/api/open/v2/DisasterDeclarationsSummaries",
                source_name="FEMA Disaster Declarations Summaries",
                entry_id="declaration-5001",
                raw={"disasterNumber": 5001},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_fema_disaster_declarations", fake_fema)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "fema",
                "source": "state=CA&incidentType=Fire",
                "limit": 5,
                "state": "CA",
                "incident_type": "Fire",
                "declaration_type": "DR",
                "api_base_url": "https://fema.test/api/open/v2/DisasterDeclarationsSummaries",
            }
        )
    )

    assert captured["source"] == "state=CA&incidentType=Fire"
    assert captured["kwargs"]["limit"] == 5
    assert captured["kwargs"]["state"] == "CA"
    assert captured["kwargs"]["incident_type"] == "Fire"
    assert captured["kwargs"]["declaration_type"] == "DR"
    assert captured["kwargs"]["api_base_url"] == "https://fema.test/api/open/v2/DisasterDeclarationsSummaries"
    assert imported["imported_count"] == 1
    evidence = imported["imported"][0]["evidence"]
    assert evidence["source_type"] == "adapter:fema"
    assert evidence["source_name"] == "FEMA Disaster Declarations Summaries"
    assert evidence["published_at"] == "2025-01-03T00:00:00Z"
    assert evidence["claim"] == "FEMA 5001 CA Los Angeles County: Fire"
    assert evidence["metadata"]["adapter"] == "fema"
    assert evidence["metadata"]["adapter_item"]["hazard_mitigation"] is True


def test_forecast_ledger_tool_imports_weatherhistory_observations(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will historical weather import through the tool?",
                "resolution_criteria": "Resolved yes if historical weather evidence is imported.",
            }
        )
    )
    question_id = created["question"]["id"]
    captured = {}

    def fake_weatherhistory(source: str, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            OpenMeteoHistoricalWeatherObservation(
                latitude=37.77,
                longitude=-122.42,
                observation_date="2026-05-20",
                temperature_2m_mean=16.2,
                temperature_2m_max=21.5,
                temperature_2m_min=12.1,
                precipitation_sum=0.0,
                wind_speed_10m_max=18.0,
                source_name="Open-Meteo Historical Weather",
                entry_id="37.77,-122.42:2026-05-20",
                raw={"daily_units": {"temperature_2m_mean": "C"}},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_openmeteo_historical_weather", fake_weatherhistory)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "weatherhistory",
                "source": "37.77,-122.42",
                "limit": 3,
                "start_date": "2026-05-20",
                "end_date": "2026-05-21",
                "api_base_url": "https://history.test/v1/archive",
            }
        )
    )

    assert captured["source"] == "37.77,-122.42"
    assert captured["kwargs"]["start_date"] == "2026-05-20"
    assert captured["kwargs"]["end_date"] == "2026-05-21"
    assert captured["kwargs"]["api_base_url"] == "https://history.test/v1/archive"
    assert imported["imported_count"] == 1
    evidence = imported["imported"][0]["evidence"]
    assert evidence["source_type"] == "adapter:weatherhistory"
    assert evidence["source_name"] == "Open-Meteo Historical Weather"
    assert evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert evidence["claim_type"] == "fact"
    assert evidence["claim"].startswith("Open-Meteo historical weather for 37.77,-122.42")
    assert evidence["metadata"]["adapter"] == "weatherhistory"
    assert evidence["metadata"]["adapter_item"]["temperature_2m_mean"] == 16.2


def test_forecast_ledger_tool_imports_sec_company_facts(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will SEC facts import through the tool?",
                "resolution_criteria": "Resolved yes if SEC facts import through the tool.",
            }
        )
    )
    question_id = created["question"]["id"]
    captured = {}

    def fake_sec_company_facts(source, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            SecCompanyFact(
                cik="0000320193",
                company_name="Apple Inc.",
                taxonomy="us-gaap",
                concept="Revenues",
                label="Revenues",
                description="Revenue from contract with customer.",
                unit="USD",
                observation_date="2025-09-27",
                value=391035000000,
                filed_at="2025-10-31T00:00:00Z",
                published_at="2025-10-31T00:00:00Z",
                form="10-K",
                fiscal_year=2025,
                fiscal_period="FY",
                accession_number="0000320193-25-000079",
                frame="CY2025",
                source_url="https://sec.test/companyfacts/CIK0000320193.json",
                source_name="SEC Company Facts",
                entry_id="0000320193:us-gaap:Revenues:USD:2025-09-27:0000320193-25-000079",
                raw={"row": {"val": 391035000000}},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_sec_company_facts", fake_sec_company_facts)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "secfacts",
                "source": "0000320193/Revenues",
                "limit": 1,
                "since": "2025-01-01",
                "taxonomy": "us-gaap",
                "unit": "USD",
                "api_base_url": "https://sec.test/companyfacts",
            }
        )
    )

    assert captured["source"] == "0000320193/Revenues"
    assert captured["kwargs"]["taxonomy"] == "us-gaap"
    assert captured["kwargs"]["unit"] == "USD"
    assert captured["kwargs"]["api_base_url"] == "https://sec.test/companyfacts"
    assert imported["imported_count"] == 1
    evidence = imported["imported"][0]["evidence"]
    assert evidence["source_type"] == "adapter:secfacts"
    assert evidence["source_name"] == "SEC Company Facts"
    assert evidence["claim"] == (
        "SEC Company Facts Apple Inc. Revenues was 391035000000 USD for 2025-09-27"
    )
    assert evidence["published_at"] == "2025-10-31T00:00:00Z"
    assert evidence["metadata"]["adapter"] == "secfacts"
    assert evidence["metadata"]["adapter_item"]["concept"] == "Revenues"


def test_forecast_ledger_tool_imports_fivethirtyeight_polls(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will polling import through the tool?",
                "resolution_criteria": "Resolved yes if polling import through the tool.",
            }
        )
    )
    question_id = created["question"]["id"]
    captured = {}

    def fake_fivethirtyeight_polls(source, **kwargs):
        captured["source"] = source
        captured["kwargs"] = kwargs
        return [
            FiveThirtyEightPollObservation(
                dataset="president_polls",
                poll_id="p1",
                question_id="q1",
                pollster="Example Polls",
                pollster_grade="A",
                race_id="r1",
                office_type="PRES",
                state="PA",
                cycle=2026,
                stage="general",
                candidate_name="Jane Candidate",
                answer="Jane Candidate",
                party="DEM",
                pct=48.4,
                sample_size=1000,
                population="lv",
                start_date="2026-05-20",
                end_date="2026-05-22",
                published_at="2026-05-23T00:00:00Z",
                source_url="https://polls.test/p1",
                source_name="Example Polls",
                entry_id="president_polls:p1:q1:Jane Candidate",
                raw={"poll_id": "p1"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_fivethirtyeight_polls", fake_fivethirtyeight_polls)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "fivethirtyeight",
                "source": "president",
                "limit": 1,
                "since": "2026-05-01",
                "state": "PA",
                "candidate": "Jane",
                "pollster": "Example",
                "cycle": 2026,
                "office_type": "PRES",
                "api_base_url": "https://polls.test/data",
            }
        )
    )

    assert captured["source"] == "president"
    assert captured["kwargs"]["state"] == "PA"
    assert captured["kwargs"]["candidate"] == "Jane"
    assert captured["kwargs"]["pollster"] == "Example"
    assert captured["kwargs"]["cycle"] == 2026
    assert captured["kwargs"]["office_type"] == "PRES"
    assert captured["kwargs"]["api_base_url"] == "https://polls.test/data"
    assert imported["imported_count"] == 1
    evidence = imported["imported"][0]["evidence"]
    assert evidence["source_type"] == "adapter:fivethirtyeight"
    assert evidence["source_name"] == "Example Polls"
    assert evidence["claim"] == "FiveThirtyEight poll president_polls: Jane Candidate 48.4% in PA"
    assert evidence["claim_type"] == "estimate"
    assert evidence["published_at"] == "2026-05-23T00:00:00Z"
    assert evidence["metadata"]["adapter"] == "fivethirtyeight"
    assert evidence["metadata"]["adapter_item"]["pct"] == 48.4


def test_forecast_ledger_tool_lifecycle(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool lifecycle work?",
                "resolution_criteria": "Resolved yes if the tool can score a forecast.",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Initial evidence note.",
                "available_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.7,
                "rationale": "Evidence supports yes.",
                "as_of": "2026-01-02T00:00:00Z",
                "evidence_refs": [evidence["evidence"]["id"]],
            }
        )
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "resolve",
            "question_id": question_id,
            "outcome": "yes",
        }
    )
    score = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "score",
                "question_id": question_id,
            }
        )
    )

    assert updated["forecast_snapshot"]["forecast_id"]
    assert score["score"]["brier_score"] == 0.09000000000000002
    assert ForecastLedger(db).get_question(question_id).current_forecast_id == updated["forecast_snapshot"]["forecast_id"]


def test_forecast_ledger_tool_can_require_update_citations(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool citation policy work?",
                "resolution_criteria": "Resolved yes if the agent tool can enforce citations.",
            }
        )
    )
    question_id = created["question"]["id"]
    uncited = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.5,
                "rationale": "Uncited factual claim.",
                "require_citations": True,
            }
        )
    )
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Tool-cited evidence.",
                "available_at": "2026-01-01T00:00:00Z",
            }
        )
    )
    cited = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.55,
                "rationale": "Tool-cited evidence supports the update.",
                "as_of": "2026-01-02T00:00:00Z",
                "evidence_refs": [evidence["evidence"]["id"]],
                "require_citations": True,
            }
        )
    )

    assert uncited["success"] is False
    assert "requires citations" in uncited["error"]
    assert cited["forecast_snapshot"]["evidence_refs"] == [evidence["evidence"]["id"]]
    assert cited["forecast_snapshot"]["metadata"]["citation_policy"] == "required"


def test_forecast_ledger_tool_stores_resolution_provenance(tmp_path):
    db = str(tmp_path / "forecasting.db")
    source = tmp_path / "resolution.txt"
    source.write_text("official result: no", encoding="utf-8")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool resolution provenance persist?",
                "resolution_criteria": "Resolved no if provenance fields are stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    resolved = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "resolve",
                "question_id": question_id,
                "outcome": "no",
                "resolution_source": str(source),
                "resolver_type": "source_adapter",
                "resolution_status": "confirmed",
                "criteria_satisfied": True,
                "confidence": 0.82,
                "confirmed_by": "official-results-adapter",
                "resolver_notes": "Matched the published outcome.",
                "scoreable": False,
            }
        )
    )

    resolution = resolved["resolution"]
    assert resolution["outcome"] == "no"
    assert resolution["resolution_source"] == str(source)
    assert resolution["resolution_source_snapshot_ref"]
    assert Path(resolution["resolution_source_snapshot_ref"]).exists()
    assert resolution["resolver_type"] == "source_adapter"
    assert resolution["resolution_status"] == "confirmed"
    assert resolution["criteria_satisfied"] is True
    assert resolution["confidence"] == pytest.approx(0.82)
    assert resolution["confirmed_by"] == "official-results-adapter"
    assert resolution["resolver_notes"] == "Matched the published outcome."
    assert resolution["scoreable"] is False


def test_forecast_ledger_tool_records_structured_postmortem_learning(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool postmortems preserve learning fields?",
                "resolution_criteria": "Resolved no if structured postmortems are persisted.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.82,
            "rationale": "Inside-view signal looked strong.",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "resolve",
            "question_id": question_id,
            "outcome": "no",
        }
    )

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "Overweighted a policy signal.",
                "what_happened": "The policy did not pass.",
                "what_was_expected": "Expected a high chance of passage.",
                "missed_evidence": "Committee calendar delays.",
                "overweighted_evidence": "Sponsor statements.",
                "base_rate_error": "Ignored prior committee failure rates.",
                "inside_view_error": "Treated rhetoric as commitment.",
                "resolution_error": "No resolution ambiguity.",
                "lesson": "Discount sponsor rhetoric when calendar evidence is weak.",
                "calibration_adjustment": {"probability_delta": -0.04},
            }
        )
    )

    postmortem = result["postmortem"]
    lessons = ForecastLedger(db).list_calibration_lessons(scope_type="domain", scope_ref="macro")
    assert postmortem["summary"] == "Overweighted a policy signal."
    assert postmortem["what_happened"] == "The policy did not pass."
    assert postmortem["what_was_expected"] == "Expected a high chance of passage."
    assert postmortem["missed_evidence"] == "Committee calendar delays."
    assert postmortem["overweighted_evidence"] == "Sponsor statements."
    assert postmortem["base_rate_error"] == "Ignored prior committee failure rates."
    assert postmortem["inside_view_error"] == "Treated rhetoric as commitment."
    assert postmortem["resolution_error"] == "No resolution ambiguity."
    assert postmortem["lesson"] == "Discount sponsor rhetoric when calendar evidence is weak."
    assert postmortem["calibration_adjustment"] == {"probability_delta": -0.04}
    assert lessons[0]["source_postmortem_refs"] == [postmortem["id"]]
    assert lessons[0]["recommended_adjustment"] == {"probability_delta": -0.04}


def test_forecast_ledger_tool_creates_questions_with_forecast_metadata(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool metadata persist?",
                "description": "Question metadata should survive tool creation.",
                "resolution_criteria": "Resolved yes if metadata is stored.",
                "resolution_source": "official filing",
                "domain": "macro",
                "topics": ["rates", "inflation"],
                "tags": ["portfolio:global-macro"],
                "owner": "research",
                "impact": "high",
                "outcome_type": "numeric",
                "choices": [],
                "units": "percent",
                "bounds": [0, 10],
                "close_time": "2026-06-01T00:00:00Z",
                "resolution_time": "2026-07-01T00:00:00Z",
                "review_cadence": "3d",
                "next_review_at": "2026-05-01T00:00:00Z",
            }
        )
    )

    ledger = ForecastLedger(db)
    question = ledger.get_question(created["question"]["id"])
    schedules = ledger.list_scheduled_reviews()

    assert question.description == "Question metadata should survive tool creation."
    assert question.resolution_source == "official filing"
    assert question.domain == "macro"
    assert question.topics == ["rates", "inflation"]
    assert question.tags == ["portfolio:global-macro"]
    assert question.owner == "research"
    assert question.impact == "high"
    assert question.outcome_space.type == "numeric"
    assert question.outcome_space.units == "percent"
    assert question.outcome_space.bounds == [0, 10]
    assert question.close_time == "2026-06-01T00:00:00Z"
    assert question.resolution_time == "2026-07-01T00:00:00Z"
    assert schedules[0]["scope_ref"] == question.id
    assert schedules[0]["cadence"] == "3d"


def test_forecast_ledger_tool_show_question_returns_research_context(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will show question include context?",
                "resolution_criteria": "Resolved yes if agent context includes research artifacts.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Context evidence.",
            }
        )
    )["evidence"]
    assumption = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_assumption",
                "question_id": question_id,
                "text": "Indicator remains comparable.",
            }
        )
    )["assumption"]
    reference = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_reference_class",
                "question_id": question_id,
                "name": "Comparable macro releases",
                "inclusion_criteria": "Same country and indicator family.",
                "base_rate": 0.48,
            }
        )
    )["reference_class"]
    model = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "sensitivity",
                "output": {"probability": 0.57},
            }
        )
    )["model_run"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.57,
            "rationale": "Context update.",
            "evidence_refs": [evidence["id"]],
            "assumption_refs": [assumption["id"]],
            "reference_class_refs": [reference["id"]],
            "model_run_refs": [model["id"]],
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "yes"})
    score = json.loads(forecast_ledger_tool({"db": db, "action": "score", "question_id": question_id}))["score"]
    postmortem = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "Context postmortem.",
            }
        )
    )["postmortem"]

    shown = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "show_question",
                "question_id": question_id,
            }
        )
    )

    assert shown["question"]["id"] == question_id
    assert shown["current_forecast"]["evidence_refs"] == [evidence["id"]]
    assert shown["forecast_history"][0]["forecast_id"] == shown["current_forecast"]["forecast_id"]
    assert shown["evidence"][0]["id"] == evidence["id"]
    assert shown["assumptions"][0]["id"] == assumption["id"]
    assert shown["reference_classes"][0]["id"] == reference["id"]
    assert model["id"] in {row["id"] for row in shown["model_runs"]}
    assert shown["scores"][0]["id"] == score["id"]
    assert shown["postmortems"][0]["id"] == postmortem["id"]


def test_forecast_ledger_tool_manages_baseline_comparisons(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool baselines be comparable?",
                "resolution_criteria": "Resolved yes if agent baselines are stored.",
            }
        )
    )
    question_id = created["question"]["id"]
    added = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_baseline_comparison",
                "question_id": question_id,
                "source": "market-fixture",
                "baseline_type": "market",
                "probability_or_distribution": 0.63,
                "as_of": "2026-01-01T00:00:00Z",
                "metadata": {"market_id": "fixture-1"},
            }
        )
    )
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_baseline_comparisons",
                "question_id": question_id,
            }
        )
    )
    shown = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "show_question",
                "question_id": question_id,
            }
        )
    )

    assert added["baseline_comparison"]["baseline_type"] == "market"
    assert listed["baseline_comparisons"][0]["source"] == "market-fixture"
    assert listed["baseline_comparisons"][0]["probability_or_distribution"] == pytest.approx(0.63)
    assert listed["baseline_comparisons"][0]["metadata"] == {"market_id": "fixture-1"}
    assert shown["baseline_comparisons"][0]["id"] == added["baseline_comparison"]["id"]


def test_forecast_ledger_tool_adds_strict_evidence_metadata(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool evidence metadata persist?",
                "resolution_criteria": "Resolved yes if strict source metadata is stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "https://example.com/report",
                "source_url": "https://example.com/report",
                "source_name": "Example Research",
                "source_type": "url",
                "published_at": "2026-01-01T12:00:00Z",
                "available_at": "2026-01-02T00:00:00Z",
                "claim": "The report supports the forecast.",
                "claim_type": "estimate",
                "summary": "A timestamped source summary.",
                "reliability_rating": 0.83,
                "relevance_rating": 0.76,
                "stance": "supports",
                "admissible_for_backtests": False,
                "metadata": {"source_snapshot_id": "snap-1"},
            }
        )
    )

    evidence = result["evidence"]
    assert evidence["source_url"] == "https://example.com/report"
    assert evidence["source_name"] == "Example Research"
    assert evidence["source_type"] == "url"
    assert evidence["published_at"] == "2026-01-01T12:00:00Z"
    assert evidence["available_at"] == "2026-01-02T00:00:00Z"
    assert evidence["claim_type"] == "estimate"
    assert evidence["reliability_rating"] == pytest.approx(0.83)
    assert evidence["relevance_rating"] == pytest.approx(0.76)
    assert evidence["stance"] == "supports"
    assert evidence["admissible_for_backtests"] is False
    assert evidence["metadata"]["source_snapshot_id"] == "snap-1"


def test_forecast_ledger_tool_manages_assumptions(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool assumptions persist?",
                "resolution_criteria": "Resolved yes if assumptions can be managed.",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Assumption source.",
            }
        )
    )
    added = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_assumption",
                "question_id": question_id,
                "text": "Policy conditions remain unchanged.",
                "check_cadence": "7d",
                "evidence_refs": [evidence["evidence"]["id"]],
                "notes": "Initial assumption.",
            }
        )
    )
    assumption_id = added["assumption"]["id"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_assumptions",
                "question_id": question_id,
            }
        )
    )
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_assumption",
                "assumption_id": assumption_id,
                "status": "invalidated",
                "last_checked_at": "2026-01-05T00:00:00Z",
                "notes": "Policy changed.",
            }
        )
    )

    assert listed["assumptions"][0]["id"] == assumption_id
    assert listed["assumptions"][0]["check_cadence"] == "7d"
    assert listed["assumptions"][0]["evidence_refs"] == [evidence["evidence"]["id"]]
    assert updated["assumption"]["status"] == "invalidated"
    assert updated["assumption"]["last_checked_at"] == "2026-01-05T00:00:00Z"
    assert updated["assumption"]["invalidated_at"] is not None
    assert updated["assumption"]["notes"] == "Policy changed."


def test_forecast_ledger_tool_checks_watched_sources(tmp_path):
    db = str(tmp_path / "forecasting.db")
    source = tmp_path / "source.txt"
    source.write_text("initial", encoding="utf-8")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool watches detect changes?",
                "resolution_criteria": "Resolved yes if tool watch alerts are created.",
            }
        )
    )
    question_id = created["question"]["id"]
    watch = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_watched_source",
                "question_id": question_id,
                "source": str(source),
            }
        )
    )

    source.write_text("changed", encoding="utf-8")
    checked = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "check_watched_sources",
                "scope_type": "question",
                "scope_ref": question_id,
            }
        )
    )

    assert watch["watched_source"]["source_type"] == "file"
    assert checked["alerts"][0]["reason"] == f"watched_source_changed:{watch['watched_source']['id']}"


def test_forecast_ledger_tool_can_save_ensemble_components(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool ensemble updates work?",
                "resolution_criteria": "Resolved yes if tool ensemble components are stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "components": {
                    "base_rate": {"probability": 0.4, "weight": 2},
                    "inside_view": {"probability": 0.7, "weight": 1},
                },
                "rationale": "Tool-saved ensemble update.",
                "method": "weighted_ensemble",
            }
        )
    )

    snapshot = ForecastLedger(db).get_snapshot(updated["forecast_snapshot"]["forecast_id"])
    assert snapshot.probability_or_distribution == 0.5
    assert snapshot.ensemble_components["base_rate"]["weight"] == 2
    assert snapshot.method == "weighted_ensemble"


def test_forecast_ledger_tool_records_model_run_provenance(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool model provenance persist?",
                "resolution_criteria": "Resolved yes if model run provenance is stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "bayesian_update",
                "inputs": {"prior": 0.45},
                "parameters": {"likelihood_ratio": 1.4},
                "output": {"posterior": 0.53},
                "diagnostics": {"sensitivity": "medium"},
                "code_ref": "models/bayes.py@abc123",
                "artifact_paths": ["artifacts/run-1.json"],
                "model_version": "bayes-v2",
                "prompt_version": "decomp-v1",
                "data_version": "evidence-cut-2026-01-01",
                "evidence_cutoff": "2026-01-01T00:00:00Z",
            }
        )
    )

    model_run = result["model_run"]
    assert model_run["model_type"] == "bayesian_update"
    assert model_run["inputs"] == {"prior": 0.45}
    assert model_run["parameters"] == {"likelihood_ratio": 1.4}
    assert model_run["output"] == {"posterior": 0.53}
    assert model_run["diagnostics"] == {"sensitivity": "medium"}
    assert model_run["code_ref"] == "models/bayes.py@abc123"
    assert model_run["artifact_paths"] == ["artifacts/run-1.json"]
    assert model_run["model_version"] == "bayes-v2"
    assert model_run["prompt_version"] == "decomp-v1"
    assert model_run["data_version"] == "evidence-cut-2026-01-01"
    assert model_run["evidence_cutoff"] == "2026-01-01T00:00:00Z"


def test_forecast_ledger_tool_computes_trend_projection_model_run(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool trend projection persist?",
                "resolution_criteria": "Resolved yes if trend model output is stored.",
            }
        )
    )
    question_id = created["question"]["id"]

    result = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "trend_projection",
                "series": [[0, 10], [1, 12], [2, 14]],
                "target_x": 3,
            }
        )
    )

    model_run = result["model_run"]
    assert model_run["model_type"] == "trend_projection"
    assert model_run["output"]["projected_value"] == pytest.approx(16.0)
    assert model_run["output"]["slope"] == pytest.approx(2.0)
    assert model_run["parameters"]["target_x"] == 3


def test_forecast_ledger_tool_lists_model_runs_and_postmortems(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool learning artifacts be inspectable?",
                "resolution_criteria": "Resolved no if model runs and postmortems can be listed.",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "record_model_run",
            "question_id": question_id,
            "model_type": "reference_class",
            "output": {"base_rate": 0.4},
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.7,
            "rationale": "Model run pushed probability higher.",
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "no"})
    created_postmortem = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "The base-rate comparison was too loose.",
                "lesson": "Tighten reference classes before moving above 0.6.",
            }
        )
    )["postmortem"]

    model_runs = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_model_runs",
                "question_id": question_id,
            }
        )
    )
    postmortems = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_postmortems",
                "question_id": question_id,
            }
        )
    )

    assert model_runs["model_runs"][0]["model_type"] == "reference_class"
    assert model_runs["model_runs"][0]["output"] == {"base_rate": 0.4}
    assert postmortems["postmortems"][0]["id"] == created_postmortem["id"]
    assert postmortems["postmortems"][0]["summary"] == "The base-rate comparison was too loose."
    assert postmortems["postmortems"][0]["lesson"] == "Tighten reference classes before moving above 0.6."


def test_forecast_ledger_tool_exports_audit_packets(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool exports include audit data?",
                "resolution_criteria": "Resolved yes if export packets are available to agents.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Export evidence note.",
                "claim": "A relevant indicator moved.",
            }
        )
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.61,
            "rationale": "Evidence nudged the forecast.",
            "evidence_refs": [evidence["evidence"]["id"]],
        }
    )

    question_packet = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "export_question",
                "question_id": question_id,
                "format": "json",
            }
        )
    )
    markdown_packet = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "export_question",
                "question_id": question_id,
                "format": "markdown",
            }
        )
    )
    portfolio_packet = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "export_all",
                "format": "json",
            }
        )
    )

    assert question_packet["packet"]["question"]["id"] == question_id
    assert question_packet["packet"]["forecast_history"][0]["evidence_refs"] == [evidence["evidence"]["id"]]
    assert question_packet["packet"]["evidence"][0]["claim"] == "A relevant indicator moved."
    assert markdown_packet["export"].startswith("# Forecast Packet:")
    assert portfolio_packet["packet"]["questions"][0]["question"]["id"] == question_id


def test_forecast_ledger_tool_returns_pilot_report(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool pilot report summarize artifacts?",
                "resolution_criteria": "Resolved yes if tool reports pilot checks.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    evidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_evidence",
                "question_id": question_id,
                "source_or_note": "Structured source row.",
                "source_type": "fred",
            }
        )
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.55,
            "rationale": "Structured evidence is enough for the pilot report.",
            "evidence_refs": [evidence["evidence"]["id"]],
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "schedule_review",
            "question_id": question_id,
            "cadence": "1d",
            "next_run_at": "2026-05-24T09:00:00Z",
        }
    )

    report = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "pilot_report",
                "min_questions": 1,
                "min_structured_source_questions": 1,
                "min_scores": 0,
                "min_postmortems": 0,
                "min_scheduled_reviews": 1,
            }
        )
    )

    assert report["pilot_report"]["pilot_status"] == "pilot_exit_ready"
    assert report["pilot_report"]["summary"]["questions_with_structured_sources"] == 1
    assert report["pilot_report"]["source_types"]["fred"] == 1


def test_forecast_ledger_tool_records_corrections_and_invalidates_learning(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool corrections invalidate learning?",
                "resolution_criteria": "Resolved no if applied corrections mark dependent learning invalid.",
                "domain": "policy",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.8,
            "rationale": "Wrong source was trusted.",
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "no"})
    score = json.loads(forecast_ledger_tool({"db": db, "action": "score", "question_id": question_id}))["score"]
    postmortem = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "postmortem",
                "question_id": question_id,
                "summary": "The source was later corrected.",
                "lesson": "Discount this source class.",
            }
        )
    )["postmortem"]
    lesson = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_calibration_lessons",
                "scope_type": "domain",
                "scope_ref": "policy",
            }
        )
    )["calibration_lessons"][0]

    created_correction = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_correction",
                "target_type": "score_record",
                "target_id": score["id"],
                "reason": "Resolution source was corrected after scoring.",
                "created_by": "forecast-agent",
                "old_value": {"outcome": "no"},
                "new_value": {"outcome": "yes"},
                "patch": {"resolution": "corrected"},
                "status": "applied",
            }
        )
    )["correction"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_corrections",
                "target_type": "score_record",
                "target_id": score["id"],
            }
        )
    )
    ledger = ForecastLedger(db)

    assert listed["corrections"][0]["id"] == created_correction["id"]
    assert created_correction["affected_score_record_refs"] == [score["id"]]
    assert created_correction["affected_postmortem_refs"] == [postmortem["id"]]
    assert created_correction["affected_calibration_lesson_refs"] == [lesson["id"]]
    assert ledger.get_score(score["id"]).invalidated_by_correction_id == created_correction["id"]
    assert ledger.get_postmortem(postmortem["id"])["invalidated_by_correction_id"] == created_correction["id"]
    assert ledger.get_calibration_lesson(lesson["id"])["invalidated_by_correction_id"] == created_correction["id"]


def test_forecast_ledger_tool_lists_scores_for_calibration_review(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool score listing support calibration review?",
                "resolution_criteria": "Resolved yes if score records can be filtered.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.72,
            "rationale": "Macro forecast for score listing.",
            "forecast_origin": "live",
        }
    )
    forecast_ledger_tool({"db": db, "action": "resolve", "question_id": question_id, "outcome": "yes"})
    score = json.loads(forecast_ledger_tool({"db": db, "action": "score", "question_id": question_id}))["score"]

    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_scores",
                "domain": "macro",
                "forecast_origin": "live",
                "bucket": score["calibration_bucket"],
                "calibration_eligible": True,
            }
        )
    )

    assert listed["scores"][0]["id"] == score["id"]
    assert listed["scores"][0]["domain"] == "macro"
    assert listed["scores"][0]["forecast_origin"] == "live"
    assert listed["scores"][0]["calibration_bucket"] == score["calibration_bucket"]


def test_forecast_ledger_tool_manages_trusted_resolver_policies(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_trusted_resolver_policy",
                "resolver_plugin": "official-results",
                "plugin_version": "1.2.0",
                "scope_type": "source",
                "scope_ref": "official-election-board",
                "enabled": True,
                "approved_by": "research-lead",
                "audit_log_ref": "audit://resolver-policy/1",
            }
        )
    )
    policy = created["trusted_resolver_policy"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_trusted_resolver_policies",
                "resolver_plugin": "official-results",
                "scope_type": "source",
                "enabled": True,
            }
        )
    )
    question = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will trusted resolver usage be audited?",
                "resolution_criteria": "Resolved yes if trusted resolver policy usage updates last_used_at.",
            }
        )
    )["question"]
    resolved = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "resolve",
                "question_id": question["id"],
                "outcome": "yes",
                "resolver_type": "source_adapter",
                "trusted_policy_id": policy["id"],
            }
        )
    )
    stored_policy = ForecastLedger(db).get_trusted_resolver_policy(policy["id"])

    assert listed["trusted_resolver_policies"][0]["id"] == policy["id"]
    assert listed["trusted_resolver_policies"][0]["enabled"] is True
    assert resolved["resolution"]["trusted_policy_id"] == policy["id"]
    assert stored_policy["last_used_at"] is not None


def test_forecast_ledger_tool_manages_reference_class_review_state(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool reference classes be reviewable?",
                "resolution_criteria": "Resolved yes if reference classes can be checked and invalidated.",
            }
        )
    )
    question_id = created["question"]["id"]
    added = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_reference_class",
                "question_id": question_id,
                "name": "Comparable policy votes",
                "inclusion_criteria": "Recent committee votes with similar sponsors.",
                "exclusion_criteria": "Unrelated floor votes.",
                "base_rate": 0.42,
                "uncertainty": 0.08,
                "check_cadence": "14d",
                "notes": "Initial base-rate book.",
            }
        )
    )
    reference_class_id = added["reference_class"]["id"]
    listed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_reference_classes",
                "question_id": question_id,
            }
        )
    )
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_reference_class",
                "reference_class_id": reference_class_id,
                "status": "invalidated",
                "last_checked_at": "2026-01-07T00:00:00Z",
                "notes": "Reference class no longer comparable.",
            }
        )
    )

    assert listed["reference_classes"][0]["id"] == reference_class_id
    assert listed["reference_classes"][0]["check_cadence"] == "14d"
    assert listed["reference_classes"][0]["notes"] == "Initial base-rate book."
    assert updated["reference_class"]["status"] == "invalidated"
    assert updated["reference_class"]["last_checked_at"] == "2026-01-07T00:00:00Z"
    assert updated["reference_class"]["invalidated_at"] is not None
    assert updated["reference_class"]["notes"] == "Reference class no longer comparable."


def test_forecast_ledger_tool_stores_snapshot_audit_metadata(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool snapshot metadata persist?",
                "resolution_criteria": "Resolved yes if snapshot metadata is auditable.",
            }
        )
    )
    question_id = created["question"]["id"]
    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.62,
                "rationale": "Store tool audit metadata.",
                "as_of": "2026-01-01T00:00:00Z",
                "method": "structured_judgment",
                "key_assumptions": ["Policy signal remains valid."],
                "forecast_origin": "live",
                "agent_model": "test-model",
                "prompt_version": "prompt-v1",
                "forecasting_protocol_version": "protocol-v1",
                "toolset_version": "forecast-tool-v1",
                "source_snapshot_refs": ["src_snap_1"],
                "evidence_cutoff": "2026-01-01T00:00:00Z",
                "calibration_eligible": False,
                "calibration_weight": 0.25,
                "metadata": {"created_by": "forecast_ledger_tool"},
            }
        )
    )

    snapshot = ForecastLedger(db).get_snapshot(updated["forecast_snapshot"]["forecast_id"])
    assert snapshot.method == "structured_judgment"
    assert snapshot.key_assumptions == ["Policy signal remains valid."]
    assert snapshot.forecast_origin == "live"
    assert snapshot.agent_model == "test-model"
    assert snapshot.prompt_version == "prompt-v1"
    assert snapshot.forecasting_protocol_version == "protocol-v1"
    assert snapshot.toolset_version == "forecast-tool-v1"
    assert snapshot.source_snapshot_refs == ["src_snap_1"]
    assert snapshot.evidence_cutoff == "2026-01-01T00:00:00Z"
    assert snapshot.calibration_eligible is False
    assert snapshot.calibration_weight == pytest.approx(0.25)
    assert snapshot.metadata["created_by"] == "forecast_ledger_tool"


def test_forecast_ledger_tool_can_apply_active_calibration_lessons(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool learning adjust forecasts?",
                "resolution_criteria": "Resolved yes if the tool applies active lessons.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    ledger = ForecastLedger(db)
    lesson = ledger.create_calibration_lesson(
        scope_type="domain",
        scope_ref="macro",
        lesson="Macro tool updates should discount policy-shock overconfidence.",
        status="active",
        recommended_adjustment={"probability_delta": -0.06},
    )

    updated = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "update_forecast",
                "question_id": question_id,
                "probability": 0.7,
                "rationale": "Tool applies active lesson.",
                "use_active_lessons": True,
            }
        )
    )

    snapshot = ledger.get_snapshot(updated["forecast_snapshot"]["forecast_id"])
    assert snapshot.probability_or_distribution == pytest.approx(0.64)
    assert snapshot.calibration_lesson_refs == [lesson["id"]]
    assert snapshot.calibration_adjustment["raw_probability"] == pytest.approx(0.7)
    assert snapshot.calibration_adjustment["applied_probability_delta"] == pytest.approx(-0.06)


def test_forecast_ledger_tool_manages_scheduled_reviews(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool schedules run?",
                "resolution_criteria": "Resolved yes if scheduled reviews run through the tool.",
            }
        )
    )
    question_id = created["question"]["id"]

    scheduled = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "schedule_review",
                "question_id": question_id,
                "cadence": "1d",
                "next_run_at": "2026-01-01T00:00:00Z",
                "auto_score": True,
                "auto_postmortem": True,
            }
        )
    )
    review_id = scheduled["scheduled_review"]["id"]
    listed = json.loads(
        forecast_ledger_tool({"db": db, "action": "list_scheduled_reviews"})
    )
    ran = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "run_scheduled_reviews",
                "now": "2026-01-02T00:00:00Z",
            }
        )
    )

    assert listed["scheduled_reviews"][0]["id"] == review_id
    assert listed["scheduled_reviews"][0]["scope_ref"] == question_id
    assert bool(listed["scheduled_reviews"][0]["auto_score"]) is True
    assert bool(listed["scheduled_reviews"][0]["auto_postmortem"]) is True
    assert ran["scheduled_review_results"][0]["review"]["id"] == review_id
    assert ran["scheduled_review_results"][0]["review"]["last_run_at"] == "2026-01-02T00:00:00Z"
    assert ran["scheduled_review_results"][0]["alerts"][0]["reason"] == "no_forecast_snapshot"


def test_forecast_ledger_tool_reviews_and_schedules_by_horizon(tmp_path):
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    short_horizon = ledger.create_question(
        title="Will tool short horizon be reviewed?",
        resolution_criteria="Resolved yes if horizon review includes this.",
        close_time="2026-01-25T00:00:00Z",
    )
    long_horizon = ledger.create_question(
        title="Will tool long horizon be ignored?",
        resolution_criteria="Resolved yes if horizon review excludes this.",
        close_time="2026-06-01T00:00:00Z",
    )
    for question in (short_horizon, long_horizon):
        ledger.create_snapshot(
            question_id=question.id,
            probability_or_distribution=0.5,
            rationale="Initial forecast.",
            as_of="2026-01-01T00:00:00Z",
        )

    reviewed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "review",
                "stale": True,
                "last_days": 7,
                "horizon": "30",
                "now": "2026-01-10T00:00:00Z",
            }
        )
    )
    scheduled = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "schedule_review",
                "horizon": "30",
                "cadence": "1d",
                "next_run_at": "2026-01-02T00:00:00Z",
                "stale_days": 3,
            }
        )
    )

    assert [row["question"]["id"] for row in reviewed["review"]] == [short_horizon.id]
    assert scheduled["scheduled_review"]["scope_type"] == "horizon"
    assert scheduled["scheduled_review"]["scope_ref"] == "30"
    assert scheduled["scheduled_review"]["stale_days"] == 3


def test_forecast_ledger_tool_self_check_and_schedule_filter_by_confidence(tmp_path):
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    low_confidence = ledger.create_question(
        title="Will tool confidence self-check alert?",
        resolution_criteria="Resolved yes if confidence-filtered tool checks alert.",
        domain="macro",
        next_review_at="2026-01-01T00:00:00Z",
    )
    high_confidence = ledger.create_question(
        title="Will tool confidence self-check skip this?",
        resolution_criteria="Resolved yes if confidence-filtered tool checks skip this.",
        domain="macro",
        next_review_at="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=low_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.35,
        rationale="Low-confidence forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=high_confidence.id,
        probability_or_distribution=0.5,
        confidence=0.85,
        rationale="High-confidence forecast.",
        as_of="2026-01-01T00:00:00Z",
    )

    checked = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "self_check",
                "domain": "macro",
                "confidence_below": 0.5,
                "now": "2026-01-10T00:00:00Z",
            }
        )
    )
    scheduled = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "schedule_review",
                "domain": "macro",
                "cadence": "1d",
                "next_run_at": "2026-01-02T00:00:00Z",
                "confidence_below": 0.5,
            }
        )
    )
    ran = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "run_scheduled_reviews",
                "now": "2026-01-10T00:00:00Z",
            }
        )
    )

    assert checked["alerts"][0]["scope_ref"] == low_confidence.id
    assert all(alert["scope_ref"] != high_confidence.id for alert in checked["alerts"])
    assert scheduled["scheduled_review"]["confidence_below"] == pytest.approx(0.5)
    scheduled_alerts = ran["scheduled_review_results"][0]["alerts"]
    assert any(alert["scope_ref"] == low_confidence.id for alert in scheduled_alerts)
    assert all(alert["scope_ref"] != high_confidence.id for alert in scheduled_alerts)


def test_forecast_ledger_tool_review_and_schedule_flag_large_delta(tmp_path):
    db_path = tmp_path / "forecasting.db"
    db = str(db_path)
    ledger = ForecastLedger(db_path)
    question = ledger.create_question(
        title="Will tool large deltas be reviewed?",
        resolution_criteria="Resolved yes if tool review flags large forecast deltas.",
        domain="macro",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.35,
        rationale="Initial forecast.",
        as_of="2026-01-01T00:00:00Z",
    )
    ledger.create_snapshot(
        question_id=question.id,
        probability_or_distribution=0.68,
        rationale="Large update.",
        as_of="2026-01-02T00:00:00Z",
    )

    reviewed = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "review",
                "stale": True,
                "large_delta_threshold": 0.25,
                "now": "2026-01-04T00:00:00Z",
            }
        )
    )
    scheduled = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "schedule_review",
                "domain": "macro",
                "cadence": "1d",
                "next_run_at": "2026-01-03T00:00:00Z",
                "large_delta_threshold": 0.25,
            }
        )
    )
    ran = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "run_scheduled_reviews",
                "now": "2026-01-04T00:00:00Z",
            }
        )
    )

    assert reviewed["review"][0]["question"]["id"] == question.id
    assert any(
        reason.startswith("large_forecast_delta:")
        for reason in reviewed["review"][0]["reasons"]
    )
    assert scheduled["scheduled_review"]["large_delta_threshold"] == pytest.approx(0.25)
    assert any(
        alert["reason"].startswith("large_forecast_delta:")
        for alert in ran["scheduled_review_results"][0]["alerts"]
    )


def test_forecast_ledger_tool_can_list_and_acknowledge_alerts(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool alert lifecycle work?",
                "resolution_criteria": "Resolved yes if alerts can be reviewed.",
            }
        )
    )
    question_id = created["question"]["id"]
    checked = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "self_check",
                "question_id": question_id,
            }
        )
    )
    alert_id = checked["alerts"][0]["id"]

    listed = json.loads(forecast_ledger_tool({"db": db, "action": "list_alerts"}))
    acknowledged = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "acknowledge_alert",
                "alert_id": alert_id,
                "acknowledged_at": "2026-01-03T00:00:00Z",
            }
        )
    )
    open_after_ack = json.loads(forecast_ledger_tool({"db": db, "action": "list_alerts"}))
    all_after_ack = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_alerts",
                "unresolved_only": False,
            }
        )
    )

    assert listed["alerts"][0]["id"] == alert_id
    assert acknowledged["alert"]["acknowledged_at"] == "2026-01-03T00:00:00Z"
    assert open_after_ack["alerts"] == []
    assert all_after_ack["alerts"][0]["id"] == alert_id


def test_forecast_ledger_tool_reviews_focused_books(tmp_path):
    db = str(tmp_path / "forecasting.db")
    low_confidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will focused election review appear?",
                "resolution_criteria": "Resolved yes if low-confidence election forecasts can be filtered.",
                "domain": "geopolitics",
                "topics": ["election"],
            }
        )
    )["question"]
    high_confidence = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will rates review stay separate?",
                "resolution_criteria": "Resolved yes if topic filters exclude this question.",
                "domain": "geopolitics",
                "topics": ["rates"],
            }
        )
    )["question"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": low_confidence["id"],
            "probability": 0.55,
            "confidence": 0.3,
            "rationale": "Low-confidence election update.",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": high_confidence["id"],
            "probability": 0.65,
            "confidence": 0.8,
            "rationale": "High-confidence rates update.",
        }
    )

    focused = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "review",
                "domain": "geopolitics",
                "topic": "election",
                "confidence_below": 0.5,
                "now": "2026-01-10T00:00:00Z",
            }
        )
    )

    assert [row["question"]["id"] for row in focused["review"]] == [low_confidence["id"]]


def test_forecast_ledger_tool_reads_calibration_and_error_memory(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool calibration memory be readable?",
                "resolution_criteria": "Resolved yes if calibration memory is readable.",
                "domain": "macro",
            }
        )
    )
    question_id = created["question"]["id"]
    forecast_ledger_tool(
        {
            "db": db,
            "action": "update_forecast",
            "question_id": question_id,
            "probability": 0.9,
            "rationale": "Overconfident macro forecast.",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "resolve",
            "question_id": question_id,
            "outcome": "no",
        }
    )
    forecast_ledger_tool(
        {
            "db": db,
            "action": "postmortem",
            "question_id": question_id,
            "summary": "The macro event did not happen.",
            "lesson": "Discount overconfident macro calls after misses.",
        }
    )

    calibration = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "calibration_summary",
                "domain": "macro",
            }
        )
    )
    profiles = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "list_domain_error_profiles",
                "domain": "macro",
            }
        )
    )

    assert calibration["calibration"]["count"] == 1
    assert calibration["calibration"]["mean_brier"] == pytest.approx(0.81)
    assert profiles["domain_error_profiles"][0]["domain"] == "macro"
    assert profiles["domain_error_profiles"][0]["sample_count"] == 1
    assert "elevated_mean_brier" in profiles["domain_error_profiles"][0]["recurring_errors"]


def test_forecast_ledger_tool_runs_and_reports_backtests(tmp_path):
    db = str(tmp_path / "forecasting.db")
    actions = set(FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"])
    assert "evidence_readiness" in actions

    run = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "run_backtest_dataset",
                "dataset": "tool-fixture",
                "cases": [
                    {
                        "title": "Will tool backtest case resolve yes?",
                        "resolution_criteria": "Resolved yes for the fixture.",
                        "as_of": "2026-01-01T00:00:00Z",
                        "probability": 0.7,
                        "outcome": "yes",
                        "baselines": [
                            {
                                "source": "fixture-market",
                                "baseline_type": "market",
                                "probability": 0.6,
                            }
                        ],
                    }
                ],
            }
        )
    )
    run_id = run["backtest_run"]["id"]
    listed = json.loads(forecast_ledger_tool({"db": db, "action": "list_backtest_runs"}))
    report = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "backtest_performance_report",
                "run_id": run_id,
            }
        )
    )
    readiness = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "evidence_readiness",
                "last": 5,
                "min_live_scores": 3,
                "min_agent_protocol_cases": 4,
            }
        )
    )

    assert listed["backtest_runs"][0]["id"] == run_id
    assert report["backtest_performance"]["case_count"] == 1
    assert report["backtest_performance"]["agent"]["mean_brier"] == pytest.approx(0.09)
    assert report["backtest_performance"]["baselines"][0]["baseline_type"] == "market"
    assert report["backtest_performance"]["baselines"][0]["mean_brier"] == pytest.approx(0.16)
    assert report["backtest_performance"]["baselines"][0]["paired_agent_wins"] == 1
    assert readiness["inspected_backtest_run_ids"] == [run_id]
    assert readiness["backtest_summaries"][0]["id"] == run_id
    assert readiness["evidence_status"]["score_counts"]["backtest"] == 1
    assert readiness["evidence_status"]["backtests"]["leakage_free_run_count"] == 1
    requirements = {
        row["id"]: row
        for row in readiness["evidence_status"]["requirements"]
    }
    assert requirements["live_scored_forecasts"]["required"] == 3
    assert requirements["agent_protocol_scored_cases"]["required"] == 4
    assert readiness["evidence_status"]["next_actions"][0]["requirement_id"] == "live_scored_forecasts"
    assert "forecast backtest <cases.json>" in readiness["evidence_status"]["next_actions"][1]["action"]


def test_forecast_ledger_tool_imports_structured_source_evidence(tmp_path, monkeypatch):
    db = str(tmp_path / "forecasting.db")
    actions = set(FORECAST_LEDGER_SCHEMA["parameters"]["properties"]["action"]["enum"])
    assert "import_source_evidence" in actions

    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will structured adapter evidence import?",
                "resolution_criteria": "Resolved yes if adapter evidence is imported through the tool.",
            }
        )
    )
    question_id = created["question"]["id"]

    def fake_pageviews(source, **kwargs):
        assert source == "en.wikipedia.org/Artificial_intelligence"
        assert kwargs["limit"] == 2
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["access"] == "desktop"
        assert kwargs["agent"] == "user"
        assert kwargs["api_base_url"] == "https://example.test/pageviews"
        return [
            WikimediaPageviewObservation(
                project="en.wikipedia.org",
                article="Artificial_intelligence",
                access="desktop",
                agent="user",
                granularity="daily",
                observation_date="2026-01-02",
                views=1234,
                published_at="2026-01-02T00:00:00Z",
                source_url="https://example.test/pageviews/en.wikipedia.org/Artificial_intelligence",
                source_name="Wikimedia Pageviews",
                entry_id="en.wikipedia.org:Artificial_intelligence:2026-01-02",
                raw={"views": 1234},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_wikimedia_pageviews", fake_pageviews)
    imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "wikipediapageviews",
                "source": "en.wikipedia.org/Artificial_intelligence",
                "limit": 2,
                "since": "2026-01-01",
                "access": "desktop",
                "agent": "user",
                "api_base_url": "https://example.test/pageviews",
                "reliability_rating": 0.8,
                "relevance_rating": 0.7,
                "snapshot_path": "adapter-snapshot.json",
            }
        )
    )

    assert imported["imported_count"] == 1
    row = imported["imported"][0]
    evidence = row["evidence"]
    assert evidence["question_id"] == question_id
    assert evidence["source_type"] == "adapter:wikipediapageviews"
    assert evidence["source_name"] == "Wikimedia Pageviews"
    assert evidence["snapshot_path"] == "adapter-snapshot.json"
    assert evidence["claim"] == "Wikimedia pageviews for Artificial_intelligence were 1234 on 2026-01-02"
    assert evidence["reliability_rating"] == pytest.approx(0.8)
    assert evidence["relevance_rating"] == pytest.approx(0.7)
    assert evidence["metadata"]["adapter"] == "wikipediapageviews"
    assert evidence["metadata"]["adapter_item"]["views"] == 1234
    assert row["adapter_item"]["entry_id"] == "en.wikipedia.org:Artificial_intelligence:2026-01-02"

    def fake_github_commits(source, **kwargs):
        assert source == "acme/desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["api_base_url"] == "https://example.test/github"
        return [
            GitHubCommit(
                repo="acme/desk",
                sha="abcdef1234567890",
                short_sha="abcdef1",
                message="Add calibrated forecast dashboard",
                author_name="Ada Analyst",
                author_login="ada",
                authored_at="2026-05-20T10:00:00Z",
                committed_at="2026-05-21T11:00:00Z",
                comments=2,
                url="https://api.github.test/repos/acme/desk/commits/abcdef1234567890",
                html_url="https://github.com/acme/desk/commit/abcdef1234567890",
                source_name="GitHub",
                entry_id="acme/desk@abcdef1234567890",
                raw={"sha": "abcdef1234567890"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_github_commits", fake_github_commits)
    github_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "githubcommits",
                "source": "acme/desk",
                "limit": 1,
                "since": "2026-01-01",
                "api_base_url": "https://example.test/github",
            }
        )
    )

    assert github_imported["imported_count"] == 1
    github_evidence = github_imported["imported"][0]["evidence"]
    assert github_evidence["source_type"] == "adapter:githubcommits"
    assert github_evidence["source_name"] == "GitHub"
    assert github_evidence["claim"] == "GitHub commit acme/desk abcdef1: Add calibrated forecast dashboard"
    assert github_evidence["published_at"] == "2026-05-21T11:00:00Z"
    assert github_evidence["metadata"]["adapter"] == "githubcommits"
    assert github_evidence["metadata"]["adapter_item"]["sha"] == "abcdef1234567890"

    def fake_githubactions(source, **kwargs):
        assert source == "acme/desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["api_base_url"] == "https://example.test/github"
        return [
            GitHubWorkflowRun(
                repo="acme/desk",
                run_id="987",
                name="CI",
                display_title="Add calibrated forecast dashboard",
                status="completed",
                conclusion="success",
                event="push",
                head_branch="main",
                head_sha="abcdef1234567890",
                short_sha="abcdef1",
                workflow_id="1234",
                workflow_url="https://api.github.test/repos/acme/desk/actions/workflows/1234",
                actor_login="ada",
                triggering_actor_login="ci-bot",
                run_started_at="2026-05-21T10:30:00Z",
                created_at="2026-05-21T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                url="https://api.github.test/repos/acme/desk/actions/runs/987",
                html_url="https://github.com/acme/desk/actions/runs/987",
                source_name="GitHub",
                entry_id="acme/desk/actions/runs/987",
                raw={"id": 987},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_github_workflow_runs", fake_githubactions)
    githubactions_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "githubactions",
                "source": "acme/desk",
                "limit": 1,
                "since": "2026-01-01",
                "api_base_url": "https://example.test/github",
            }
        )
    )

    assert githubactions_imported["imported_count"] == 1
    githubactions_evidence = githubactions_imported["imported"][0]["evidence"]
    assert githubactions_evidence["source_type"] == "adapter:githubactions"
    assert githubactions_evidence["source_name"] == "GitHub"
    assert githubactions_evidence["claim"] == "GitHub Actions run acme/desk 987: success"
    assert githubactions_evidence["published_at"] == "2026-05-21T10:30:00Z"
    assert githubactions_evidence["metadata"]["adapter"] == "githubactions"
    assert githubactions_evidence["metadata"]["adapter_item"]["run_id"] == "987"

    def fake_coingecko(source, **kwargs):
        assert source == "bitcoin"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["vs_currency"] == "usd"
        assert kwargs["api_base_url"] == "https://example.test/coingecko"
        return [
            CoinGeckoMarketSnapshot(
                coin_id="bitcoin",
                symbol="btc",
                name="Bitcoin",
                vs_currency="usd",
                current_price=109500,
                market_cap=2170000000000,
                market_cap_rank=1,
                total_volume=51200000000,
                price_change_percentage_24h=2.34,
                last_updated="2026-05-21T11:00:00Z",
                source_url="https://www.coingecko.com/en/coins/bitcoin",
                source_name="CoinGecko",
                entry_id="bitcoin:usd:2026-05-21T11:00:00Z",
                raw={"id": "bitcoin"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_coingecko_market_snapshots", fake_coingecko)
    coingecko_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "coingecko",
                "source": "bitcoin",
                "limit": 1,
                "since": "2026-01-01",
                "vs_currency": "usd",
                "api_base_url": "https://example.test/coingecko",
            }
        )
    )

    assert coingecko_imported["imported_count"] == 1
    coingecko_evidence = coingecko_imported["imported"][0]["evidence"]
    assert coingecko_evidence["source_type"] == "adapter:coingecko"
    assert coingecko_evidence["source_name"] == "CoinGecko"
    assert coingecko_evidence["claim"] == "CoinGecko bitcoin price was 109500 USD at 2026-05-21T11:00:00Z"
    assert coingecko_evidence["published_at"] == "2026-05-21T11:00:00Z"
    assert coingecko_evidence["metadata"]["adapter"] == "coingecko"
    assert coingecko_evidence["metadata"]["adapter_item"]["current_price"] == 109500

    def fake_eia(source, **kwargs):
        assert source == "PET.RWTC.M"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["api_base_url"] == "https://example.test/eia"
        return [
            EiaObservation(
                series_id="PET.RWTC.M",
                series_name="WTI crude oil spot price",
                observation_period="2026-03",
                value=72.5,
                unit="dollars per barrel",
                published_at="2026-03-01T00:00:00Z",
                source_url="https://example.test/eia?series_id=PET.RWTC.M",
                source_name="EIA",
                entry_id="PET.RWTC.M:2026-03",
                raw={"period": "2026-03", "value": "72.5"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_eia_observations", fake_eia)
    eia_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "eia",
                "source": "PET.RWTC.M",
                "limit": 1,
                "since": "2026-01-01",
                "api_base_url": "https://example.test/eia",
            }
        )
    )

    assert eia_imported["imported_count"] == 1
    eia_evidence = eia_imported["imported"][0]["evidence"]
    assert eia_evidence["source_type"] == "adapter:eia"
    assert eia_evidence["source_name"] == "EIA"
    assert eia_evidence["claim"] == "EIA PET.RWTC.M was 72.5 dollars per barrel for 2026-03"
    assert eia_evidence["published_at"] == "2026-03-01T00:00:00Z"
    assert eia_evidence["metadata"]["adapter"] == "eia"
    assert eia_evidence["metadata"]["adapter_item"]["unit"] == "dollars per barrel"

    def fake_treasury(source, **kwargs):
        assert source == "v2/accounting/od/avg_interest_rates"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["date_field"] == "record_date"
        assert kwargs["value_field"] == "avg_interest_rate_amt"
        assert kwargs["api_base_url"] == "https://example.test/treasury"
        return [
            TreasuryRecord(
                dataset="v2/accounting/od/avg_interest_rates",
                record_date="2026-04-01",
                value=4.4,
                value_field="avg_interest_rate_amt",
                value_label="Average Interest Rate",
                published_at="2026-04-01T00:00:00Z",
                source_url="https://example.test/treasury/v2/accounting/od/avg_interest_rates",
                source_name="U.S. Treasury Fiscal Data",
                entry_id="v2/accounting/od/avg_interest_rates:2026-04-01:0",
                raw={"record_date": "2026-04-01", "avg_interest_rate_amt": "4.40"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_treasury_records", fake_treasury)
    treasury_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "treasury",
                "source": "v2/accounting/od/avg_interest_rates",
                "limit": 1,
                "since": "2026-01-01",
                "date_field": "record_date",
                "value_field": "avg_interest_rate_amt",
                "api_base_url": "https://example.test/treasury",
            }
        )
    )

    assert treasury_imported["imported_count"] == 1
    treasury_evidence = treasury_imported["imported"][0]["evidence"]
    assert treasury_evidence["source_type"] == "adapter:treasury"
    assert treasury_evidence["source_name"] == "U.S. Treasury Fiscal Data"
    assert (
        treasury_evidence["claim"]
        == "Treasury v2/accounting/od/avg_interest_rates 2026-04-01: avg_interest_rate_amt=4.4"
    )
    assert treasury_evidence["published_at"] == "2026-04-01T00:00:00Z"
    assert treasury_evidence["metadata"]["adapter"] == "treasury"
    assert treasury_evidence["metadata"]["adapter_item"]["value_label"] == "Average Interest Rate"

    def fake_census(source, **kwargs):
        assert source == "2023/acs/acs5?get=NAME,B01003_001E&for=state:*"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2023-01-01"
        assert kwargs["api_base_url"] == "https://example.test/census"
        return [
            CensusRecord(
                dataset="2023/acs/acs5",
                dataset_year=2023,
                observation_date="2023-12-31",
                values={"NAME": "California", "B01003_001E": 39100000.0},
                geography={"state": "06"},
                published_at="2023-12-31T00:00:00Z",
                source_url="https://example.test/census/2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
                source_name="U.S. Census Bureau",
                entry_id="2023/acs/acs5:2023-12-31:0",
                raw={"row_index": 0},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_census_records", fake_census)
    census_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "census",
                "source": "2023/acs/acs5?get=NAME,B01003_001E&for=state:*",
                "limit": 1,
                "since": "2023-01-01",
                "api_base_url": "https://example.test/census",
            }
        )
    )

    assert census_imported["imported_count"] == 1
    census_evidence = census_imported["imported"][0]["evidence"]
    assert census_evidence["source_type"] == "adapter:census"
    assert census_evidence["source_name"] == "U.S. Census Bureau"
    assert census_evidence["claim"] == "Census 2023/acs/acs5 state=06: NAME=California, B01003_001E=39100000.0"
    assert census_evidence["published_at"] == "2023-12-31T00:00:00Z"
    assert census_evidence["metadata"]["adapter"] == "census"
    assert census_evidence["metadata"]["adapter_item"]["geography"] == {"state": "06"}

    def fake_socrata(source, **kwargs):
        assert source == "data.cdc.gov/abcd-1234?county=King"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["api_base_url"] == "https://example.test/{domain}/resource/{dataset_id}.json"
        return [
            SocrataRecord(
                domain="data.cdc.gov",
                dataset_id="abcd-1234",
                row_id="row-1",
                observation_time="2026-05-20T00:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                values={"report_date": "2026-05-20", "county": "King", "cases": "42"},
                source_url="https://data.cdc.gov/resource/abcd-1234.json?county=King",
                source_name="Socrata",
                entry_id="data.cdc.gov/abcd-1234:row-1",
                raw={"row_index": 0},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_socrata_records", fake_socrata)
    socrata_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "socrata",
                "source": "data.cdc.gov/abcd-1234?county=King",
                "limit": 1,
                "since": "2026-01-01",
                "api_base_url": "https://example.test/{domain}/resource/{dataset_id}.json",
            }
        )
    )

    assert socrata_imported["imported_count"] == 1
    socrata_evidence = socrata_imported["imported"][0]["evidence"]
    assert socrata_evidence["source_type"] == "adapter:socrata"
    assert socrata_evidence["source_name"] == "Socrata"
    assert socrata_evidence["claim"] == "Socrata row data.cdc.gov/abcd-1234 row-1"
    assert socrata_evidence["published_at"] == "2026-05-21T11:00:00Z"
    assert socrata_evidence["metadata"]["adapter"] == "socrata"
    assert socrata_evidence["metadata"]["adapter_item"]["values"]["cases"] == "42"

    def fake_ckan(source, **kwargs):
        assert source == "data.gov/energy"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-01-01"
        assert kwargs["api_base_url"] == "https://example.test/{domain}/api/3/action/package_search"
        return [
            CkanDataset(
                portal="data.gov",
                package_id="pkg-1",
                name="electricity-demand",
                title="Electricity demand",
                notes="Hourly grid demand.",
                url=None,
                organization="Energy Department",
                groups=["energy"],
                tags=["grid", "demand"],
                license_title="Creative Commons",
                metadata_created="2026-05-20T10:00:00Z",
                metadata_modified="2026-05-22T11:30:00Z",
                resources=[{"id": "res-1", "format": "CSV"}],
                source_url="https://data.gov/dataset/electricity-demand",
                source_name="CKAN:data.gov",
                entry_id="data.gov:electricity-demand",
                raw={"row_index": 0},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_ckan_datasets", fake_ckan)
    ckan_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "ckan",
                "source": "data.gov/energy",
                "limit": 1,
                "since": "2026-01-01",
                "api_base_url": "https://example.test/{domain}/api/3/action/package_search",
            }
        )
    )

    assert ckan_imported["imported_count"] == 1
    ckan_evidence = ckan_imported["imported"][0]["evidence"]
    assert ckan_evidence["source_type"] == "adapter:ckan"
    assert ckan_evidence["source_name"] == "CKAN:data.gov"
    assert ckan_evidence["claim"] == "CKAN dataset data.gov Electricity demand"
    assert ckan_evidence["published_at"] == "2026-05-22T11:30:00Z"
    assert ckan_evidence["metadata"]["adapter"] == "ckan"
    assert ckan_evidence["metadata"]["adapter_item"]["resources"][0]["format"] == "CSV"

    def fake_githubissues(source, **kwargs):
        assert source == "acme/desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["state"] == "all"
        assert kwargs["api_base_url"] == "https://example.test/github"
        return [
            GitHubIssue(
                repo="acme/desk",
                issue_number=42,
                title="Ship forecast ledger",
                state="open",
                is_pull_request=False,
                author="analyst",
                labels=["forecasting"],
                created_at="2026-05-20T10:00:00Z",
                updated_at="2026-05-21T11:00:00Z",
                closed_at=None,
                comments=2,
                url="https://api.github.test/repos/acme/desk/issues/42",
                html_url="https://github.com/acme/desk/issues/42",
                source_name="GitHub",
                entry_id="acme/desk#42",
                raw={"number": 42},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_github_issues", fake_githubissues)
    githubissues_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "githubissues",
                "source": "acme/desk",
                "limit": 1,
                "since": "2026-05-01",
                "state": "all",
                "api_base_url": "https://example.test/github",
            }
        )
    )

    assert githubissues_imported["imported_count"] == 1
    githubissues_evidence = githubissues_imported["imported"][0]["evidence"]
    assert githubissues_evidence["source_type"] == "adapter:githubissues"
    assert githubissues_evidence["source_name"] == "GitHub"
    assert githubissues_evidence["claim"] == "GitHub issue acme/desk #42: Ship forecast ledger"
    assert githubissues_evidence["published_at"] == "2026-05-21T11:00:00Z"
    assert githubissues_evidence["metadata"]["adapter"] == "githubissues"
    assert githubissues_evidence["metadata"]["adapter_item"]["labels"] == ["forecasting"]

    def fake_hackernews(source, **kwargs):
        assert source == "forecast desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/hackernews"
        return [
            HackerNewsItem(
                object_id="12345",
                title="Forecast Desk launches public beta",
                url="https://example.test/forecast-desk",
                hn_url="https://news.ycombinator.com/item?id=12345",
                author="analyst",
                created_at="2026-05-21T14:30:00Z",
                points=128,
                comments=34,
                story_id=12345,
                story_text="Public beta discussion.",
                source_name="Hacker News",
                entry_id="12345",
                raw={"objectID": "12345"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_hackernews_items", fake_hackernews)
    hackernews_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "hackernews",
                "source": "forecast desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/hackernews",
            }
        )
    )

    assert hackernews_imported["imported_count"] == 1
    hackernews_evidence = hackernews_imported["imported"][0]["evidence"]
    assert hackernews_evidence["source_type"] == "adapter:hackernews"
    assert hackernews_evidence["source_name"] == "Hacker News"
    assert hackernews_evidence["claim"] == "Hacker News: Forecast Desk launches public beta"
    assert hackernews_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert hackernews_evidence["metadata"]["adapter"] == "hackernews"
    assert hackernews_evidence["metadata"]["adapter_item"]["points"] == 128

    def fake_reddit(source, **kwargs):
        assert source == "forecast desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/reddit/search.json"
        return [
            RedditPost(
                post_id="t3_abc123",
                title="Forecast Desk launches public beta",
                subreddit="forecasting",
                author="analyst",
                url="https://example.test/forecast-desk",
                permalink="https://www.reddit.com/r/forecasting/comments/abc123/forecast_desk/",
                created_at="2026-05-21T14:30:00Z",
                score=128,
                comments=34,
                upvote_ratio=0.91,
                selftext="Public beta discussion.",
                source_name="Reddit r/forecasting",
                entry_id="t3_abc123",
                raw={"name": "t3_abc123"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_reddit_posts", fake_reddit)
    reddit_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "reddit",
                "source": "forecast desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/reddit/search.json",
            }
        )
    )

    assert reddit_imported["imported_count"] == 1
    reddit_evidence = reddit_imported["imported"][0]["evidence"]
    assert reddit_evidence["source_type"] == "adapter:reddit"
    assert reddit_evidence["source_name"] == "Reddit r/forecasting"
    assert reddit_evidence["claim"] == "Reddit: Forecast Desk launches public beta"
    assert reddit_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert reddit_evidence["metadata"]["adapter"] == "reddit"
    assert reddit_evidence["metadata"]["adapter_item"]["score"] == 128

    def fake_bluesky(source, **kwargs):
        assert source == "forecast desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/bsky/search"
        assert kwargs["sort"] == "top"
        assert kwargs["author"] == "analyst.bsky.social"
        assert kwargs["lang"] == "en"
        assert kwargs["link_domain"] == "example.test"
        assert kwargs["url_filter"] == "https://example.test/forecast-desk"
        return [
            BlueskyPost(
                post_uri="at://did:plc:abc/app.bsky.feed.post/3kforecast",
                cid="bafyforecast",
                text="Forecast Desk launches public beta",
                author_handle="analyst.bsky.social",
                author_display_name="Analyst",
                author_did="did:plc:abc",
                created_at="2026-05-21T14:30:00Z",
                indexed_at="2026-05-21T14:31:00Z",
                reply_count=4,
                repost_count=12,
                like_count=128,
                quote_count=3,
                url="https://bsky.app/profile/analyst.bsky.social/post/3kforecast",
                source_name="Bluesky @analyst.bsky.social",
                entry_id="at://did:plc:abc/app.bsky.feed.post/3kforecast",
                raw={"uri": "at://did:plc:abc/app.bsky.feed.post/3kforecast"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_bluesky_posts", fake_bluesky)
    bluesky_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "bluesky",
                "source": "forecast desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/bsky/search",
                "sort": "top",
                "author": "analyst.bsky.social",
                "lang": "en",
                "link_domain": "example.test",
                "url_filter": "https://example.test/forecast-desk",
            }
        )
    )

    assert bluesky_imported["imported_count"] == 1
    bluesky_evidence = bluesky_imported["imported"][0]["evidence"]
    assert bluesky_evidence["source_type"] == "adapter:bluesky"
    assert bluesky_evidence["source_name"] == "Bluesky @analyst.bsky.social"
    assert bluesky_evidence["claim"] == "Bluesky: Forecast Desk launches public beta"
    assert bluesky_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert bluesky_evidence["metadata"]["adapter"] == "bluesky"
    assert bluesky_evidence["metadata"]["adapter_item"]["like_count"] == 128

    def fake_mastodon(source, **kwargs):
        assert source == "mastodon.social/forecasting"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/mastodon/tag"
        assert kwargs["local"] is True
        assert kwargs["only_media"] is True
        return [
            MastodonStatus(
                status_id="110123",
                uri="https://mastodon.social/users/analyst/statuses/110123",
                url="https://mastodon.social/@analyst/110123",
                content_text="Forecast Desk launches public beta.",
                account_acct="analyst",
                account_username="analyst",
                account_display_name="Analyst",
                account_url="https://mastodon.social/@analyst",
                created_at="2026-05-21T14:30:00Z",
                replies_count=4,
                reblogs_count=12,
                favourites_count=128,
                language="en",
                visibility="public",
                tags=["forecasting"],
                card_url="https://example.test/forecast-desk",
                card_title="Forecast Desk",
                source_name="Mastodon @analyst",
                entry_id="110123",
                raw={"id": "110123"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_mastodon_statuses", fake_mastodon)
    mastodon_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "mastodon",
                "source": "mastodon.social/forecasting",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/mastodon/tag",
                "local": True,
                "only_media": True,
            }
        )
    )

    assert mastodon_imported["imported_count"] == 1
    mastodon_evidence = mastodon_imported["imported"][0]["evidence"]
    assert mastodon_evidence["source_type"] == "adapter:mastodon"
    assert mastodon_evidence["source_name"] == "Mastodon @analyst"
    assert mastodon_evidence["claim"] == "Mastodon: Forecast Desk launches public beta."
    assert mastodon_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert mastodon_evidence["metadata"]["adapter"] == "mastodon"
    assert mastodon_evidence["metadata"]["adapter_item"]["favourites_count"] == 128

    def fake_reliefweb(source, **kwargs):
        assert source == "Kenya floods"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/reliefweb/reports"
        assert kwargs["appname"] == "forecast-test"
        return [
            ReliefWebReport(
                report_id="rw_123",
                title="Flood response update",
                summary="Humanitarian partners reported new flooding impacts.",
                url="https://reliefweb.int/report/kenya/flood-response-update",
                published_at="2026-05-21T14:30:00Z",
                changed_at="2026-05-22T09:00:00Z",
                sources=["OCHA"],
                countries=["Kenya"],
                disasters=["Floods"],
                formats=["Situation Report"],
                themes=["Shelter and Non-Food Items"],
                source_name="OCHA",
                entry_id="rw_123",
                raw={"id": "rw_123"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_reliefweb_reports", fake_reliefweb)
    reliefweb_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "reliefweb",
                "source": "Kenya floods",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/reliefweb/reports",
                "appname": "forecast-test",
            }
        )
    )

    assert reliefweb_imported["imported_count"] == 1
    reliefweb_evidence = reliefweb_imported["imported"][0]["evidence"]
    assert reliefweb_evidence["source_type"] == "adapter:reliefweb"
    assert reliefweb_evidence["source_name"] == "OCHA"
    assert reliefweb_evidence["claim"] == "ReliefWeb: Flood response update"
    assert reliefweb_evidence["published_at"] == "2026-05-21T14:30:00Z"
    assert reliefweb_evidence["metadata"]["adapter"] == "reliefweb"
    assert reliefweb_evidence["metadata"]["adapter_item"]["countries"] == ["Kenya"]

    def fake_cisakev(source, **kwargs):
        assert source == "ForecastSoft"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/cisa-kev.json"
        return [
            CisaKevVulnerability(
                cve_id="CVE-2026-23456",
                vendor_project="ForecastSoft",
                product="Forecast Server",
                vulnerability_name="ForecastSoft Forecast Server Command Injection",
                short_description="A known exploited command injection vulnerability.",
                date_added="2026-05-20T00:00:00Z",
                due_date="2026-06-10T00:00:00Z",
                required_action="Apply vendor mitigations.",
                ransomware_use="Known",
                notes="Observed exploitation in the wild.",
                cwes=["CWE-77"],
                source_url="https://example.test/cisa-kev.json",
                source_name="CISA Known Exploited Vulnerabilities",
                entry_id="CVE-2026-23456",
                raw={"cveID": "CVE-2026-23456"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_cisa_kev_vulnerabilities", fake_cisakev)
    cisakev_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "cisakev",
                "source": "ForecastSoft",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/cisa-kev.json",
            }
        )
    )

    assert cisakev_imported["imported_count"] == 1
    cisakev_evidence = cisakev_imported["imported"][0]["evidence"]
    assert cisakev_evidence["source_type"] == "adapter:cisakev"
    assert cisakev_evidence["source_name"] == "CISA Known Exploited Vulnerabilities"
    assert cisakev_evidence["claim"] == "CISA KEV CVE-2026-23456: ForecastSoft Forecast Server"
    assert cisakev_evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert cisakev_evidence["metadata"]["adapter"] == "cisakev"
    assert cisakev_evidence["metadata"]["adapter_item"]["ransomware_use"] == "Known"

    def fake_stooq(source, **kwargs):
        assert source == "AAPL.US"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["interval"] == "d"
        assert kwargs["api_base_url"] == "https://example.test/stooq"
        return [
            StooqPriceObservation(
                symbol="AAPL.US",
                interval="d",
                observation_date="2026-05-22",
                open_price=197.2,
                high_price=199.0,
                low_price=196.8,
                close_price=198.4,
                volume=62000000,
                published_at="2026-05-22T00:00:00Z",
                source_url="https://example.test/stooq?s=aapl.us&i=d",
                source_name="Stooq",
                entry_id="AAPL.US:d:2026-05-22",
                raw={"Date": "2026-05-22", "Close": "198.40"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_stooq_prices", fake_stooq)
    stooq_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "stooq",
                "source": "AAPL.US",
                "limit": 1,
                "since": "2026-05-01",
                "interval": "d",
                "api_base_url": "https://example.test/stooq",
            }
        )
    )

    assert stooq_imported["imported_count"] == 1
    stooq_evidence = stooq_imported["imported"][0]["evidence"]
    assert stooq_evidence["source_type"] == "adapter:stooq"
    assert stooq_evidence["source_name"] == "Stooq"
    assert stooq_evidence["claim"] == "Stooq AAPL.US close was 198.4 on 2026-05-22"
    assert stooq_evidence["published_at"] == "2026-05-22T00:00:00Z"
    assert stooq_evidence["metadata"]["adapter"] == "stooq"
    assert stooq_evidence["metadata"]["adapter_item"]["close_price"] == 198.4

    def fake_yahoo(source, **kwargs):
        assert source == "AAPL"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01T00:00:00Z"
        assert kwargs["range_value"] == "5d"
        assert kwargs["interval"] == "1d"
        assert kwargs["api_base_url"] == "https://example.test/yahoo"
        return [
            YahooFinancePriceObservation(
                symbol="AAPL",
                interval="1d",
                observation_time="2026-05-23T00:00:00Z",
                open_price=198.0,
                high_price=200.0,
                low_price=197.5,
                close_price=199.1,
                volume=63000000,
                published_at="2026-05-23T00:00:00Z",
                currency="USD",
                exchange_name="NMS",
                source_url="https://finance.yahoo.com/quote/AAPL",
                source_name="Yahoo Finance",
                entry_id="AAPL:1d:2026-05-23T00:00:00Z",
                raw={"symbol": "AAPL", "close": 199.1},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_yahoo_finance_prices", fake_yahoo)
    yahoo_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "yahoo",
                "source": "AAPL",
                "limit": 1,
                "since": "2026-05-01T00:00:00Z",
                "range_value": "5d",
                "interval": "1d",
                "api_base_url": "https://example.test/yahoo",
            }
        )
    )

    assert yahoo_imported["imported_count"] == 1
    yahoo_evidence = yahoo_imported["imported"][0]["evidence"]
    assert yahoo_evidence["source_type"] == "adapter:yahoo"
    assert yahoo_evidence["source_name"] == "Yahoo Finance"
    assert yahoo_evidence["claim"] == "Yahoo Finance AAPL close was 199.1 USD at 2026-05-23T00:00:00Z"
    assert yahoo_evidence["published_at"] == "2026-05-23T00:00:00Z"
    assert yahoo_evidence["metadata"]["adapter"] == "yahoo"
    assert yahoo_evidence["metadata"]["adapter_item"]["close_price"] == 199.1
    assert yahoo_evidence["metadata"]["adapter_item"]["currency"] == "USD"

    def fake_clinicaltrials(source, **kwargs):
        assert source == "NCT01234567"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/clinicaltrials"
        return [
            ClinicalTrialStudy(
                nct_id="NCT01234567",
                brief_title="Test oncology trial",
                official_title="A test oncology trial",
                url="https://clinicaltrials.gov/study/NCT01234567",
                status="RECRUITING",
                phases=["PHASE2"],
                study_type="INTERVENTIONAL",
                conditions=["Lung Cancer"],
                interventions=["Drug A"],
                sponsors=["Acme Bio"],
                start_date="2026-01-01T00:00:00Z",
                primary_completion_date="2027-06-30T00:00:00Z",
                completion_date=None,
                last_update_submitted_at="2026-05-20T00:00:00Z",
                last_update_posted_at="2026-05-21T00:00:00Z",
                has_results=False,
                source_name="ClinicalTrials.gov",
                entry_id="NCT01234567",
                raw={"nctId": "NCT01234567"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_clinicaltrials_studies", fake_clinicaltrials)
    clinicaltrials_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "clinicaltrials",
                "source": "NCT01234567",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/clinicaltrials",
            }
        )
    )

    assert clinicaltrials_imported["imported_count"] == 1
    clinicaltrials_evidence = clinicaltrials_imported["imported"][0]["evidence"]
    assert clinicaltrials_evidence["source_type"] == "adapter:clinicaltrials"
    assert clinicaltrials_evidence["source_name"] == "ClinicalTrials.gov"
    assert clinicaltrials_evidence["claim"] == (
        "ClinicalTrials.gov NCT01234567: RECRUITING - Test oncology trial"
    )
    assert clinicaltrials_evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert clinicaltrials_evidence["metadata"]["adapter"] == "clinicaltrials"
    assert clinicaltrials_evidence["metadata"]["adapter_item"]["phases"] == ["PHASE2"]

    def fake_openfda(source, **kwargs):
        assert source == "BLA125514"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/openfda"
        return [
            OpenFdaDrugApplication(
                application_number="BLA125514",
                sponsor_name="ACME BIO",
                brand_names=["TESTMAB"],
                generic_names=["testimab"],
                routes=["INTRAVENOUS"],
                substances=["TESTIMAB"],
                dosage_forms=["INJECTION"],
                marketing_statuses=["Prescription"],
                latest_submission_status="AP",
                latest_submission_status_date="2026-05-21T00:00:00Z",
                latest_submission_type="ORIG",
                latest_submission_class="TYPE 1",
                url="https://www.accessdata.fda.gov/test-label.pdf",
                source_name="openFDA Drugs@FDA",
                entry_id="BLA125514",
                raw={"application_number": "BLA125514"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_openfda_drug_applications", fake_openfda)
    openfda_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "openfda",
                "source": "BLA125514",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/openfda",
            }
        )
    )

    assert openfda_imported["imported_count"] == 1
    openfda_evidence = openfda_imported["imported"][0]["evidence"]
    assert openfda_evidence["source_type"] == "adapter:openfda"
    assert openfda_evidence["source_name"] == "openFDA Drugs@FDA"
    assert openfda_evidence["claim"] == "openFDA BLA125514: AP - TESTMAB"
    assert openfda_evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert openfda_evidence["metadata"]["adapter"] == "openfda"
    assert openfda_evidence["metadata"]["adapter_item"]["brand_names"] == ["TESTMAB"]

    def fake_pubmed(source, **kwargs):
        assert source == "forecasting calibration"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/pubmed/esearch.fcgi"
        return [
            PubMedArticle(
                pmid="12345678",
                title="Calibrated biomedical forecasts",
                abstract="Forecasts need calibrated biomedical priors.",
                journal="Journal of Forecasting Medicine",
                url="https://pubmed.ncbi.nlm.nih.gov/12345678/",
                doi="10.1234/pubmed.forecast",
                published_at="2026-05-21T00:00:00Z",
                revised_at="2026-05-22T00:00:00Z",
                authors=["Ada Forecaster"],
                publication_types=["Journal Article"],
                source_name="PubMed",
                entry_id="12345678",
                raw={"pmid": "12345678"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_pubmed_articles", fake_pubmed)
    pubmed_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "pubmed",
                "source": "forecasting calibration",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/pubmed/esearch.fcgi",
            }
        )
    )

    assert pubmed_imported["imported_count"] == 1
    pubmed_evidence = pubmed_imported["imported"][0]["evidence"]
    assert pubmed_evidence["source_type"] == "adapter:pubmed"
    assert pubmed_evidence["source_name"] == "PubMed"
    assert pubmed_evidence["claim"] == "PubMed 12345678: Calibrated biomedical forecasts"
    assert pubmed_evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert pubmed_evidence["metadata"]["adapter"] == "pubmed"
    assert pubmed_evidence["metadata"]["adapter_item"]["doi"] == "10.1234/pubmed.forecast"

    def fake_crossref(source, **kwargs):
        assert source == "forecasting calibration"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/crossref/works"
        return [
            CrossrefWork(
                doi="10.1234/crossref.forecast",
                title="Calibrated DOI forecasts",
                abstract="Forecasts need DOI-indexed priors.",
                url="https://doi.org/10.1234/crossref.forecast",
                published_at="2026-05-21T00:00:00Z",
                updated_at="2026-05-22T00:00:00Z",
                authors=["Ada Forecaster"],
                subjects=["Forecasting"],
                container_title="Journal of Forecasting",
                publisher="Forecasting Society",
                work_type="journal-article",
                reference_count=12,
                cited_by_count=7,
                source_name="Journal of Forecasting",
                entry_id="10.1234/crossref.forecast",
                raw={"DOI": "10.1234/crossref.forecast"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_crossref_works", fake_crossref)
    crossref_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "crossref",
                "source": "forecasting calibration",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/crossref/works",
            }
        )
    )

    assert crossref_imported["imported_count"] == 1
    crossref_evidence = crossref_imported["imported"][0]["evidence"]
    assert crossref_evidence["source_type"] == "adapter:crossref"
    assert crossref_evidence["source_name"] == "Journal of Forecasting"
    assert crossref_evidence["claim"] == "Crossref work (10.1234/crossref.forecast): Calibrated DOI forecasts"
    assert crossref_evidence["published_at"] == "2026-05-21T00:00:00Z"
    assert crossref_evidence["metadata"]["adapter"] == "crossref"
    assert crossref_evidence["metadata"]["adapter_item"]["doi"] == "10.1234/crossref.forecast"

    def fake_pypi(source, **kwargs):
        assert source == "forecast-desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/pypi"
        return [
            PypiRelease(
                package="forecast-desk",
                version="1.2.3",
                summary="Forecasting command line tools.",
                url="https://pypi.org/project/forecast-desk/1.2.3/",
                project_url="https://pypi.org/project/forecast-desk/",
                uploaded_at="2026-05-21T11:00:00Z",
                latest_upload_at="2026-05-21T11:05:00Z",
                file_count=2,
                package_types=["bdist_wheel", "sdist"],
                python_versions=["py3", "source"],
                yanked=False,
                yanked_reason=None,
                source_name="PyPI",
                entry_id="forecast-desk:1.2.3",
                raw={"version": "1.2.3"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_pypi_releases", fake_pypi)
    pypi_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "pypi",
                "source": "forecast-desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/pypi",
            }
        )
    )

    assert pypi_imported["imported_count"] == 1
    pypi_evidence = pypi_imported["imported"][0]["evidence"]
    assert pypi_evidence["source_type"] == "adapter:pypi"
    assert pypi_evidence["source_name"] == "PyPI"
    assert pypi_evidence["claim"] == "PyPI release forecast-desk 1.2.3: Forecasting command line tools."
    assert pypi_evidence["published_at"] == "2026-05-21T11:05:00Z"
    assert pypi_evidence["metadata"]["adapter"] == "pypi"
    assert pypi_evidence["metadata"]["adapter_item"]["file_count"] == 2

    def fake_npm(source, **kwargs):
        assert source == "@forecast/desk"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-01"
        assert kwargs["api_base_url"] == "https://example.test/npm"
        return [
            NpmPackageVersion(
                package="@forecast/desk",
                version="2.0.0",
                description="Forecasting interface components.",
                url="https://www.npmjs.com/package/@forecast/desk/v/2.0.0",
                tarball_url="https://registry.npm.test/@forecast/desk/-/desk-2.0.0.tgz",
                published_at="2026-05-21T11:00:00Z",
                license="Apache-2.0",
                maintainers=["analyst"],
                keywords=["forecasting"],
                deprecated=None,
                dependency_count=2,
                source_name="npm",
                entry_id="@forecast/desk:2.0.0",
                raw={"version": "2.0.0"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_npm_package_versions", fake_npm)
    npm_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "npm",
                "source": "@forecast/desk",
                "limit": 1,
                "since": "2026-05-01",
                "api_base_url": "https://example.test/npm",
            }
        )
    )

    assert npm_imported["imported_count"] == 1
    npm_evidence = npm_imported["imported"][0]["evidence"]
    assert npm_evidence["source_type"] == "adapter:npm"
    assert npm_evidence["source_name"] == "npm"
    assert npm_evidence["claim"] == "npm package @forecast/desk 2.0.0: Forecasting interface components."
    assert npm_evidence["published_at"] == "2026-05-21T11:00:00Z"
    assert npm_evidence["metadata"]["adapter"] == "npm"
    assert npm_evidence["metadata"]["adapter_item"]["dependency_count"] == 2

    def fake_usgs(source, **kwargs):
        assert source == "minmagnitude=5"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-20"
        assert kwargs["api_base_url"] == "https://example.test/usgs"
        return [
            UsgsEarthquakeEvent(
                event_id="us7000abcd",
                title="M 5.7 - Testville",
                url="https://earthquake.usgs.gov/earthquakes/eventpage/us7000abcd",
                time="2026-05-20T00:00:00Z",
                updated_at="2026-05-20T01:00:00Z",
                magnitude=5.7,
                place="Testville",
                event_type="earthquake",
                status="reviewed",
                tsunami=0,
                significance=500,
                longitude=-122.4,
                latitude=37.7,
                depth_km=8.5,
                source_name="USGS Earthquake Catalog",
                entry_id="us7000abcd",
                raw={"id": "us7000abcd"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_usgs_earthquakes", fake_usgs)
    usgs_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "usgs",
                "source": "minmagnitude=5",
                "limit": 1,
                "since": "2026-05-20",
                "api_base_url": "https://example.test/usgs",
            }
        )
    )

    assert usgs_imported["imported_count"] == 1
    usgs_evidence = usgs_imported["imported"][0]["evidence"]
    assert usgs_evidence["source_type"] == "adapter:usgs"
    assert usgs_evidence["source_name"] == "USGS Earthquake Catalog"
    assert usgs_evidence["claim"] == "USGS earthquake M5.7: Testville"
    assert usgs_evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert usgs_evidence["metadata"]["adapter"] == "usgs"
    assert usgs_evidence["metadata"]["adapter_item"]["event_id"] == "us7000abcd"

    def fake_eonet(source, **kwargs):
        assert source == "category=wildfires&status=open"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-19"
        assert kwargs["api_base_url"] == "https://example.test/eonet"
        return [
            NasaEonetEvent(
                event_id="EONET_123",
                title="Wildfire near Test Ridge",
                description="A public hazard event.",
                url="https://eonet.gsfc.nasa.gov/api/v3/events/EONET_123",
                status="open",
                closed_at=None,
                latest_geometry_at="2026-05-20T00:00:00Z",
                categories=["Wildfires"],
                source_names=["NASA"],
                source_urls=[],
                longitude=-121.2,
                latitude=38.5,
                source_name="NASA EONET",
                entry_id="EONET_123",
                raw={"id": "EONET_123"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_nasa_eonet_events", fake_eonet)
    eonet_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "eonet",
                "source": "category=wildfires&status=open",
                "limit": 1,
                "since": "2026-05-19",
                "api_base_url": "https://example.test/eonet",
            }
        )
    )

    assert eonet_imported["imported_count"] == 1
    eonet_evidence = eonet_imported["imported"][0]["evidence"]
    assert eonet_evidence["source_type"] == "adapter:eonet"
    assert eonet_evidence["source_name"] == "NASA EONET"
    assert eonet_evidence["claim"] == "NASA EONET Wildfires: Wildfire near Test Ridge"
    assert eonet_evidence["published_at"] == "2026-05-20T00:00:00Z"
    assert eonet_evidence["metadata"]["adapter"] == "eonet"
    assert eonet_evidence["metadata"]["adapter_item"]["event_id"] == "EONET_123"

    def fake_nws(source, **kwargs):
        assert source == "area=CA&event=Flood Warning"
        assert kwargs["limit"] == 1
        assert kwargs["since"] == "2026-05-20"
        assert kwargs["api_base_url"] == "https://example.test/nws"
        return [
            NwsAlert(
                alert_id="urn:oid:alert-1",
                event="Flood Warning",
                headline="Flood Warning issued for Test County",
                description="Flooding is possible.",
                instruction="Avoid flooded roads.",
                url="https://api.weather.gov/alerts/urn:oid:alert-1",
                area_desc="Test County",
                severity="Severe",
                certainty="Likely",
                urgency="Expected",
                status="Actual",
                message_type="Alert",
                category="Met",
                response="Avoid",
                sent_at="2026-05-20T12:00:00Z",
                effective_at="2026-05-20T12:05:00Z",
                onset_at=None,
                expires_at="2026-05-20T18:00:00Z",
                ends_at=None,
                source_name="National Weather Service",
                entry_id="urn:oid:alert-1",
                raw={"id": "urn:oid:alert-1"},
            )
        ]

    monkeypatch.setattr("tools.forecasting_tool.load_nws_alerts", fake_nws)
    nws_imported = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "import_source_evidence",
                "question_id": question_id,
                "source_type": "nws",
                "source": "area=CA&event=Flood Warning",
                "limit": 1,
                "since": "2026-05-20",
                "api_base_url": "https://example.test/nws",
            }
        )
    )

    assert nws_imported["imported_count"] == 1
    nws_evidence = nws_imported["imported"][0]["evidence"]
    assert nws_evidence["source_type"] == "adapter:nws"
    assert nws_evidence["source_name"] == "National Weather Service"
    assert nws_evidence["claim"] == "NWS Flood Warning: Flood Warning issued for Test County"
    assert nws_evidence["published_at"] == "2026-05-20T12:00:00Z"
    assert nws_evidence["metadata"]["adapter"] == "nws"
    assert nws_evidence["metadata"]["adapter_item"]["alert_id"] == "urn:oid:alert-1"


def test_forecast_ledger_tool_records_reference_classes_and_model_runs(tmp_path):
    db = str(tmp_path / "forecasting.db")
    created = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "create_question",
                "title": "Will tool base rates work?",
                "resolution_criteria": "Resolved yes if tool base rates are recorded.",
            }
        )
    )
    question_id = created["question"]["id"]

    reference = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "add_reference_class",
                "question_id": question_id,
                "name": "Similar cases",
                "inclusion_criteria": "Same domain and horizon.",
                "base_rate": 0.42,
            }
        )
    )
    model = json.loads(
        forecast_ledger_tool(
            {
                "db": db,
                "action": "record_model_run",
                "question_id": question_id,
                "model_type": "bayesian_update",
                "inputs": {"prior": 0.42},
                "output": {"posterior": 0.55},
            }
        )
    )

    ledger = ForecastLedger(db)
    assert reference["reference_class"]["base_rate"] == 0.42
    assert reference["model_run"]["model_type"] == "base_rate"
    assert model["model_run"]["output"]["posterior"] == 0.55
    assert len(ledger.list_model_runs(question_id)) == 2
