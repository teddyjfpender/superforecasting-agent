"""Owned server-to-client JSON-RPC requests, independent of prompt presentation."""

import copy
import logging
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from protocol.server_requests import SERVER_REQUESTS
from tui_gateway.transport import Transport

logger = logging.getLogger(__name__)


@dataclass
class PendingRequest:
    session_id: str
    method: str
    params: dict[str, Any]
    transport: Transport
    legacy: bool = False
    on_result: Callable[[Any], bool] | None = None
    on_cancel: Callable[[], None] | None = None
    event: threading.Event = field(default_factory=threading.Event)
    result: Any = None
    error: dict[str, Any] | None = None


class ServerRequests:
    """Replies belong to one transport generation; a reconnect explicitly transfers it."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._pending: dict[str, PendingRequest] = {}

    @staticmethod
    def frame(request_id: str, pending: PendingRequest) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": pending.method,
            "params": {**pending.params, "session_id": pending.session_id},
        }

    @classmethod
    def delivery(cls, request_id: str, pending: PendingRequest) -> dict[str, Any]:
        if pending.legacy:
            return {
                "jsonrpc": "2.0",
                "method": "event",
                "params": {
                    "type": pending.method + ".request",
                    "session_id": pending.session_id,
                    "payload": {**pending.params, "request_id": request_id},
                },
            }
        return cls.frame(request_id, pending)

    def legacy_reply(
        self, request_id: str, key: str, value: str, transport: Transport
    ) -> bool:
        with self._lock:
            pending = self._pending.get(request_id)
            expected = {
                "clarify": "answer",
                "sudo": "password",
                "secret": "value",
                "approval": "choice",
            }
            if (
                pending is None
                or not pending.legacy
                or expected.get(pending.method) != key
            ):
                return False
            return self.respond(
                {"jsonrpc": "2.0", "id": request_id, "result": {key: value}}, transport
            )

    def begin(
        self,
        session_id: str,
        method: str,
        params: dict[str, Any],
        transport: Transport,
        *,
        legacy: bool = False,
        on_result: Callable[[Any], bool] | None = None,
        request_id: str | None = None,
        on_cancel: Callable[[], None] | None = None,
    ) -> tuple[str, PendingRequest]:
        request_id = request_id or "srq-" + uuid.uuid4().hex
        if method not in SERVER_REQUESTS:
            raise ValueError("unknown server request method")
        SERVER_REQUESTS[method][0].model_validate(
            {**params, "request_id": request_id}, strict=True
        )
        pending = PendingRequest(
            session_id,
            method,
            copy.deepcopy(params),
            transport,
            legacy=legacy,
            on_result=on_result,
            on_cancel=on_cancel,
        )
        with self._lock:
            if request_id in self._pending:
                raise ValueError("server request already exists")
            self._pending[request_id] = pending
            try:
                transport.write(self.delivery(request_id, pending))
            except BaseException:
                self._pending.pop(request_id, None)
                raise
        return request_id, pending

    def request(
        self,
        session_id: str,
        method: str,
        params: dict[str, Any],
        transport: Transport,
        timeout: float = 300,
        legacy: bool = False,
    ) -> Any:
        request_id, pending = self.begin(
            session_id, method, params, transport, legacy=legacy
        )
        try:
            if not pending.event.wait(timeout):
                self.cancel(request_id, "timeout")
            return pending.result
        finally:
            self.cancel(request_id, "request finished")

    def respond(self, frame: dict[str, Any], transport: Transport) -> bool:
        request_id = frame.get("id")
        if not isinstance(request_id, str) or frame.get("jsonrpc") != "2.0":
            return False
        if ("result" in frame) == ("error" in frame) or "method" in frame:
            return False
        if "error" in frame:
            error = frame["error"]
            if (
                not isinstance(error, dict)
                or type(error.get("code")) is not int
                or not isinstance(error.get("message"), str)
            ):
                return False
        with self._lock:
            pending = self._pending.get(request_id)
            if pending is None or pending.transport is not transport:
                return False
            if "error" in frame:
                self.cancel(request_id, "client cancelled request")
                return True
            model = SERVER_REQUESTS[pending.method][1]
            result = frame["result"]
            if (
                not isinstance(result, dict)
                or result.keys() != model.model_fields.keys()
            ):
                return False
            try:
                model.model_validate(result, strict=True)
            except ValidationError:
                return False
            if pending.on_result is not None and not pending.on_result(
                frame.get("result")
            ):
                return False
            self._pending.pop(request_id, None)
            pending.result = frame.get("result")
            pending.error = frame.get("error")
            pending.event.set()
            return True

    def cancel(self, request_id: str, reason: str) -> None:
        with self._lock:
            pending = self._pending.pop(request_id, None)
            if pending is None:
                return
            pending.event.set()
            if pending.on_cancel is not None:
                try:
                    pending.on_cancel()
                except Exception:
                    logger.exception("Prompt cancellation callback failed")
            try:
                pending.transport.write({
                    "jsonrpc": "2.0",
                    "method": "request.cancel",
                    "params": {
                        "id": request_id,
                        "method": pending.method,
                        "reason": reason,
                    },
                })
            except Exception:
                logger.warning(
                    "Prompt cancellation could not reach its disconnected transport"
                )

    def cancel_session(self, session_id: str | None, reason: str) -> None:
        with self._lock:
            for request_id, pending in list(self._pending.items()):
                if session_id is None or pending.session_id == session_id:
                    self.cancel(request_id, reason)

    def resume(
        self, session_id: str, transport: Transport, *, legacy: bool | None = None
    ) -> list[dict[str, Any]]:
        """Transfer only outstanding requests after the session's resume admission."""
        with self._lock:
            frames = []
            for request_id, pending in self._pending.items():
                if pending.session_id == session_id:
                    pending.transport = transport
                    if legacy is not None:
                        pending.legacy = legacy
                    frames.append(self.delivery(request_id, pending))
            return frames
