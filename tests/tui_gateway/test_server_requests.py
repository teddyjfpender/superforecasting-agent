"""Transport ownership, duplicate replies and cancellation during prompt recovery."""

import threading

from tui_gateway.server_requests import ServerRequests


class Transport:
    def __init__(self):
        self.frames = []
        self.sent = threading.Event()

    def write(self, frame):
        self.frames.append(frame)
        self.sent.set()
        return True

    def close(self):
        pass


def test_reconnect_transfers_reply_authority_and_consumes_once():
    owner = ServerRequests()
    first, second = Transport(), Transport()
    results = []
    thread = threading.Thread(
        target=lambda: results.append(
            owner.request(
                "s",
                "clarify",
                {"question": "choose", "choices": None},
                first,
                timeout=5,
            )
        )
    )
    thread.start()
    try:
        assert first.sent.wait(2)
        frame = first.frames[0]
        assert owner.resume("other", second) == []
        assert owner.resume("s", second) == [frame]
        reply = {"jsonrpc": "2.0", "id": frame["id"], "result": {"answer": "yes"}}
        assert not owner.respond(reply, first)
        assert owner.respond(reply, second)
        assert not owner.respond(reply, second)
    finally:
        owner.cancel_session(None, "test cleanup")
        thread.join(2)
    assert not thread.is_alive() and results == [{"answer": "yes"}]
    assert owner.resume("s", second) == []


def test_timeout_withdraws_request_and_late_answer_is_ignored():
    owner, transport = ServerRequests(), Transport()
    assert (
        owner.request(
            "s", "secret", {"prompt": "Key", "env_var": "API_KEY"}, transport, timeout=0
        )
        is None
    )
    assert transport.frames[-1]["method"] == "request.cancel"
    assert not owner.respond(
        {"jsonrpc": "2.0", "id": transport.frames[0]["id"], "result": "late"}, transport
    )
    assert owner.resume("s", transport) == []


def test_legacy_bridge_checks_kind_and_same_transport():
    owner, transport = ServerRequests(), Transport()
    request_id, pending = owner.begin(
        "s", "secret", {"env_var": "API_KEY", "prompt": "Key"}, transport, legacy=True
    )
    assert transport.frames[0]["method"] == "event"
    assert not owner.legacy_reply(request_id, "password", "wrong", transport)
    assert not owner.legacy_reply(request_id, "value", "wrong peer", Transport())
    assert owner.legacy_reply(request_id, "value", "chosen", transport)
    assert pending.result == {"value": "chosen"}
    assert not owner.legacy_reply(request_id, "value", "duplicate", transport)


def test_approval_reply_targets_exact_queue_entry_and_settlement_withdraws(monkeypatch):
    from tools import approval

    owner, transport = ServerRequests(), Transport()
    first = approval._ApprovalEntry({"command": "first"})
    second = approval._ApprovalEntry({
        "command": "second",
        "description": "second command",
    })
    monkeypatch.setattr(approval, "_gateway_queues", {"s": [first, second]})
    monkeypatch.setattr(approval, "_gateway_settle_cbs", {})
    approval.register_gateway_settle("s", lambda rid: owner.cancel(rid, "settled"))
    request_id = second.data["request_id"]
    owner.begin(
        "s",
        "approval",
        second.data,
        transport,
        request_id=request_id,
        on_result=lambda result: bool(
            approval.resolve_gateway_approval(
                "s", result["choice"], request_id=request_id
            )
        ),
        on_cancel=lambda: approval.resolve_gateway_approval(
            "s", "deny", request_id=request_id
        ),
    )
    assert not owner.respond(
        {"jsonrpc": "2.0", "id": request_id, "result": {"choice": "invented"}},
        transport,
    )
    assert owner.respond(
        {"jsonrpc": "2.0", "id": request_id, "result": {"choice": "once"}}, transport
    )
    assert second.result == "once" and second.event.is_set()
    assert first.result is None and not first.event.is_set()
    assert transport.frames[-1]["method"] == "request.cancel"
    assert owner.resume("s", transport) == []


def test_actual_gateway_dispatch_handles_canonical_and_legacy_replies(
    monkeypatch, isolated_runtime_host
):
    from tui_gateway import server

    owner = ServerRequests()
    monkeypatch.setattr(server, "_server_requests", owner)
    for modern in (True, False):
        transport = Transport()
        server._host.sessions["s"] = {
            "session_key": "durable",
            "transport": transport,
            "server_requests": modern,
        }
        values = []
        thread = threading.Thread(
            target=lambda: values.append(
                server._block(
                    "clarify.request",
                    "s",
                    {"question": "Choose", "choices": []},
                    timeout=5,
                )
            )
        )
        thread.start()
        try:
            assert transport.sent.wait(2)
            frame = transport.frames[0]
            if modern:
                reply = {
                    "jsonrpc": "2.0",
                    "id": frame["id"],
                    "result": {"answer": "yes"},
                }
                assert server.dispatch(reply, Transport()) is None
                assert not values
                assert server.dispatch(reply, transport) is None
            else:
                request_id = frame["params"]["payload"]["request_id"]
                reply = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "clarify.respond",
                    "params": {"request_id": request_id, "answer": "yes"},
                }
                assert server.dispatch(reply, transport)["result"]["status"] == "ok"
        finally:
            thread.join(2)
            owner.cancel_session(None, "cleanup")
            thread.join(2)
            server._host.sessions.retire("s", lambda session: None)
        assert values == ["yes"] and not thread.is_alive()


def test_resume_can_change_wire_version_and_errors_cancel_exact_request():
    owner, old, new = ServerRequests(), Transport(), Transport()
    rid, pending = owner.begin("s", "sudo", {}, old, legacy=True)
    frames = owner.resume("s", new, legacy=False)
    assert frames[0]["method"] == "sudo" and frames[0]["id"] == rid
    assert not owner.legacy_reply(rid, "password", "secret", new)
    assert owner.respond(
        {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32800, "message": "cancelled"},
        },
        new,
    )
    assert pending.event.is_set() and pending.result is None
    assert owner.resume("s", old) == []


def test_cancellation_callback_failure_does_not_strand_other_requests():
    owner, transport = ServerRequests(), Transport()

    def broken():
        raise RuntimeError("cleanup failed")

    _, first = owner.begin("s", "sudo", {}, transport, on_cancel=broken)
    _, second = owner.begin("s", "sudo", {}, transport)
    owner.cancel_session("s", "shutdown")
    assert first.event.is_set() and second.event.is_set()
    assert owner.resume("s", transport) == []
