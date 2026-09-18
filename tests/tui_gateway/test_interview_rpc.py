"""Generated interview contracts reject client actor spoofing before effects."""

from forecasting.interviews.service import InterviewService
from forecasting.ledger import ForecastLedger


def test_interview_gateway_validates_and_persists(tmp_path, monkeypatch):
    from tui_gateway import server, forecast_rpc

    service = InterviewService(ForecastLedger(tmp_path / "interviews.db"))
    monkeypatch.setattr(forecast_rpc, "_interview_service", lambda: service)

    def request(method, **params):
        return server.handle_request({"jsonrpc": "2.0", "id": 1, "method": f"forecast.interview.{method}", "params": params})

    started = request("begin", interview_id="wire")
    assert started["result"]["document"]["questions"]
    invalid = request("answer", interview_id="wire", expected_revision=1, request_id="bad",
                      question_id="belief", status="answered", value=0.4, actor="agent")
    assert "error" in invalid
    assert service.store.read("wire")["revision"] == 1
    valid = request("answer", interview_id="wire", expected_revision=1, request_id="good",
                    question_id="belief", status="answered", value=0.4)
    assert valid["result"]["document"]["answers"][0]["actor"] == "user"
    assert request("list")["result"]["interviews"][0]["revision"] == 2
