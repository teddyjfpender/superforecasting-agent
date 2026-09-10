"""Provider error diagnostics and safe display formatting."""

import json
import re
from typing import Any, Dict, Optional


def _is_provider_stream_parse_error(self, error: BaseException) -> bool:
    """Return True for malformed provider streaming data from SDK parsers.

        Some Anthropic-compatible streaming providers can send a malformed
        event-stream frame.  The Anthropic SDK surfaces that as a plain
        ``ValueError`` such as ``expected ident at line 1 column 149``.  That
        is provider wire-format trouble, not local request validation, so it
        should follow the same retry path as a truncated JSON body.
        """
    if getattr(self, "api_mode", None) != "anthropic_messages":
        return False
    if not isinstance(error, ValueError):
        return False
    if isinstance(error, (UnicodeEncodeError, json.JSONDecodeError)):
        return False
    message = str(error).strip().lower()
    return "expected ident at line" in message


def _emit_auxiliary_failure(self, task: str, exc: BaseException) -> None:
    """Surface a compact warning for failed auxiliary work."""
    try:
        detail = self._summarize_api_error(exc)
    except Exception:
        detail = str(exc)
    detail = (detail or exc.__class__.__name__).strip()
    if len(detail) > 220:
        detail = detail[:217].rstrip() + "..."
    self._emit_warning(f"⚠ Auxiliary {task} failed: {detail}")


def _is_entitlement_failure(
    error_context: Optional[Dict[str, Any]],
    status_code: Optional[int],
) -> bool:
    """Detect subscription/entitlement 403s that masquerade as auth failures.

        Returned True only when the body text matches a known entitlement
        shape AND the status is 401/403.  Refreshing an OAuth token cannot
        fix an unsubscribed account, so callers should surface the error
        instead of looping the credential pool.

        Current matches:
          * xAI OAuth: "do not have an active Grok subscription" /
            "out of available resources" / "does not have permission" + "grok"

        Extend here for new providers as we discover them (Anthropic's
        Claude Max OAuth entitlement errors look distinct enough today that
        the existing 1M-context-beta branch handles them; revisit if other
        subscription tiers start producing the same loop signature).
        """
    if status_code not in {401, 403, None}:
        return False
    if not isinstance(error_context, dict):
        return False
    message = str(error_context.get("message") or "").lower()
    reason = str(error_context.get("reason") or "").lower()
    haystack = f"{message} {reason}"
    if not haystack.strip():
        return False
    if "do not have an active grok subscription" in haystack:
        return True
    if "out of available resources" in haystack and "grok" in haystack:
        return True
    if "does not have permission" in haystack and "grok" in haystack:
        return True
    return False


def _summarize_api_error(error: Exception) -> str:
    """Extract a human-readable one-liner from an API error.

        Handles Cloudflare HTML error pages (502, 503, etc.) by pulling the
        <title> tag instead of dumping raw HTML.  Falls back to a truncated
        str(error) for everything else.
        """
    raw = str(error)

    if (
        isinstance(error, ValueError)
        and "expected ident at line" in raw.lower()
    ):
        return f"Malformed provider streaming response: {raw[:300]}"

    # Cloudflare / proxy HTML pages: grab the <title> for a clean summary
    if "<!DOCTYPE" in raw or "<html" in raw:
        m = re.search(r"<title[^>]*>([^<]+)</title>", raw, re.IGNORECASE)
        title = m.group(1).strip() if m else "HTML error page (title not found)"
        # Also grab Cloudflare Ray ID if present
        ray = re.search(r"Cloudflare Ray ID:\s*<strong[^>]*>([^<]+)</strong>", raw)
        ray_id = ray.group(1).strip() if ray else None
        status_code = getattr(error, "status_code", None)
        parts = []
        if status_code:
            parts.append(f"HTTP {status_code}")
        parts.append(title)
        if ray_id:
            parts.append(f"Ray {ray_id}")
        return " — ".join(parts)

    # JSON body errors from OpenAI/Anthropic SDKs
    body = getattr(error, "body", None)
    if isinstance(body, dict):
        msg = body.get("error", {}).get("message") if isinstance(body.get("error"), dict) else body.get("message")
        if msg:
            status_code = getattr(error, "status_code", None)
            prefix = f"HTTP {status_code}: " if status_code else ""
            return f"{prefix}{msg[:300]}"

    # Fallback: truncate the raw string but give more room than 200 chars
    status_code = getattr(error, "status_code", None)
    prefix = f"HTTP {status_code}: " if status_code else ""
    return f"{prefix}{raw[:500]}"


def _mask_api_key_for_logs(self, key: Any) -> Optional[str]:
    # Azure Foundry Entra ID bearer providers are callables — never
    # invoke them in log paths; identify the auth surface instead.
    if callable(key) and not isinstance(key, str):
        return "<entra-id-bearer>"
    if not key:
        return None
    if len(key) <= 12:
        return "***"
    return f"{key[:8]}...{key[-4:]}"


def _clean_error_message(self, error_msg: str) -> str:
    """
        Clean up error messages for user display, removing HTML content and truncating.
        
        Args:
            error_msg: Raw error message from API or exception
            
        Returns:
            Clean, user-friendly error message
        """
    if not error_msg:
        return "Unknown error"

    # Remove HTML content (common with CloudFlare and gateway error pages)
    if error_msg.strip().startswith('<!DOCTYPE html') or '<html' in error_msg:
        return "Service temporarily unavailable (HTML error page returned)"

    # Remove newlines and excessive whitespace
    cleaned = ' '.join(error_msg.split())

    # Truncate if too long
    if len(cleaned) > 150:
        cleaned = cleaned[:150] + "..."

    return cleaned
