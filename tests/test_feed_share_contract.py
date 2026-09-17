"""Python and TypeScript consume the same portable snapshot fixture."""

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from protocol.feed_share import FeedShare


def snapshot():
    return json.loads(
        (Path(__file__).parent / "fixtures/feed_share/v1.json").read_text()
    )


def test_snapshot_round_trip():
    raw = snapshot()
    assert FeedShare.model_validate(raw).model_dump() == raw


@pytest.mark.parametrize(
    "mutation",
    [
        "version",
        "boolean_version",
        "duplicate",
        "overlap",
        "outside",
        "nan",
        "string",
        "control",
        "secret_url",
        "extra",
    ],
)
def test_untrusted_snapshot_rejected(mutation):
    raw = snapshot()
    feed = raw["feeds"][0]
    if mutation == "version":
        raw["version"] = 3
    if mutation == "boolean_version":
        raw["version"] = True
    if mutation == "duplicate":
        raw["feeds"].append(feed.copy())
    if mutation == "overlap":
        feed["points"][1]["start"] = "2026-06-30"
    if mutation == "outside":
        raw["horizon"]["end"] = "2026-07-31"
    if mutation == "nan":
        feed["points"][0]["value"] = float("nan")
    if mutation == "string":
        feed["points"][0]["value"] = "0.16"
    if mutation == "control":
        feed["name"] = "\x1b[2J"
    if mutation == "secret_url":
        feed["source_url"] = "https://example.com/?api_key=secret"
    if mutation == "extra":
        raw["execute"] = "something"
    with pytest.raises(ValidationError):
        FeedShare.model_validate(raw)


def test_intraday_snapshot_round_trip_and_version_boundaries():
    raw = json.loads(
        (Path(__file__).parent / "fixtures/feed_share/v2.json").read_text()
    )
    assert FeedShare.model_validate(raw).model_dump() == raw
    raw["version"] = 1
    with pytest.raises(ValidationError):
        FeedShare.model_validate(raw)
    raw["version"] = 2
    raw["feeds"][0]["points"][0]["start"] = "2026-09-16"
    with pytest.raises(ValidationError):
        FeedShare.model_validate(raw)
