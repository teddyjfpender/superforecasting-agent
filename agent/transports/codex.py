"""OpenAI Responses API (Codex) transport.

Delegates to the existing adapter functions in agent/codex_responses_adapter.py.
This transport owns format conversion and normalization — NOT client lifecycle,
streaming, or the _run_codex_stream() call path.
"""

import hashlib
import json
from typing import Any, Dict, List, Optional

from agent.transports.base import ProviderTransport
from agent.transports.types import NormalizedResponse, ToolCall


def _content_cache_key(instructions: str, tools: Optional[List[Dict[str, Any]]]) -> Optional[str]:
    """Content-address the prompt cache key from the static request prefix.

    Returns ``pck_<sha256[:24]>`` of (instructions + sorted tool schemas), or
    None when there is nothing static to key on. The cache key is a routing
    hint only — never a correctness boundary — so two requests sharing a system
    prompt and tool set intentionally resolve to the same warm prefix bucket.

    The fix this exists for: recurring cron jobs build session_id as
    ``cron_<id>_<timestamp>``, so using session_id as the cache key made every
    fire cache-cold. The static prefix (identity + tools) is identical across
    fires, so hashing it gives a stable key that stays warm within the
    provider's cache TTL. Sorting tools by name keeps the hash insertion-order
    independent.
    """
    if not instructions and not tools:
        return None
    tools_part = ""
    if tools:
        sorted_tools = sorted(
            (t for t in tools if isinstance(t, dict)),
            key=lambda t: str(t.get("name") or t.get("type") or ""),
        )
        tools_part = json.dumps(
            sorted_tools, sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
    # \x00 separator so instructions ending in the tool JSON can't collide with
    # a request whose instructions contain that JSON and whose tools are empty.
    content = f"{instructions or ''}\x00{tools_part}"
    digest = hashlib.sha256(content.encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"pck_{digest}"


class ResponsesApiTransport(ProviderTransport):
    """Transport for api_mode='codex_responses'.

    Wraps the functions extracted into codex_responses_adapter.py (PR 1).
    """

    @property
    def api_mode(self) -> str:
        return "codex_responses"

    def convert_messages(self, messages: List[Dict[str, Any]], **kwargs) -> Any:
        """Convert OpenAI chat messages to Responses API input items."""
        from agent.codex_responses_adapter import _chat_messages_to_responses_input
        return _chat_messages_to_responses_input(
            messages,
            is_xai_responses=bool(kwargs.get("is_xai_responses")),
        )

    def convert_tools(self, tools: List[Dict[str, Any]]) -> Any:
        """Convert OpenAI tool schemas to Responses API function definitions."""
        from agent.codex_responses_adapter import _responses_tools
        return _responses_tools(tools)

    def build_kwargs(
        self,
        model: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        **params,
    ) -> Dict[str, Any]:
        """Build Responses API kwargs.

        Calls convert_messages and convert_tools internally.

        params:
            instructions: str — system prompt (extracted from messages[0] if not given)
            reasoning_config: dict | None — {effort, enabled, summary}
                ``summary`` is the codex reasoning.summary mode
                ("auto" | "concise" | "detailed"); defaults to "detailed".
            reasoning_summary: str | None — direct override of the summary mode
                (wins over reasoning_config["summary"]); same accepted values.
            session_id: str | None — transcript/session id; drives the xAI
                x-grok-conv-id header and the Codex cache-scope headers, and is
                the fallback prompt_cache_key when there is no static prefix to
                content-address
            max_tokens: int | None — max_output_tokens
            timeout: float | None — per-request timeout forwarded to the SDK
            request_overrides: dict | None — extra kwargs merged in
            provider: str | None — provider name for backend-specific logic
            base_url: str | None — endpoint URL
            base_url_hostname: str | None — hostname for backend detection
            is_github_responses: bool — Copilot/GitHub models backend
            is_codex_backend: bool — chatgpt.com/backend-api/codex
            is_xai_responses: bool — xAI/Grok backend
            github_reasoning_extra: dict | None — Copilot reasoning params
        """
        from agent.codex_responses_adapter import (
            _chat_messages_to_responses_input,
            _responses_tools,
        )

        from run_agent import DEFAULT_AGENT_IDENTITY

        instructions = params.get("instructions", "")
        payload_messages = messages
        if not instructions:
            if messages and messages[0].get("role") == "system":
                instructions = str(messages[0].get("content") or "").strip()
                payload_messages = messages[1:]
        if not instructions:
            instructions = DEFAULT_AGENT_IDENTITY

        is_github_responses = params.get("is_github_responses", False)
        is_codex_backend = params.get("is_codex_backend", False)
        is_xai_responses = params.get("is_xai_responses", False)

        # Resolve reasoning effort
        reasoning_effort = "medium"
        reasoning_enabled = True
        # Codex/OpenAI reasoning.summary mode. "detailed" returns the FULLER,
        # readable reasoning summary; "auto" returns a compressed, note-form
        # ("caveman") summary; "concise" sits in between. We default to
        # "detailed" so the reasoning display reads as prose, and let the
        # user tune it via reasoning_config["summary"] (config key
        # agent.reasoning_summary). The grok branch below stays summary-less.
        reasoning_summary = "detailed"
        reasoning_config = params.get("reasoning_config")
        if reasoning_config and isinstance(reasoning_config, dict):
            if reasoning_config.get("enabled") is False:
                reasoning_enabled = False
            elif reasoning_config.get("effort"):
                reasoning_effort = reasoning_config["effort"]
            summary_override = reasoning_config.get("summary")
            if summary_override is not None:
                reasoning_summary = summary_override
        # A direct params override (e.g. request_overrides plumbing) wins.
        if params.get("reasoning_summary") is not None:
            reasoning_summary = params.get("reasoning_summary")

        _effort_clamp = {"minimal": "low"}
        reasoning_effort = _effort_clamp.get(reasoning_effort, reasoning_effort)

        # Clamp the summary mode to the OpenAI-accepted set; unknown values
        # fall back to the readable "detailed" default.
        _VALID_SUMMARY = {"auto", "concise", "detailed"}
        reasoning_summary = str(reasoning_summary or "").strip().lower()
        if reasoning_summary not in _VALID_SUMMARY:
            reasoning_summary = "detailed"

        # ``tools`` MUST be omitted entirely when there are no functions to
        # expose: the openai SDK's ``responses.stream()`` / ``responses.parse()``
        # eagerly call ``_make_tools(tools)`` which does ``for tool in tools``
        # without a None guard, so passing ``tools=None`` raises
        # ``TypeError: 'NoneType' object is not iterable`` before any HTTP
        # request is issued (openai==2.24.0).  Reported for the
        # ``openai-codex`` / ``gpt-5.5`` combo on chatgpt.com/backend-api/codex
        # (#32892) when the agent runs without external tools registered.
        response_tools = _responses_tools(tools)
        kwargs = {
            "model": model,
            "instructions": instructions,
            "input": _chat_messages_to_responses_input(
                payload_messages,
                is_xai_responses=is_xai_responses,
            ),
            "store": False,
        }
        if response_tools:
            kwargs["tools"] = response_tools
            kwargs["tool_choice"] = "auto"
            kwargs["parallel_tool_calls"] = True

        session_id = params.get("session_id")
        # prompt_cache_key is content-addressed from the static prefix
        # (instructions + tools), NOT session_id — recurring cron jobs carry a
        # per-fire timestamp in session_id (cron_<id>_<ts>) that made every run
        # cache-cold. session_id is left untouched for transcript isolation and
        # the cache-scope routing headers below. Falls back to session_id when
        # there is no static content to hash.
        cache_key = _content_cache_key(instructions, response_tools) or session_id
        # xAI Responses takes prompt_cache_key in extra_body (set further
        # down); GitHub Models opts out of cache-key routing entirely.
        if not is_github_responses and not is_xai_responses and cache_key:
            kwargs["prompt_cache_key"] = cache_key

        if reasoning_enabled and is_xai_responses:
            from agent.model_metadata import grok_supports_reasoning_effort

            # NOTE: Hermes does NOT ask xAI to return ``reasoning.encrypted_content``
            # any more.  xAI's OAuth/SuperGrok ``/v1/responses`` surface rejects
            # replayed encrypted reasoning items on turn 2+ — see
            # _chat_messages_to_responses_input docstring.  Requesting the field
            # back would just have us cache something we then must strip.  Grok
            # still reasons natively each turn; coherence across turns rides on
            # the visible message text alone.
            kwargs["include"] = []
            # xAI rejects `reasoning.effort` on grok-4 / grok-4-fast / grok-3
            # / grok-code-fast / grok-4.20-0309-* with HTTP 400 even though
            # those models reason natively. Only send the effort dial when
            # the target model is on the allowlist; otherwise send no
            # `reasoning` key at all and let the model reason on its own.
            if grok_supports_reasoning_effort(model):
                kwargs["reasoning"] = {"effort": reasoning_effort}
        elif reasoning_enabled:
            if is_github_responses:
                github_reasoning = params.get("github_reasoning_extra")
                if github_reasoning is not None:
                    kwargs["reasoning"] = github_reasoning
            else:
                kwargs["reasoning"] = {"effort": reasoning_effort, "summary": reasoning_summary}
                kwargs["include"] = ["reasoning.encrypted_content"]
        elif not is_github_responses and not is_xai_responses:
            kwargs["include"] = []

        request_overrides = params.get("request_overrides")
        if request_overrides:
            kwargs.update(request_overrides)

        # Forward per-request timeout to the SDK so OpenAI/Anthropic clients
        # honor it.  Without this, ``providers.<id>.request_timeout_seconds``
        # is silently dropped on the main agent Codex path while the
        # chat_completions path and auxiliary Codex adapter both forward it.
        timeout = kwargs.get("timeout", params.get("timeout"))
        if (
            isinstance(timeout, (int, float))
            and not isinstance(timeout, bool)
            and 0 < float(timeout) < float("inf")
        ):
            kwargs["timeout"] = float(timeout)
        else:
            kwargs.pop("timeout", None)

        if is_codex_backend:
            cache_scope_id = str(session_id or "").strip()
            if cache_scope_id:
                existing_extra_headers = kwargs.get("extra_headers")
                merged_extra_headers: Dict[str, str] = {}
                if isinstance(existing_extra_headers, dict):
                    merged_extra_headers.update(
                        {
                            str(key): str(value)
                            for key, value in existing_extra_headers.items()
                            if key and value is not None
                        }
                    )
                merged_extra_headers["session_id"] = cache_scope_id
                merged_extra_headers["x-client-request-id"] = cache_scope_id
                kwargs["extra_headers"] = merged_extra_headers

        max_tokens = params.get("max_tokens")
        if max_tokens is not None and not is_codex_backend:
            kwargs["max_output_tokens"] = max_tokens

        if is_xai_responses and session_id:
            existing_extra_headers = kwargs.get("extra_headers")
            merged_extra_headers: Dict[str, str] = {}
            if isinstance(existing_extra_headers, dict):
                merged_extra_headers.update(
                    {
                        str(key): str(value)
                        for key, value in existing_extra_headers.items()
                        if key and value is not None
                    }
                )
            merged_extra_headers["x-grok-conv-id"] = session_id
            kwargs["extra_headers"] = merged_extra_headers

            # xAI Responses cache-routing — body-level field per
            # https://docs.x.ai/developers/advanced-api-usage/prompt-caching/maximizing-cache-hits.
            # Sent via extra_body (not the typed kwarg) so it survives openai
            # SDK builds whose Responses.stream() signature has dropped the field.
            existing_extra_body = kwargs.get("extra_body")
            merged_extra_body: Dict[str, Any] = {}
            if isinstance(existing_extra_body, dict):
                merged_extra_body.update(existing_extra_body)
            merged_extra_body.setdefault("prompt_cache_key", cache_key)
            kwargs["extra_body"] = merged_extra_body

        return kwargs

    def normalize_response(self, response: Any, **kwargs) -> NormalizedResponse:
        """Normalize Codex Responses API response to NormalizedResponse."""
        from agent.codex_responses_adapter import (
            _normalize_codex_response,
        )

        # _normalize_codex_response returns (SimpleNamespace, finish_reason_str)
        msg, finish_reason = _normalize_codex_response(response)

        tool_calls = None
        if msg and msg.tool_calls:
            tool_calls = []
            for tc in msg.tool_calls:
                provider_data = {}
                if hasattr(tc, "call_id") and tc.call_id:
                    provider_data["call_id"] = tc.call_id
                if hasattr(tc, "response_item_id") and tc.response_item_id:
                    provider_data["response_item_id"] = tc.response_item_id
                tool_calls.append(ToolCall(
                    id=tc.id if hasattr(tc, "id") else (tc.function.name if hasattr(tc, "function") else None),
                    name=tc.function.name if hasattr(tc, "function") else getattr(tc, "name", ""),
                    arguments=tc.function.arguments if hasattr(tc, "function") else getattr(tc, "arguments", "{}"),
                    provider_data=provider_data or None,
                ))

        # Extract reasoning items for provider_data
        provider_data = {}
        if msg and hasattr(msg, "codex_reasoning_items") and msg.codex_reasoning_items:
            provider_data["codex_reasoning_items"] = msg.codex_reasoning_items
        if msg and hasattr(msg, "codex_message_items") and msg.codex_message_items:
            provider_data["codex_message_items"] = msg.codex_message_items
        if msg and hasattr(msg, "reasoning_details") and msg.reasoning_details:
            provider_data["reasoning_details"] = msg.reasoning_details

        return NormalizedResponse(
            content=msg.content if msg else None,
            tool_calls=tool_calls,
            finish_reason=finish_reason or "stop",
            reasoning=msg.reasoning if msg and hasattr(msg, "reasoning") else None,
            usage=None,  # Codex usage is extracted separately in normalize_usage()
            provider_data=provider_data or None,
        )

    def validate_response(self, response: Any) -> bool:
        """Check Codex Responses API response has valid output structure.

        Returns True only if response.output is a non-empty list.
        Does NOT check output_text fallback — the caller handles that
        with diagnostic logging for stream backfill recovery.
        """
        if response is None:
            return False
        output = getattr(response, "output", None)
        if not isinstance(output, list) or not output:
            return False
        return True

    def preflight_kwargs(self, api_kwargs: Any, *, allow_stream: bool = False) -> dict:
        """Validate and sanitize Codex API kwargs before the call.

        Normalizes input items, strips unsupported fields, validates structure.
        """
        from agent.codex_responses_adapter import _preflight_codex_api_kwargs
        return _preflight_codex_api_kwargs(api_kwargs, allow_stream=allow_stream)

    def map_finish_reason(self, raw_reason: str) -> str:
        """Map Codex response.status to OpenAI finish_reason.

        Codex uses response.status ('completed', 'incomplete') +
        response.incomplete_details.reason for granular mapping.
        This method handles the simple status string; the caller
        should check incomplete_details separately for 'max_output_tokens'.
        """
        _MAP = {
            "completed": "stop",
            "incomplete": "length",
            "failed": "stop",
            "cancelled": "stop",
        }
        return _MAP.get(raw_reason, "stop")


# Auto-register on import
from agent.transports import register_transport  # noqa: E402

register_transport("codex_responses", ResponsesApiTransport)
