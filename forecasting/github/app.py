"""GitHub App installation authentication kept inside the control plane."""

from __future__ import annotations

import base64
import json
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

from forecasting.models import ValidationError


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


class GitHubAppClient:
    """Perform repository-bound App calls without exposing JWTs or tokens."""

    def __init__(
        self,
        *,
        app_id: str,
        private_key: str | bytes,
        installation_id: str,
        repository_slug: str,
        request: Callable[..., Any] | None = None,
        api_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        clock: Callable[[], float] = time.time,
    ) -> None:
        if not str(app_id).strip() or not str(installation_id).strip():
            raise ValidationError("GitHub App and installation IDs are required")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository_slug):
            raise ValidationError("repository_slug must use owner/repository form")
        parsed = urlsplit(api_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValidationError("GitHub api_url must be HTTPS")
        self.app_id = str(app_id)
        self.private_key = private_key.encode() if isinstance(private_key, str) else private_key
        self.installation_id = str(installation_id)
        self.repository_slug = repository_slug
        self.api_url = api_url.rstrip("/")
        self.api_version = api_version
        self.clock = clock
        self._token: str | None = None
        self._token_expires_at = 0.0
        if request is None:
            import httpx

            request = httpx.request
        self.request = request

    def call(
        self,
        action: str,
        method: str,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        expected_statuses: tuple[int, ...] = (),
    ) -> dict[str, Any]:
        method = method.upper()
        check_path = f"/repos/{self.repository_slug}/check-runs"
        if action != "check.write" or method != "POST" or path != check_path:
            raise PermissionError("GitHub App client only permits repository promotion checks")
        token = self._installation_access_token()
        kwargs: dict[str, Any] = {
            "headers": {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": self.api_version,
            },
            "timeout": 20,
        }
        if body is not None:
            kwargs["json"] = dict(body)
        try:
            response = self.request(method, f"{self.api_url}{path}", **kwargs)
            status_code = int(response.status_code)
            if status_code not in expected_statuses:
                response.raise_for_status()
            value = response.json()
            return {
                "status_code": status_code,
                "body": _redact(value if isinstance(value, Mapping) else {}),
            }
        except Exception:
            raise RuntimeError("GitHub App promotion-check request failed") from None

    def _installation_access_token(self) -> str:
        now = self.clock()
        if self._token and now < self._token_expires_at - 60:
            return self._token
        response = self.request(
            "POST",
            f"{self.api_url}/app/installations/{self.installation_id}/access_tokens",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self._jwt(now)}",
                "X-GitHub-Api-Version": self.api_version,
            },
            timeout=20,
        )
        try:
            response.raise_for_status()
            value = response.json()
        except Exception:
            raise RuntimeError("GitHub App installation authorization failed") from None
        token = str(value.get("token") or "") if isinstance(value, Mapping) else ""
        if not token:
            raise ValidationError("GitHub App installation token response was invalid")
        self._token = token
        self._token_expires_at = _timestamp(value.get("expires_at"), default=now + 300)
        return token

    def _jwt(self, now: float) -> str:
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import padding

        header = _b64(json.dumps({"alg": "RS256", "typ": "JWT"}, separators=(",", ":")).encode())
        payload = _b64(
            json.dumps(
                {"iat": int(now) - 60, "exp": int(now) + 540, "iss": self.app_id},
                separators=(",", ":"),
            ).encode()
        )
        message = f"{header}.{payload}".encode()
        try:
            key = serialization.load_pem_private_key(self.private_key, password=None)
            signature = key.sign(message, padding.PKCS1v15(), hashes.SHA256())
        except Exception as exc:
            raise ValidationError("GitHub App private key is invalid") from exc
        return f"{message.decode()}.{_b64(signature)}"


def _timestamp(value: Any, *, default: float) -> float:
    if not value:
        return default
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc
        ).timestamp()
    except (TypeError, ValueError):
        return default


def _redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]"
            if str(key).lower() in {"token", "access_token", "authorization"}
            else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


__all__ = ["GitHubAppClient"]
