"""The centralized skill index follows the fork's configured documentation site."""

from types import SimpleNamespace

from tools import skills_hub


def test_skill_index_fetch_uses_fork_documentation_url(monkeypatch, tmp_path):
    requested = []
    payload = {"skills": []}

    def get(url, **kwargs):
        requested.append(url)
        return SimpleNamespace(status_code=200, json=lambda: payload)

    monkeypatch.setattr(skills_hub, "HERMES_INDEX_CACHE_FILE", tmp_path / "index.json")
    monkeypatch.setattr(skills_hub.httpx, "get", get)
    assert skills_hub._load_hermes_index() == payload
    assert requested == [
        "https://teddyjfpender.github.io/superforecasting-agent/docs/api/skills-index.json"
    ]
