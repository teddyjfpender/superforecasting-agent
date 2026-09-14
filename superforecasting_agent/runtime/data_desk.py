"""Thin setup and command adapters for the shared global data desk."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from superforecasting_agent.application.data_desk import DataDesk, DeskEdit
from superforecasting_agent.constants import get_agent_home


def setup_data_desk(home: Path) -> None:
    from superforecasting_agent.runtime.setup import (
        print_info,
        prompt_checklist,
        prompt_choice,
    )

    desk = DataDesk(Path(home))
    if desk.selection().state != "unconfigured":
        return
    preset = next(preset for preset in desk.catalog.presets if preset.id == "global")
    print_info(
        f"Global starter set: {len(preset.series_ids)} series across markets, country indicators and weather."
    )
    print_info(
        "Data loads progressively in Markets. Weather API free access is for non-commercial use."
    )
    choice = prompt_choice(
        "Start your data desk",
        [
            "Global starter set — recommended",
            "Start empty — browse or load the starter set later",
        ],
        0,
    )
    edit = DeskEdit(
        catalog_revision=desk.catalog.revision,
        preset_id="global" if choice == 0 else None,
        start_empty=choice != 0,
    )
    if (
        choice == 0
        and prompt_choice(
            "Personalize the starter set?",
            [
                "Use the global defaults",
                "Choose a home region and weather coverage",
            ],
            0,
        )
        == 1
    ):
        regions = [region for region in desk.catalog.regions if region.id != "global"]
        chosen = regions[
            prompt_choice("Home region", [region.name for region in regions], 0)
        ]
        weather = prompt_choice(
            "Weather forecasts",
            [
                "Global locations",
                "Locations in my home region",
                "Leave weather out for now",
            ],
            0,
        )
        locations = None if weather == 0 else []
        if weather == 1:
            allowed = {chosen.id, *chosen.members}
            locations = sorted({
                series.location.name
                for series in desk.catalog.series
                if series.location and series.region in allowed
            })
        edit = edit.model_copy(
            update={"home_region": chosen.id, "weather_locations": locations}
        )
    preview = desk.preview(edit)
    if choice == 0:
        print_info(
            f"{len(preview.added)} series will be added. No forecasts or probabilities are created."
        )
        review = prompt_choice(
            "Apply this collection?",
            [
                "Apply starter set",
                "Review and customize individual series",
                "Start empty instead",
            ],
            0,
        )
        if review == 1:
            candidates = [
                entry for entry in desk.catalog.series if entry.id in preview.added
            ]
            chosen = prompt_checklist(
                "Starter set — select data to include",
                [
                    f"{entry.name} · {entry.country or entry.region} · {entry.kind}"
                    for entry in candidates
                ],
                list(range(len(candidates))),
            )
            edit = edit.model_copy(
                update={
                    "preset_id": None,
                    "add": [candidates[index].id for index in chosen],
                }
            )
        elif review == 2:
            edit = DeskEdit(catalog_revision=desk.catalog.revision, start_empty=True)
        preview = desk.preview(edit)
    desk.apply(edit, expected_revision=preview.revision)


def register_cli(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "data", help="Browse and configure the global data desk"
    )
    commands = parser.add_subparsers(dest="data_command", required=True)
    catalog = commands.add_parser("catalog", help="Browse available measurements")
    for field in ("query", "category", "region", "provider", "country", "kind"):
        catalog.add_argument("--" + field, default="")
    commands.add_parser("selection", help="Show the active backend selection")
    preset = commands.add_parser(
        "preset", help="Preview a starter set; --apply adds missing series"
    )
    preset.add_argument("preset_id", nargs="?", default="global")
    preset.add_argument("--apply", action="store_true")
    preset.add_argument("--home-region")
    preset.add_argument(
        "--weather-location",
        action="append",
        help="Catalog location name; repeat to choose several",
    )
    preset.add_argument("--no-weather", action="store_true")
    empty = commands.add_parser("empty", help="Start an unconfigured desk empty")
    empty.add_argument("--apply", action="store_true")
    select = commands.add_parser(
        "select", help="Preview individual series additions or removals"
    )
    select.add_argument("series", nargs="+")
    select.add_argument("--remove", action="store_true")
    select.add_argument("--apply", action="store_true")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace) -> None:
    desk = DataDesk(Path(get_agent_home()))
    if args.data_command == "catalog":
        result = {
            "catalog_revision": desk.catalog.revision,
            "series": [
                entry.model_dump(mode="json")
                for entry in desk.catalog.find_series(
                    args.query,
                    category=args.category,
                    region=args.region,
                    provider=args.provider,
                    country=args.country,
                    kind=args.kind,
                )
            ],
        }
    elif args.data_command == "selection":
        result = desk.selection().model_dump(mode="json")
    else:
        edit = DeskEdit(
            catalog_revision=desk.catalog.revision,
            preset_id=args.preset_id if args.data_command == "preset" else None,
            start_empty=args.data_command == "empty",
        )
        if args.data_command == "preset":
            if args.no_weather and args.weather_location:
                raise ValueError("Choose weather locations or --no-weather, not both")
            edit = edit.model_copy(
                update={
                    "home_region": args.home_region,
                    "weather_locations": []
                    if args.no_weather
                    else args.weather_location,
                }
            )
        if args.data_command == "select":
            edit = edit.model_copy(
                update={"remove" if args.remove else "add": args.series}
            )
        preview = desk.preview(edit)
        result = (
            desk.apply(edit, expected_revision=preview.revision)
            if args.apply
            else preview
        ).model_dump(mode="json")
    print(json.dumps(result, ensure_ascii=False, indent=2))
