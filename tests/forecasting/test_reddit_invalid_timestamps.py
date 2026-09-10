"""Optional Reddit metadata must not abort otherwise usable evidence."""
import pytest

from forecasting import source_adapters


@pytest.mark.parametrize("timestamp", [
    float("inf"), float("-inf"), float("nan"), 1e100, -1e100, 10**400,
    "inf", "-inf", "nan", "1e100", "-1e100",
])
def test_reddit_unrepresentable_timestamp_keeps_post(monkeypatch, timestamp):
    payload = {"data": {"children": [
        {"data": {"id": "bad-date", "title": "Usable text", "created_utc": timestamp}},
        {"data": {"id": "valid-date", "title": "Next post", "created_utc": 1704067200}},
    ]}}
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: payload)
    posts = source_adapters.load_reddit_posts("forecasting")
    assert [post.post_id for post in posts] == ["bad-date", "valid-date"]
    assert posts[0].created_at is None
    assert posts[0].title == "Usable text"
    assert posts[1].created_at == "2024-01-01T00:00:00Z"


@pytest.mark.parametrize("timestamp,expected", [
    (0, "1970-01-01T00:00:00Z"),
    (-1, "1969-12-31T23:59:59Z"),
    (1704067200.9, "2024-01-01T00:00:00Z"),
    ("1704067200", "2024-01-01T00:00:00Z"),
    ("2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"),
])
def test_reddit_valid_timestamp_formats(monkeypatch, timestamp, expected):
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *args: [
        {"id": "valid-date", "created_utc": timestamp}
    ])
    assert source_adapters.load_reddit_posts("forecasting")[0].created_at == expected
