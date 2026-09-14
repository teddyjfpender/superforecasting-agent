"""Discovery is a bounded view of selected tools, never a permission grant."""

import pytest

from superforecasting_agent.tooling.disclosure import BRIDGE_NAMES, ToolCatalog


def definition(name, description="Read weather observations", schema=None):
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema
            or {
                "type": "object",
                "properties": {"days": {"type": "integer", "minimum": 1}},
                "required": ["days"],
                "additionalProperties": False,
            },
        },
    }


def test_core_forecasts_and_clarify_remain_direct_and_optional_is_discoverable():
    tools = [
        definition(name) for name in ["forecast_ledger", "clarify", "mcp_weather_read"]
    ]
    catalog = ToolCatalog.selected(tools)
    wire = catalog.wire_tools()
    assert {t["function"]["name"] for t in wire} == {
        "forecast_ledger",
        "clarify",
        *BRIDGE_NAMES,
    }
    assert (
        catalog.search(["weather observations"])[0]["matches"][0]["name"]
        == "mcp_weather_read"
    )
    assert catalog.describe(["mcp_weather_read"])[0]["parameters"]["required"] == [
        "days"
    ]
    assert tools[-1]["function"]["name"] == "mcp_weather_read"


def test_nonexistent_tool_hunt_does_not_match_incidental_common_words():
    catalog = ToolCatalog.selected([definition("mcp_weather_read")])
    assert (
        catalog.search([
            "Find a tool to teleport quantum cargo across seven galaxies with weather control"
        ])[0]["matches"]
        == []
    )


@pytest.mark.parametrize(
    "requests",
    [
        [{"name": "mcp_weather_read", "arguments": {"days": "2"}}],
        [{"name": "mcp_weather_read", "arguments": {"days": True}}],
        [{"name": "mcp_weather_read", "arguments": {"days": 0}}],
        [{"name": "mcp_weather_read", "arguments": {"days": 1, "unknown": 2}}],
        [{"name": "tool_call", "arguments": {}}],
        [{"name": "disabled_tool", "arguments": {}}],
    ],
)
def test_calls_reject_invalid_types_bounds_extra_fields_and_unselected_tools(requests):
    with pytest.raises(ValueError):
        ToolCatalog.selected([definition("mcp_weather_read")]).calls(requests)


def test_schema_validation_never_fetches_external_references(monkeypatch):
    import urllib.request

    monkeypatch.setattr(
        urllib.request, "urlopen", lambda *a, **k: pytest.fail("External schema fetch")
    )
    tool = definition(
        "mcp_weather_read", schema={"$ref": "https://example.org/schema.json"}
    )
    with pytest.raises(ValueError, match="resolved locally"):
        ToolCatalog.selected([tool]).calls([
            {"name": "mcp_weather_read", "arguments": {}}
        ])


def test_schema_references_local_to_tool_are_supported():
    tool = definition(
        "mcp_weather_read",
        schema={
            "type": "object",
            "$defs": {"count": {"type": "integer", "minimum": 1}},
            "properties": {"days": {"$ref": "#/$defs/count"}},
            "required": ["days"],
        },
    )
    assert ToolCatalog.selected([tool]).calls([
        {"name": "mcp_weather_read", "arguments": {"days": 3}}
    ]) == [("mcp_weather_read", {"days": 3})]


def test_catalog_isolation_and_live_schema_changes():
    tools = [definition("mcp_weather_read")]
    old = ToolCatalog.selected(tools)
    tools[0]["function"]["parameters"]["properties"]["days"]["minimum"] = 4
    assert old.calls([{"name": "mcp_weather_read", "arguments": {"days": 2}}])
    with pytest.raises(ValueError):
        ToolCatalog.selected(tools).calls([
            {"name": "mcp_weather_read", "arguments": {"days": 2}}
        ])
    with pytest.raises(ValueError):
        ToolCatalog.selected([definition("other")]).describe(["mcp_weather_read"])


def test_search_stems_words_and_preserves_non_ascii_terms():
    catalog = ToolCatalog.selected([
        definition("optional_running", description="Running analysis"),
        definition("optional_weather", description="天气预报"),
    ])
    results = catalog.search(["run analyses", "天气预报"])
    assert results[0]["matches"][0]["name"] == "optional_running"
    assert results[1]["matches"][0]["name"] == "optional_weather"
