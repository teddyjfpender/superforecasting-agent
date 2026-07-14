"""GitHub App user OAuth with PKCE and encrypted token persistence."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from urllib.parse import urlencode, urlsplit

from forecasting.change_control.collaboration import bind_identity
from forecasting.change_control.trace_archive import parse_workspace_key
from forecasting.models import LedgerNotFoundError, ValidationError, utc_now_iso


def _aesgcm():
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    return AESGCM


def _seal(value: str, key: bytes, *, aad: str) -> str:
    nonce = os.urandom(12)
    ciphertext = _aesgcm()(key).encrypt(nonce, value.encode("utf-8"), aad.encode("utf-8"))
    return json.dumps(
        {
            "version": 1,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def _open(value: str, key: bytes, *, aad: str) -> str:
    envelope = json.loads(value)
    plaintext = _aesgcm()(key).decrypt(
        base64.b64decode(envelope["nonce"]),
        base64.b64decode(envelope["ciphertext"]),
        aad.encode("utf-8"),
    )
    return plaintext.decode("utf-8")


def _response_json(response: Any) -> dict[str, Any]:
    response.raise_for_status()
    value = response.json()
    if not isinstance(value, dict):
        raise ValidationError("GitHub returned an invalid response")
    return value


class GitHubOAuthService:
    def __init__(
        self,
        ledger: Any,
        *,
        client_id: str,
        client_secret: str,
        token_key: bytes | str,
        api_url: str = "https://api.github.com",
        api_version: str = "2026-03-10",
        state_ttl_seconds: int = 600,
        http_post: Callable[..., Any] | None = None,
        http_get: Callable[..., Any] | None = None,
    ) -> None:
        if not client_id or not client_secret:
            raise ValidationError("GitHub App client_id and client_secret are required")
        parsed = urlsplit(api_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValidationError("GitHub api_url must be HTTPS")
        self.ledger = ledger
        self.client_id = client_id
        self.client_secret = client_secret
        self.key = parse_workspace_key(token_key)
        self.api_url = api_url.rstrip("/")
        self.api_version = api_version
        self.state_ttl_seconds = max(60, int(state_ttl_seconds))
        if http_post is None or http_get is None:
            import httpx

            http_post = http_post or httpx.post
            http_get = http_get or httpx.get
        self.http_post = http_post
        self.http_get = http_get

    def begin(
        self,
        *,
        owner_id: str,
        slack_team_id: str,
        slack_user_id: str,
        agent_instance_id: str,
        agent_persona: str,
        redirect_uri: str,
        agent_avatar_url: str | None = None,
        slack_bot_user_id: str | None = None,
    ) -> dict[str, str]:
        parsed = urlsplit(redirect_uri)
        if parsed.scheme != "https" or not parsed.hostname or parsed.fragment:
            raise ValidationError("GitHub OAuth redirect_uri must be an HTTPS URL")
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        state_hash = hashlib.sha256(state.encode()).hexdigest()
        now = datetime.now(timezone.utc)
        expires = (now + timedelta(seconds=self.state_ttl_seconds)).isoformat().replace(
            "+00:00", "Z"
        )
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_oauth_states (
                       state_hash, owner_id, slack_team_id, slack_user_id,
                       agent_instance_id, agent_persona, agent_avatar_url,
                       slack_bot_user_id, redirect_uri, verifier_ciphertext,
                       expires_at, created_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    state_hash,
                    owner_id,
                    slack_team_id,
                    slack_user_id,
                    agent_instance_id,
                    agent_persona,
                    agent_avatar_url,
                    slack_bot_user_id,
                    redirect_uri,
                    _seal(verifier, self.key, aad=f"oauth-state:{state_hash}"),
                    expires,
                    utc_now_iso(),
                ),
            )
        query = urlencode(
            {
                "client_id": self.client_id,
                "redirect_uri": redirect_uri,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            }
        )
        return {"authorization_url": f"https://github.com/login/oauth/authorize?{query}", "state": state}

    def complete(self, *, state: str, code: str, redirect_uri: str) -> dict[str, Any]:
        state_hash = hashlib.sha256(str(state).encode()).hexdigest()
        with self.ledger.transaction(immediate=True):
            with self.ledger._connect() as conn:
                row = conn.execute(
                    "SELECT * FROM github_oauth_states WHERE state_hash = ?", (state_hash,)
                ).fetchone()
                if row is None or row["consumed_at"] is not None:
                    raise ValidationError("GitHub OAuth state is invalid or already used")
                if row["redirect_uri"] != redirect_uri:
                    raise ValidationError("GitHub OAuth callback URI does not match")
                if row["expires_at"] <= utc_now_iso():
                    raise ValidationError("GitHub OAuth state expired")
                conn.execute(
                    "UPDATE github_oauth_states SET consumed_at = ? WHERE state_hash = ?",
                    (utc_now_iso(), state_hash),
                )
            state_row = dict(row)
        verifier = _open(
            state_row["verifier_ciphertext"], self.key, aad=f"oauth-state:{state_hash}"
        )
        try:
            token_data = _response_json(
                self.http_post(
                    "https://github.com/login/oauth/access_token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "code": code,
                        "redirect_uri": redirect_uri,
                        "code_verifier": verifier,
                    },
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
            )
        except Exception:
            raise ValidationError("GitHub OAuth token exchange failed") from None
        access_token = str(token_data.get("access_token") or "")
        if not access_token:
            raise ValidationError("GitHub token exchange did not return an access token")
        try:
            user = _response_json(
                self.http_get(
                    f"{self.api_url}/user",
                    headers=self._headers(access_token),
                    timeout=15,
                )
            )
        except Exception:
            raise ValidationError("GitHub authenticated-user lookup failed") from None
        if not user.get("id") or not user.get("node_id") or not user.get("login"):
            raise ValidationError("GitHub authenticated-user response lacks immutable identity fields")
        binding = bind_identity(
            self.ledger,
            owner_id=state_row["owner_id"],
            slack_team_id=state_row["slack_team_id"],
            slack_user_id=state_row["slack_user_id"],
            agent_instance_id=state_row["agent_instance_id"],
            agent_persona=state_row["agent_persona"],
            agent_avatar_url=state_row["agent_avatar_url"],
            slack_bot_user_id=state_row["slack_bot_user_id"],
            github_user_id=str(user["id"]),
            github_node_id=str(user["node_id"]),
            github_login=str(user["login"]),
        )
        self._store_tokens(binding["id"], token_data)
        return binding

    def _store_tokens(self, binding_id: str, token_data: dict[str, Any]) -> None:
        token_id = f"ghtoken_{uuid.uuid4().hex[:16]}"
        now = datetime.now(timezone.utc)
        expires_at = _expiry(now, token_data.get("expires_in"))
        refresh_expires_at = _expiry(now, token_data.get("refresh_token_expires_in"))
        access = _seal(
            str(token_data["access_token"]), self.key, aad=f"github-token:{binding_id}:access"
        )
        refresh_raw = token_data.get("refresh_token")
        refresh = (
            _seal(str(refresh_raw), self.key, aad=f"github-token:{binding_id}:refresh")
            if refresh_raw
            else None
        )
        timestamp = utc_now_iso()
        with self.ledger._connect() as conn:
            conn.execute(
                """INSERT INTO github_user_tokens (
                       id, identity_binding_id, access_ciphertext, refresh_ciphertext,
                       expires_at, refresh_expires_at, token_type, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(identity_binding_id) DO UPDATE SET
                       access_ciphertext = excluded.access_ciphertext,
                       refresh_ciphertext = excluded.refresh_ciphertext,
                       expires_at = excluded.expires_at,
                       refresh_expires_at = excluded.refresh_expires_at,
                       token_type = excluded.token_type,
                       status = 'active', revoked_at = NULL,
                       updated_at = excluded.updated_at""",
                (
                    token_id,
                    binding_id,
                    access,
                    refresh,
                    expires_at,
                    refresh_expires_at,
                    str(token_data.get("token_type") or "bearer"),
                    timestamp,
                    timestamp,
                ),
            )

    def control_plane_token(self, binding_id: str) -> str:
        """Return a token only to trusted control-plane callers, never a sandbox response."""

        with self.ledger._connect() as conn:
            row = conn.execute(
                """SELECT * FROM github_user_tokens
                   WHERE identity_binding_id = ? AND status = 'active'""",
                (binding_id,),
            ).fetchone()
        if row is None:
            raise LedgerNotFoundError("no active delegated GitHub token")
        if row["expires_at"] and row["expires_at"] <= utc_now_iso():
            self.refresh(binding_id)
            return self.control_plane_token(binding_id)
        return _open(
            row["access_ciphertext"], self.key, aad=f"github-token:{binding_id}:access"
        )

    def refresh(self, binding_id: str) -> None:
        with self.ledger._connect() as conn:
            row = conn.execute(
                """SELECT * FROM github_user_tokens
                   WHERE identity_binding_id = ? AND status = 'active'""",
                (binding_id,),
            ).fetchone()
        if row is None or not row["refresh_ciphertext"]:
            raise ValidationError("delegated GitHub token cannot be refreshed")
        if row["refresh_expires_at"] and row["refresh_expires_at"] <= utc_now_iso():
            raise ValidationError("delegated GitHub refresh token expired")
        refresh_token = _open(
            row["refresh_ciphertext"], self.key, aad=f"github-token:{binding_id}:refresh"
        )
        try:
            token_data = _response_json(
                self.http_post(
                    "https://github.com/login/oauth/access_token",
                    data={
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "grant_type": "refresh_token",
                        "refresh_token": refresh_token,
                    },
                    headers={"Accept": "application/json"},
                    timeout=15,
                )
            )
        except Exception:
            raise ValidationError("GitHub delegated-token refresh failed") from None
        if not token_data.get("access_token"):
            raise ValidationError("GitHub refresh did not return an access token")
        self._store_tokens(binding_id, token_data)

    def revoke_local(self, binding_id: str) -> None:
        with self.ledger._connect() as conn:
            conn.execute(
                """UPDATE github_user_tokens SET status = 'revoked', revoked_at = ?, updated_at = ?
                   WHERE identity_binding_id = ?""",
                (utc_now_iso(), utc_now_iso(), binding_id),
            )

    def _headers(self, token: str) -> dict[str, str]:
        return {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": self.api_version,
        }


def _expiry(now: datetime, seconds: Any) -> str | None:
    if seconds is None:
        return None
    return (now + timedelta(seconds=max(0, int(seconds)))).isoformat().replace("+00:00", "Z")


__all__ = ["GitHubOAuthService"]
