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


def test_generation_start_retries_return_same_durable_job(tmp_path, monkeypatch):
    from forecasting.jobs import detached
    from tui_gateway import server, forecast_rpc

    service = InterviewService(ForecastLedger(tmp_path / "interviews.db"))
    service.begin("adaptive")
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    monkeypatch.setattr(forecast_rpc, "_interview_service", lambda: service)
    launched = []
    monkeypatch.setattr(detached, "spawn_detached_job", lambda job_id, **kwargs: launched.append((job_id, kwargs)))
    request = {"jsonrpc": "2.0", "id": 3, "method": "forecast.interview.generate",
               "params": {"interview_id": "adaptive", "revision": 1, "request_id": "start"}}
    first = server.handle_request(request)
    assert "result" in first, first
    assert server.handle_request(request)["result"] == first["result"]
    assert len({job for job, _ in launched}) == 1
    assert launched[0][1]["home"] == tmp_path
    invalid = {**request, "params": {**request["params"], "options": {"max_tokens": 999999}}}
    assert "error" in server.handle_request(invalid)
    assert len(launched) == 2


def test_review_comparison_and_promotion_round_trip_uses_durable_contracts(tmp_path, monkeypatch):
    """Real RPC dispatch and jobs with a controlled model; reconstruct service on every request."""
    import hashlib
    import json
    from forecasting.interviews import evaluation
    from forecasting.jobs import detached
    from forecasting.jobs.runtime import run
    from forecasting.jobs.store import JobStore
    from forecasting.ledger import allow_ledger_writes
    from tui_gateway import server, forecast_rpc

    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(tmp_path))
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    path = tmp_path / "roundtrip.db"
    ledger = ForecastLedger(path)
    with allow_ledger_writes(reason="fixture"):
        question = ledger.create_question(title="Will the candidate run by 2030?", resolution_criteria="Official filing before December 2030.")
    evidence = ledger.add_evidence(question_id=question.id, source_or_note="Official registry", claim="Candidate is eligible", summary="Eligibility record", archive_url_snapshot=False)
    reference = ledger.add_reference_class(question_id=question.id, name="Prior eligible candidates", inclusion_criteria="Same office and eligibility rules", base_rate=0.4)
    monkeypatch.setattr(forecast_rpc, "_interview_service", lambda: InterviewService(ForecastLedger(path)))
    monkeypatch.setattr(detached, "spawn_detached_job", lambda *args, **kwargs: None)

    def request(method, **params):
        response = server.handle_request({"jsonrpc": "2.0", "id": 9, "method": f"forecast.interview.{method}", "params": params})
        assert "error" not in response, response
        return response["result"]

    draft = request("begin", interview_id="roundtrip", question_id=question.id)
    draft = request("answer", interview_id="roundtrip", expected_revision=draft["revision"], request_id="drivers", question_id="drivers", status="answered", value="Candidate remains healthy")
    assumption = draft["document"]["assumptions"][0]
    draft = request("assumption.save", interview_id="roundtrip", expected_revision=draft["revision"], request_id="belief", assumption={**assumption, "probability": 0.8, "uncertainty": "mixed"})
    draft = request("scenario.save", interview_id="roundtrip", expected_revision=draft["revision"], request_id="scenario", scenario={"id": "healthy", "name": "Healthy candidate", "kind": "conditional", "conditions": {assumption["id"]: True}})
    calls = []

    def model(messages, options, cancelled):
        packet = json.loads(messages[1]["content"])
        assert packet["reference_classes"][0]["id"] == reference["id"]
        calls.append(packet["variant"]["id"])
        return {
            "content": json.dumps({"outcome_type": "binary", "probability": 0.4 if packet["variant"]["id"] == "baseline" else 0.6,
                                   "rationale": "Controlled comparison using prior candidates", "evidence_refs": [evidence.id], "reference_class_refs": [reference["id"]]}),
            "response_model": "controlled", "output_tokens": 50,
            "request_receipt": {"fingerprint": hashlib.sha256(b"same-route").hexdigest(), "provider": "fake", "model": "controlled"},
        }

    monkeypatch.setattr(evaluation, "run_model", model)
    params = {"interview_id": "roundtrip", "revision": draft["revision"], "request_id": "compare", "options": {"scenario_ids": ["healthy"]}}
    started = request("evaluate", **params)
    assert request("evaluate", **params) == started
    assert run(started["job_id"], store=JobStore(tmp_path)).status == "done"
    status = request("evaluation_status", interview_id="roundtrip")
    assert status["report"]["results"][0]["estimate"]["reference_class_refs"] == [reference["id"]]
    assert calls == ["baseline", "healthy"]
    assert ledger.list_snapshots(question.id) == []
    preview = request("promotion_preview", job_id=started["job_id"])
    assert preview["would_commit"], preview
    acceptance = {"job_id": started["job_id"], "preview_digest": preview["preview_digest"]}
    promoted = request("promote", **acceptance)
    assert request("promote", **acceptance) == promoted
    assert len(ledger.list_snapshots(question.id)) == 1
    snapshot = ledger.get_current_snapshot(question.id)
    assert snapshot.probability_or_distribution == 0.4
    assert snapshot.reference_class_refs == [reference["id"]]
    assert request("promotion_preview", job_id=started["job_id"])["promoted_forecast_id"] == promoted["forecast_id"]
