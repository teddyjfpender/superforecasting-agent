"""Selection behavior across fresh setup, migration, concurrency and retries."""

import json

import pytest

from forecasting.marketdata.catalog import load_catalog
from superforecasting_agent.application.data_desk import DataDesk, DeskEdit
from superforecasting_agent.storage.market_selection import SelectionConflict


def test_explicit_empty_survives_restart(tmp_path):
    desk = DataDesk(tmp_path)
    initial = desk.selection()
    assert initial.state == "unconfigured"
    edit = DeskEdit(catalog_revision=desk.catalog.revision, start_empty=True)
    result = desk.apply(edit, expected_revision=initial.revision)
    assert result.state == "empty"
    assert DataDesk(tmp_path).selection() == result
    assert desk.apply(edit, expected_revision=initial.revision) == result


def test_additive_preset_preserves_all_profile_fields_and_retries(tmp_path):
    original = {
        "providers": [],
        "categories": [],
        "custom": [{"symbol": "CUSTOM", "provider": "yahoo"}],
        "watchlist": [{"symbol": "WATCH", "provider": "yahoo"}],
        "pmSaved": [{"event_id": "e", "venue": "polymarket"}],
        "serverSide": ["fred"],
        "futureExtension": {"keep": True},
    }
    (tmp_path / "markets.json").write_text(json.dumps(original))
    desk = DataDesk(tmp_path)
    preset = desk.catalog.presets[0]
    edit = DeskEdit(catalog_revision=desk.catalog.revision, preset_id=preset.id)
    preview = desk.preview(edit)
    assert (tmp_path / "markets.json").read_text() == json.dumps(original)
    result = desk.apply(edit, expected_revision=preview.revision)
    stored = json.loads((tmp_path / "markets.json").read_text())
    assert all(stored[key] == value for key, value in original.items())
    assert set(result.series_ids) == set(preset.series_ids)
    assert desk.apply(edit, expected_revision=preview.revision) == result
    assert desk.preview(edit).added == []


def test_stale_different_edits_fail_without_losing_first_edit(tmp_path):
    first, second = DataDesk(tmp_path), DataDesk(tmp_path)
    revision = first.selection().revision
    ids = [s.id for s in first.catalog.series[:2]]
    result = first.apply(
        DeskEdit(catalog_revision=first.catalog.revision, add=[ids[0]]),
        expected_revision=revision,
    )
    with pytest.raises(SelectionConflict):
        second.apply(
            DeskEdit(catalog_revision=second.catalog.revision, add=[ids[1]]),
            expected_revision=revision,
        )
    assert first.selection() == result


def test_empty_never_erases_populated_desk(tmp_path):
    desk = DataDesk(tmp_path)
    initial = desk.selection()
    result = desk.apply(
        DeskEdit(
            catalog_revision=desk.catalog.revision, add=[desk.catalog.series[0].id]
        ),
        expected_revision=initial.revision,
    )
    with pytest.raises(ValueError, match="cannot erase"):
        desk.apply(
            DeskEdit(catalog_revision=desk.catalog.revision, start_empty=True),
            expected_revision=result.revision,
        )
    assert desk.selection() == result


@pytest.mark.parametrize(
    "contents", ["{oops", "[]", '{"seriesIds":false}', '{"selectionVersion":2}']
)
def test_damaged_or_future_profile_is_not_replaced(tmp_path, contents):
    path = tmp_path / "markets.json"
    path.write_text(contents)
    with pytest.raises(ValueError):
        DataDesk(tmp_path).selection()
    assert path.read_text() == contents


def test_removals_are_not_repopulated_by_catalog_reads(tmp_path):
    desk = DataDesk(tmp_path)
    preset = desk.catalog.presets[0]
    result = desk.apply(
        DeskEdit(catalog_revision=desk.catalog.revision, preset_id=preset.id),
        expected_revision=desk.selection().revision,
    )
    removed = preset.series_ids[0]
    result = desk.apply(
        DeskEdit(catalog_revision=desk.catalog.revision, remove=[removed]),
        expected_revision=result.revision,
    )
    assert removed not in DataDesk(tmp_path).selection().series_ids
    assert result.state == "custom"


def test_catalog_snapshot_is_detached():
    catalog = load_catalog()
    catalog.series[0].dimensions["should-not-leak"] = "changed"
    assert "should-not-leak" not in load_catalog().series[0].dimensions


