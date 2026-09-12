"""Shared and per-request OpenAI client lifecycle and request headers."""

import logging
import threading
from typing import Any, Optional

from agent.process_bootstrap import _get_proxy_for_base_url
from superforecasting_agent.urls import base_url_host_matches

logger = logging.getLogger("run_agent")


def _thread_identity(self) -> str:
    thread = threading.current_thread()
    return f"{thread.name}:{thread.ident}"


def _client_log_context(self) -> str:
    provider = getattr(self, "provider", "unknown")
    base_url = getattr(self, "base_url", "unknown")
    model = getattr(self, "model", "unknown")
    return (
        f"thread={self._thread_identity()} provider={provider} "
        f"base_url={base_url} model={model}"
    )


def _openai_client_lock(self) -> threading.RLock:
    lock = getattr(self, "_client_lock", None)
    if lock is None:
        lock = threading.RLock()
        self._client_lock = lock
    return lock


def detach_primary_client(self) -> Any:
    """Transfer this instance's current client to cleanup under the owner lock."""
    with _openai_client_lock(self):
        client = getattr(self, "client", None)
        self.client = None
        return client


def _is_openai_client_closed(client: Any) -> bool:
    """Check if an OpenAI client is closed.

    Handles both property and method forms of is_closed:
    - httpx.Client.is_closed is a bool property
    - openai.OpenAI.is_closed is a method returning bool

    Prior bug: getattr(client, "is_closed", False) returned the bound method,
    which is always truthy, causing unnecessary client recreation on every call.
    """
    from unittest.mock import Mock

    if isinstance(client, Mock):
        return False

    is_closed_attr = getattr(client, "is_closed", None)
    if is_closed_attr is not None:
        # Handle method (openai SDK) vs property (httpx)
        if callable(is_closed_attr):
            if is_closed_attr():
                return True
        elif bool(is_closed_attr):
            return True

    http_client = getattr(client, "_client", None)
    if http_client is not None:
        return bool(getattr(http_client, "is_closed", False))
    return False


def _build_keepalive_http_client(base_url: str = "") -> Any:
    try:
        import socket as _socket

        import httpx as _httpx

        _sock_opts = [(_socket.SOL_SOCKET, _socket.SO_KEEPALIVE, 1)]
        if hasattr(_socket, "TCP_KEEPIDLE"):
            _sock_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPIDLE, 30))
            _sock_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPINTVL, 10))
            _sock_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPCNT, 3))
        elif hasattr(_socket, "TCP_KEEPALIVE"):
            _sock_opts.append((_socket.IPPROTO_TCP, _socket.TCP_KEEPALIVE, 30))
        # When a custom transport is provided, httpx won't auto-read proxy
        # from env vars (allow_env_proxies = trust_env and transport is None).
        # Explicitly read proxy settings while still honoring NO_PROXY for
        # loopback / local endpoints such as a locally hosted sub2api.
        _proxy = _get_proxy_for_base_url(base_url)
        return _httpx.Client(
            transport=_httpx.HTTPTransport(socket_options=_sock_opts),
            proxy=_proxy,
        )
    except Exception:
        return None


def _close_openai_client(self, client: Any, *, reason: str, shared: bool) -> None:
    if client is None:
        return
    # The SDK/transport owns its pools, proxy mounts and socket lifetime.
    # Closing private sockets here bypasses that ownership and synchronization.
    try:
        client.close()
        logger.info(
            "OpenAI client closed (%s, shared=%s) %s",
            reason,
            shared,
            self._client_log_context(),
        )
    except Exception as exc:
        logger.debug(
            "OpenAI client close failed (%s, shared=%s) %s error=%s",
            reason,
            shared,
            self._client_log_context(),
            exc,
        )


