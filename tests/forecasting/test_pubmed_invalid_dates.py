"""Invalid optional publication dates must not abort a PubMed import."""

import pytest
from forecasting import source_adapters


@pytest.mark.parametrize("year,month,day,expected", [
    pytest.param("0000", "1", "1", None, id="zero-year"),
    pytest.param("2026", "Feb", "30", None, id="invalid-calendar-day"),
    pytest.param("2025", "2", "29", None, id="non-leap-year"),
    pytest.param("2026", "²", "1", None, id="non-decimal-month"),
    pytest.param("2024", "2", "29", "2024-02-29T00:00:00Z", id="valid-leap-day"),
])
def test_invalid_optional_dates_preserve_articles(monkeypatch, year, month, day, expected):
    xml = f"""<PubmedArticleSet>
      <PubmedArticle><MedlineCitation><PMID>1</PMID><Article>
        <ArticleTitle>First fixture</ArticleTitle><ArticleDate>
          <Year>{year}</Year><Month>{month}</Month><Day>{day}</Day>
        </ArticleDate></Article></MedlineCitation></PubmedArticle>
      <PubmedArticle><MedlineCitation><PMID>2</PMID><Article>
        <ArticleTitle>Second fixture</ArticleTitle><ArticleDate>
          <Year>2026</Year><Month>1</Month><Day>2</Day>
        </ArticleDate></Article></MedlineCitation></PubmedArticle>
    </PubmedArticleSet>"""
    monkeypatch.setattr(source_adapters, "_read_json_endpoint", lambda *_: {"esearchresult": {"idlist": ["1", "2"]}})
    monkeypatch.setattr(source_adapters, "_read_text_endpoint", lambda *_: xml)

    articles = source_adapters.load_pubmed_articles("fixture")

    assert [(row.pmid, row.published_at) for row in articles] == [
        ("1", expected), ("2", "2026-01-02T00:00:00Z"),
    ]
