"""Catalog selection operations shared by setup, CLI and connected TUI clients.

Presets are explicit, additive edits. Reading a profile never enrolls it in new
defaults, and catalog upgrades never restore series the user chose to remove.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import JsonValue

from forecasting.marketdata.catalog import DataCatalog, load_catalog
from protocol.data_desk import DeskCustomSeries as DeskCustomSeries
from protocol.data_desk import DeskEdit as DeskEdit
from protocol.data_desk import DeskPatch as DeskPatch
from protocol.data_desk import DeskPreview as DeskPreview
from protocol.data_desk import DeskSavedEvent as DeskSavedEvent
from protocol.data_desk import DeskSelection as DeskSelection
from superforecasting_agent.storage.market_selection import MarketSelectionStore


def _strings(value: JsonValue) -> list[str]:
    return (
        [item for item in value if isinstance(item, str)]
        if isinstance(value, list)
        else []
    )


def _objects(value: JsonValue) -> list[dict[str, JsonValue]]:
    return (
        [item for item in value if isinstance(item, dict)]
        if isinstance(value, list)
        else []
    )


def _text(value: JsonValue) -> str:
    return value if isinstance(value, str) else ""


def _legacy_series(value: JsonValue) -> list[DeskCustomSeries]:
    result = []
    for item in _objects(value):
        provider, symbol = item.get("provider"), item.get("symbol")
        if (
            not isinstance(provider, str)
            or not provider
            or not isinstance(symbol, str)
            or not symbol
        ):
            continue
        fields = {name: _text(item.get(name)) for name in ("name", "category", "unit")}
        result.append(
            DeskCustomSeries(
                provider=provider,
                symbol=symbol,
                name=fields["name"] or symbol,
                category=fields["category"],
                unit=fields["unit"],
                line=_text(item.get("line")) or None,
            )
        )
    return result


class DataDesk:
    def __init__(self, home: Path, *, catalog: DataCatalog | None = None) -> None:
        self.store = MarketSelectionStore(home)
        self.catalog = catalog if catalog is not None else load_catalog()

    def _selection(
        self, raw: dict[str, JsonValue] | None, revision: str
    ) -> DeskSelection:
        data = raw or {}
        if "selectionVersion" in data and (
            type(data["selectionVersion"]) is not int or data["selectionVersion"] != 1
        ):
            raise ValueError(
                "Unsupported markets.json selection version; upgrade the application"
            )
        categories = _strings(data.get("categories"))
        providers = _strings(data.get("providers"))
        if "seriesIds" in data:
            if not isinstance(data["seriesIds"], list) or any(
                not isinstance(item, str) for item in data["seriesIds"]
            ):
                raise ValueError("markets.json seriesIds must be a list of strings")
            ids = _strings(data["seriesIds"])
        else:
            # Legacy category names are retained as aliases on the shared catalog.
            selected_categories = {
                category.id
                for category in self.catalog.categories
                if category.id in categories
                or category.name in categories
                or set(category.aliases).intersection(categories)
            }
            legacy = next(
                (preset for preset in self.catalog.presets if preset.id == "legacy"),
                None,
            )
            legacy_ids = set(legacy.series_ids) if legacy else set()
            ids = [
                entry.id
                for entry in self.catalog.series
                if entry.id in legacy_ids
                and entry.provider in providers
                and entry.category in selected_categories
            ]
        ids = list(dict.fromkeys(ids))
        custom, watchlist = (
            _objects(data.get("custom")),
            _objects(data.get("watchlist")),
        )
        saved = _objects(data.get("pmSaved"))
        state: Literal["unconfigured", "empty", "custom", "preset"] = "unconfigured"
        if raw is not None:
            state = "custom" if ids or custom or watchlist or saved else "empty"
            if state == "custom" and data.get("setupState") == "preset":
                state = "preset"
        return DeskSelection(
            revision=revision,
            state=state,
            series_ids=ids,
            categories=categories,
            providers=providers,
            custom=_legacy_series(data.get("custom")),
            watchlist=_legacy_series(data.get("watchlist")),
            pm_saved=[
                DeskSavedEvent.model_validate(item)
                for item in saved
                if isinstance(item.get("event_id"), str)
                and item.get("event_id")
                and isinstance(item.get("venue"), str)
                and item.get("venue")
            ],
            server_side=_strings(data["serverSide"]) if "serverSide" in data else None,
            home_region=_text(data.get("homeRegion")) or None,
            weather_locations=_strings(data["weatherLocations"])
            if "weatherLocations" in data
            else None,
        )

    def selection(self) -> DeskSelection:
        raw, revision = self.store.read()
        return self._selection(raw, revision)

    def remember_events(
        self, add: list[DeskSavedEvent], remove: list[DeskSavedEvent]
    ) -> DeskSelection:
        """Merge event identities under the lock without replacing desk settings."""
        removing = {(item.venue, item.event_id) for item in remove}
        if removing.intersection((item.venue, item.event_id) for item in add):
            raise ValueError("An event cannot be added and removed together")

        def mutate(raw: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
            current = self._selection(raw, self.store.revision(raw))
            events = {
                (item.venue, item.event_id): item.model_dump(mode="json")
                for item in current.pm_saved
                if (item.venue, item.event_id) not in removing
            }
            for stored in _objects((raw or {}).get("pmSaved")):
                venue, event_id = stored.get("venue"), stored.get("event_id")
                if not isinstance(venue, str) or not isinstance(event_id, str):
                    continue
                key = (venue, event_id)
                if key in events:
                    events[key] = stored
            for item in add:
                events.setdefault(
                    (item.venue, item.event_id), item.model_dump(mode="json")
                )
            updated = dict(raw or {})
            updated["pmSaved"] = list(events.values())[-100:]
            return updated

        raw, revision = self.store.update(mutate, expected_revision=None)
        return self._selection(raw, revision)

    def connect(self, provider_id: str, capture: Callable[[str, str], str]) -> bool:
        """Capture through the caller's secret prompt and persist on this backend."""
        from forecasting.api_keys import set_api_key

        provider = next(
            (p for p in self.catalog.providers if p.id == provider_id), None
        )
        if provider is None or not provider.key_env:
            raise ValueError("This provider does not have a credential slot")
        value = capture(provider.key_env, f"API key for {provider.name}")
        if not value:
            return False
        if "\n" in value or "\r" in value:
            raise ValueError("An API key must be a single line")
        set_api_key(provider.key_env, value, env_path=self.store.home / ".env")
        return True

    def update(self, patch: DeskPatch, *, expected_revision: str) -> DeskSelection:
        aliases = {"pm_saved": "pmSaved", "server_side": "serverSide"}

        def mutate(raw: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
            self._selection(raw, expected_revision)
            updated = dict(raw or {})
            for key, value in patch.model_dump(mode="json", exclude_unset=True).items():
                if value is None and key != "server_side":
                    raise ValueError(f"{key} must be a list")
                target = aliases.get(key, key)
                if key == "server_side" and value is None:
                    updated.pop(target, None)
                else:
                    updated[target] = value
            return updated

        raw, revision = self.store.update(mutate, expected_revision=expected_revision)
        return self._selection(raw, revision)

    def _preview(
        self, raw: dict[str, JsonValue] | None, revision: str, edit: DeskEdit
    ) -> DeskPreview:
        if edit.catalog_revision != self.catalog.revision:
            raise ValueError(
                "The catalog changed. Refresh it before applying selections."
            )
        selection = self._selection(raw, revision)
        requested = set(edit.add)
        # Live discovery results are custom display series, never qualified
        # catalog/settlement bindings. Merge them under the same revision lock.
        custom = {(r.provider, r.symbol): r for r in selection.custom}
        custom_added: list[str] = []
        custom_removed: list[str] = []
        custom_existing: list[str] = []
        add_keys = {(r.provider, r.symbol) for r in edit.custom_add}
        remove_keys = {(r.provider, r.symbol) for r in edit.custom_remove}
        if add_keys & remove_keys:
            raise ValueError("A custom series cannot be added and removed together")
        if edit.start_empty and (add_keys or remove_keys):
            raise ValueError("Start empty cannot be combined with custom changes")
        supported = {
            "yahoo",
            "fred",
            "coingecko",
            "worldbank",
            "imf",
            "frankfurter",
            "stooq",
            "bls",
            "bea",
        }
        for item in edit.custom_add:
            if (
                item.provider not in supported
                or not item.symbol.strip()
                or len(item.symbol) > 240
            ):
                raise ValueError("Unsupported custom data identity")
            key = (item.provider, item.symbol)
            identity = f"custom:{item.provider}:{item.symbol}"
            if key in custom:
                custom_existing.append(identity)
            else:
                custom[key] = item
                custom_added.append(identity)
        for key in remove_keys:
            if key in custom:
                del custom[key]
                custom_removed.append(f"custom:{key[0]}:{key[1]}")
        weather_filter = (
            edit.weather_locations
            if edit.weather_locations is not None
            else selection.weather_locations
        )
        if edit.home_region is not None and edit.home_region not in {
            region.id for region in self.catalog.regions
        }:
            raise ValueError("Unknown home region")
        known_locations = {
            series.location.name for series in self.catalog.series if series.location
        }
        if (
            edit.weather_locations is not None
            and set(edit.weather_locations) - known_locations
        ):
            raise ValueError("Choose a weather location from the catalog")
        if edit.preset_id:
            preset = next(
                (p for p in self.catalog.presets if p.id == edit.preset_id), None
            )
            if preset is None:
                raise ValueError(f"Unknown starter set: {edit.preset_id}")
            weather_categories = {
                category.id
                for category in self.catalog.categories
                if category.group == "Weather and environment"
            }
            home_region = (
                edit.home_region
                if edit.home_region is not None
                else selection.home_region
            )
            region = next(
                (item for item in self.catalog.regions if item.id == home_region), None
            )
            home_regions = {home_region, *(region.members if region else ())}
            for series in self.catalog.series:
                if series.id not in preset.series_ids:
                    continue
                if weather_filter is not None:
                    if not weather_filter and series.category in weather_categories:
                        continue
                    if series.location and series.location.name not in weather_filter:
                        continue
                    if (
                        series.kind == "event"
                        and series.category in weather_categories
                        and home_region
                        and series.region not in home_regions
                    ):
                        continue
                requested.add(series.id)
        known = {entry.id for entry in self.catalog.series}
        if requested - known:
            raise ValueError("Unknown series: " + ", ".join(sorted(requested - known)))
        if requested.intersection(edit.remove):
            raise ValueError("A series cannot be added and removed in the same edit")
        if edit.start_empty and (requested or edit.remove):
            raise ValueError("Start empty cannot be combined with selection changes")
        if edit.start_empty and selection.state not in {"unconfigured", "empty"}:
            raise ValueError("Start empty cannot erase an existing data desk")
        existing = set(selection.series_ids)
        added = sorted(requested - existing)
        removed = sorted(set(edit.remove) & existing)
        ids = [item for item in selection.series_ids if item not in removed] + added
        providers = {
            entry.provider for entry in self.catalog.series if entry.id in added
        }
        providers.update(item.provider for item in edit.custom_add)
        credentials = sorted(
            p.id
            for p in self.catalog.providers
            if p.id in providers and p.auth == "required"
        )
        state: Literal["unconfigured", "empty", "custom", "preset"] = "empty"
        if ids or custom or selection.watchlist or selection.pm_saved:
            state = "preset" if edit.preset_id else "custom"
            if (
                not added
                and not removed
                and not custom_added
                and not custom_removed
                and selection.state != "unconfigured"
            ):
                state = selection.state
        return DeskPreview(
            revision=revision,
            catalog_revision=self.catalog.revision,
            added=added + custom_added,
            removed=removed + custom_removed,
            already_selected=sorted(requested & existing) + custom_existing,
            credential_providers=credentials,
            selection=selection.model_copy(
                update={
                    "series_ids": ids,
                    "custom": list(custom.values()),
                    "state": state,
                    "home_region": edit.home_region
                    if edit.home_region is not None
                    else selection.home_region,
                    "weather_locations": list(dict.fromkeys(edit.weather_locations))
                    if edit.weather_locations is not None
                    else selection.weather_locations,
                }
            ),
        )

    def preview(self, edit: DeskEdit) -> DeskPreview:
        raw, revision = self.store.read()
        return self._preview(raw, revision, edit)

    def apply(self, edit: DeskEdit, *, expected_revision: str) -> DeskSelection:
        def mutate(raw: dict[str, JsonValue] | None) -> dict[str, JsonValue]:
            preview = self._preview(raw, expected_revision, edit)
            # Preserve all legacy and unknown fields. Do not rebuild the file
            # from the UI's narrower model (which previously lost pmSaved).
            updated = dict(raw or {})
            updated["selectionVersion"] = 1
            updated["seriesIds"] = list(preview.selection.series_ids)
            updated["setupState"] = preview.selection.state
            if edit.custom_add or edit.custom_remove:
                # Keep unknown metadata on untouched legacy custom rows.
                prior = {
                    (r.get("provider"), r.get("symbol")): r
                    for r in _objects(updated.get("custom"))
                    if isinstance(r.get("provider"), str)
                    and isinstance(r.get("symbol"), str)
                }
                updated["custom"] = [
                    prior.get((r.provider, r.symbol), r.model_dump(mode="json"))
                    for r in preview.selection.custom
                ]
            if edit.home_region is not None:
                updated["homeRegion"] = edit.home_region
            if edit.weather_locations is not None:
                updated["weatherLocations"] = list(
                    dict.fromkeys(edit.weather_locations)
                )
            if edit.preset_id:
                preset = next(p for p in self.catalog.presets if p.id == edit.preset_id)
                applied = (
                    dict(updated["appliedPresets"])
                    if isinstance(updated.get("appliedPresets"), dict)
                    else {}
                )
                applied[preset.id] = preset.version
                updated["appliedPresets"] = applied
            return updated

        raw, revision = self.store.update(mutate, expected_revision=expected_revision)
        return self._selection(raw, revision)
