"""Generated interview contracts reject client actor spoofing before effects."""

from forecasting.interviews.service import InterviewService
from forecasting.ledger import ForecastLedger


def test_interview_gateway_validates_and_persists(tmp_path, monkeypatch):
    from tui_gateway import server, forecast_rpc

    service = InterviewService(ForecastLedger(tmp_path / "interviews.db"))
    monkeypatch.setattr(forecast_rpc, "_interview_service", lambda: service)

    def request(method, **params):
        return server.handle_request({
            "jsonrpc": "2.0",
            "id": 1,
            "method": f"forecast.interview.{method}",
            "params": params,
        })

    started = request("begin", interview_id="wire")
    assert started["result"]["document"]["questions"]
    invalid = request(
        "answer",
        interview_id="wire",
        expected_revision=1,
        request_id="bad",
        question_id="belief",
        status="answered",
        value=0.4,
        actor="agent",
    )
    assert "error" in invalid
    assert service.store.read("wire")["revision"] == 1
    valid = request(
        "answer",
        interview_id="wire",
        expected_revision=1,
        request_id="good",
        question_id="belief",
        status="answered",
        value=0.4,
    )
    assert valid["result"]["document"]["answers"][0]["actor"] == "user"
    assert request("list")["result"]["interviews"][0]["revision"] == 2


def test_article_attachment_and_picker_use_validated_contracts(tmp_path, monkeypatch):
    from forecasting import ledger as ledger_module
    from forecasting.ledger import allow_ledger_writes
    from tui_gateway import server

    ledger = ForecastLedger(tmp_path / "articles.db")
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(
            title="Will CPI exceed 3 percent in June 2030?",
            resolution_criteria="Resolves yes if the BLS June 2030 first release reports annual CPI above 3 percent.",
        )
    monkeypatch.setattr(ledger_module, "ForecastLedger", lambda: ledger)

    def request(method, params):
        return server.handle_request({
            "jsonrpc": "2.0",
            "id": 2,
            "method": method,
            "params": params,
        })

    choices = request("forecast.question.choices", {})
    assert choices["result"]["questions"][0]["id"] == question.id
    article = {
        "title": "Inflation report",
        "url": "https://example.org/article",
        "feed_url": "https://example.org/rss",
        "content": "Publisher report",
        "extraction": "feed",
    }
    params = {"question_id": question.id, "article": article, "prepare_update": True}
    invalid = request(
        "forecast.article.attach",
        {**params, "article": {**article, "url": "file:///tmp/secret"}},
    )
    assert "error" in invalid
    assert ledger.list_evidence(question.id) == []
    attached = request("forecast.article.attach", params)
    assert attached["result"]["interview_id"]
    assert (
        request("forecast.article.attach", params)["result"]["already_attached"] is True
    )
