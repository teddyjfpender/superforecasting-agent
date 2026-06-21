"""Tests for semantic news ranking (forecasting.news_search)."""

from __future__ import annotations

import sys
import types

import pytest

import forecasting.news_search as news_search

ARTICLES = [
    {"title": "Fed holds rates steady amid inflation concerns", "summary": "FOMC keeps the target unchanged."},
    {"title": "Bloom Energy signs data center power deal", "summary": "Fuel cells to power AI datacenters."},
    {"title": "Local bakery wins a county award", "summary": "Sourdough takes first place."},
]


def _stub_call_llm(monkeypatch, content: str):
    def call_llm(**kwargs):
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", types.SimpleNamespace(call_llm=call_llm))


def test_rank_uses_llm_order_when_available(monkeypatch):
    _stub_call_llm(monkeypatch, '[{"i": 1, "score": 95}, {"i": 0, "score": 30}]')

    out = news_search.rank_news_articles("AI data center electricity demand", ARTICLES, limit=5)

    assert out["engine"] == "llm"
    assert [r["index"] for r in out["results"]] == [1, 0]
    assert out["results"][0]["score"] == 95


def test_rank_falls_back_to_lexical_when_llm_fails(monkeypatch):
    def boom(**kwargs):
        raise RuntimeError("no provider configured")

    monkeypatch.setitem(sys.modules, "agent.auxiliary_client", types.SimpleNamespace(call_llm=boom))

    out = news_search.rank_news_articles("Fed inflation rates", ARTICLES, limit=5)

    assert out["engine"] == "lexical"
    # The Fed headline scores highest lexically; the bakery is irrelevant and dropped.
    assert out["results"][0]["index"] == 0
    assert all(r["index"] != 2 for r in out["results"])


def test_rank_ignores_out_of_range_or_dup_llm_indices(monkeypatch):
    _stub_call_llm(monkeypatch, '[{"i": 99, "score": 80}, {"i": 1, "score": 70}, {"i": 1, "score": 60}]')

    out = news_search.rank_news_articles("energy", ARTICLES, limit=5)

    # 99 is out of range, the duplicate 1 is collapsed → just one valid hit.
    assert [r["index"] for r in out["results"]] == [1]


def test_rank_rejects_bool_index(monkeypatch):
    # bool is an int subclass; {"i": true} must not masquerade as index 1.
    _stub_call_llm(monkeypatch, '[{"i": true, "score": 90}, {"i": 1, "score": 80}]')

    out = news_search.rank_news_articles("energy", ARTICLES, limit=5)

    assert [r["index"] for r in out["results"]] == [1]
    assert all(r["index"] is not True for r in out["results"])


def test_rank_extracts_json_from_prose_wrapped_response(monkeypatch):
    # A bracketed prose preamble must not defeat extraction (greedy [.*] would).
    _stub_call_llm(monkeypatch, 'Here is [my ranking] for you:\n[{"i": 1, "score": 88}]')

    out = news_search.rank_news_articles("AI data center", ARTICLES, limit=5)

    assert out["engine"] == "llm"
    assert [r["index"] for r in out["results"]] == [1]


@pytest.mark.parametrize("query,articles", [("", ARTICLES), ("anything", [])])
def test_rank_empty_inputs(query, articles):
    assert news_search.rank_news_articles(query, articles) == {"results": [], "engine": "none"}