def _replace_primary_openai_client(self, *, reason: str) -> bool:
    with self._openai_client_lock():
        if getattr(self, "_resources_closed", False):
            return False
        old_client = getattr(self, "client", None)
        try:
            new_client = self._create_openai_client(
                self._client_kwargs, reason=reason, shared=True
            )
        except Exception as exc:
            logger.warning(
                "Failed to rebuild shared OpenAI client (%s) %s error=%s",
                reason,
                self._client_log_context(),
                exc,
            )
            return False
        if getattr(self, "_resources_closed", False):
            self._close_openai_client(
                new_client, reason="closed_during_build", shared=True
            )
            return False
        self.client = new_client
    self._close_openai_client(old_client, reason=f"replace:{reason}", shared=True)
    return True


def _ensure_primary_openai_client(self, *, reason: str) -> Any:
    with self._openai_client_lock():
        if getattr(self, "_resources_closed", False):
            raise RuntimeError("Agent resources are closed")
        client = getattr(self, "client", None)
        if client is not None and not self._is_openai_client_closed(client):
            return client

    logger.warning(
        "Detected closed shared OpenAI client; recreating before use (%s) %s",
        reason,
        self._client_log_context(),
    )
    if not self._replace_primary_openai_client(reason=f"recreate_closed:{reason}"):
        raise RuntimeError("Failed to recreate closed OpenAI client")
    with self._openai_client_lock():
        return self.client


def _api_kwargs_have_image_parts(api_kwargs: dict) -> bool:
    """Return True when the outbound request still contains native image parts."""
    if not isinstance(api_kwargs, dict):
        return False
    candidates = []
    messages = api_kwargs.get("messages")
    if isinstance(messages, list):
        candidates.extend(messages)
    # Responses API payloads use `input`; after conversion, image parts can
    # still be present there instead of in `messages`.
    response_input = api_kwargs.get("input")
    if isinstance(response_input, list):
        candidates.extend(response_input)

    def _contains_image(value: Any) -> bool:
        if isinstance(value, dict):
            ptype = value.get("type")
            if ptype in {"image_url", "input_image"}:
                return True
            return any(_contains_image(v) for v in value.values())
        if isinstance(value, list):
            return any(_contains_image(v) for v in value)
        return False

    return any(_contains_image(item) for item in candidates)


def _copilot_headers_for_request(self, *, is_vision: bool) -> dict:
    from superforecasting_agent.runtime.copilot_auth import copilot_request_headers

    return copilot_request_headers(is_agent_turn=True, is_vision=is_vision)


def _create_request_openai_client(
    self, *, reason: str, api_kwargs: Optional[dict] = None
) -> Any:
    from unittest.mock import Mock

    primary_client = self._ensure_primary_openai_client(reason=reason)
    if isinstance(primary_client, Mock):
        return primary_client
    with self._openai_client_lock():
        request_kwargs = dict(self._client_kwargs)
    # Per-request OpenAI-wire clients (used by both the non-streaming
    # chat-completions path and the streaming chat-completions path
    # in `_interruptible_api_call`) should not run the SDK's built-in
    # retry loop: the agent's outer loop owns retries with credential
    # rotation, provider fallback, and backoff that the SDK can't
    # see. Leaving SDK retries on (default 2) compounds with our outer
    # retries and lets a single hung provider request stretch to ~3x
    # the per-call timeout before our stale detector reports it.
    # Shared/primary clients and Anthropic / Bedrock paths are
    # unaffected (they don't go through here).
    request_kwargs["max_retries"] = 0
    if base_url_host_matches(
        str(request_kwargs.get("base_url", "")), "api.githubcopilot.com"
    ) and self._api_kwargs_have_image_parts(api_kwargs or {}):
        request_kwargs["default_headers"] = self._copilot_headers_for_request(
            is_vision=True
        )
    return self._create_openai_client(request_kwargs, reason=reason, shared=False)


def _close_request_openai_client(self, client: Any, *, reason: str) -> None:
    self._close_openai_client(client, reason=reason, shared=False)