def test_weather_preferences_preview_and_apply_agree(tmp_path):
    desk = DataDesk(tmp_path)
    edit = DeskEdit(
        catalog_revision=desk.catalog.revision,
        preset_id="global",
        home_region="europe",
        weather_locations=[],
    )
    preview = desk.preview(edit)
    assert preview.selection.home_region == "europe"
    assert preview.selection.weather_locations == []
    assert all(
        not entry.location for entry in desk.catalog.series if entry.id in preview.added
    )
    result = desk.apply(edit, expected_revision=preview.revision)
    assert result.weather_locations == []
    assert result.home_region == "europe"
    assert (
        desk.preview(
            DeskEdit(catalog_revision=desk.catalog.revision, preset_id="global")
        ).added
        == []
    )


def test_saved_event_edits_merge_identities_without_replacing_settings(tmp_path):
    from superforecasting_agent.application.data_desk import DeskSavedEvent

    path = tmp_path / "markets.json"
    path.write_text(
        json.dumps({
            "future": "preserved",
            "pmSaved": [{"venue": "kalshi", "event_id": "same", "extra": "keep"}],
        })
    )
    desk = DataDesk(tmp_path)
    event = DeskSavedEvent(venue="polymarket", event_id="same")
    result = desk.remember_events([event], [])
    assert len(result.pm_saved) == 2
    assert desk.remember_events([event], []) == result
    stored = json.loads(path.read_text())
    assert stored["future"] == "preserved" and stored["pmSaved"][0]["extra"] == "keep"
    result = desk.remember_events([], [event])
    assert [e.venue for e in result.pm_saved] == ["kalshi"]


@pytest.mark.parametrize(
    "contents", ['{"seriesIds":[],"seriesIds":["hidden"]}', '{"future":NaN}']
)
def test_ambiguous_json_is_not_overwritten(tmp_path, contents):
    path = tmp_path / "markets.json"
    path.write_text(contents)
    with pytest.raises(ValueError):
        DataDesk(tmp_path).selection()
    assert path.read_text() == contents


def test_legacy_category_selection_does_not_enroll_new_catalog_entries(tmp_path):
    from forecasting.marketdata.catalog import DataSeries

    catalog = load_catalog()
    original = catalog.series[0]
    added = original.model_copy(update={"id": "new-after-legacy", "symbol": "NEW"})
    catalog = catalog.model_copy(update={"series": (*catalog.series, added)})
    category = next(c for c in catalog.categories if c.id == original.category)
    (tmp_path / "markets.json").write_text(
        json.dumps({"providers": [original.provider], "categories": [category.name]})
    )
    result = DataDesk(tmp_path, catalog=catalog).selection()
    assert original.id in result.series_ids
    assert added.id not in result.series_ids


def test_country_discovery_is_shared_across_provider_code_conventions():
    catalog = load_catalog()
    brazil = catalog.find_series(country="BRA")
    assert {"worldbank", "bcb", "ibge", "openmeteo"} <= {
        item.provider for item in brazil
    }
    assert {item.country for item in brazil} == {"BRA"}
    assert any(item.provider == "openmeteo" for item in catalog.find_series("Brazil"))


def test_secret_prompt_reconnect_preserves_backend_ownership_and_consumes_once(
    tmp_path, monkeypatch
):
    import threading
    from tui_gateway.server_requests import ServerRequests
    from forecasting.api_keys import get_api_key

    monkeypatch.delenv("FRED_API_KEY", raising=False)

    class Transport:
        def __init__(self):
            self.frames = []
            self.sent = threading.Event()

        def write(self, frame):
            self.frames.append(frame)
            self.sent.set()
            return True

    first, second = Transport(), Transport()
    requests = ServerRequests()
    desk = DataDesk(tmp_path)
    result = []

    def capture(slot, prompt):
        response = requests.request(
            "desk", "secret", {"env_var": slot, "prompt": prompt}, first, timeout=5
        )
        return response.get("value", "") if response else ""

    thread = threading.Thread(
        target=lambda: result.append(desk.connect("fred", capture))
    )
    thread.start()
    try:
        assert first.sent.wait(2)
        frame = first.frames[0]
        assert requests.resume("desk", second) == [frame]
        reply = {
            "jsonrpc": "2.0",
            "id": frame["id"],
            "result": {"value": "fixture-secret"},
        }
        assert not requests.respond(reply, first)
        assert requests.respond(reply, second)
        assert not requests.respond(reply, second)
    finally:
        thread.join(2)
        requests.cancel_session(None, "test cleanup")
        thread.join(2)
    assert not thread.is_alive() and result == [True]
    assert "FRED_API_KEY=fixture-secret" in (tmp_path / ".env").read_text()
    assert get_api_key("fred") == "fixture-secret"
    assert not (tmp_path / "markets.json").exists()
    assert requests.resume("desk", second) == []


def test_cancelled_secret_prompt_does_not_write_credentials(tmp_path):
    desk = DataDesk(tmp_path)
    assert not desk.connect("fred", lambda slot, prompt: "")
    assert not (tmp_path / ".env").exists()
