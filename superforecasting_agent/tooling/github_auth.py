"""GitHub authentication shared by skill source adapters."""

import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Dict, Optional

import httpx

logger = logging.getLogger("tools.skills_hub")

class GitHubAuth:
    """
    GitHub API authentication. Tries methods in priority order:
      1. GITHUB_TOKEN / GH_TOKEN env var (PAT — the default)
      2. `gh auth token` subprocess (if gh CLI is installed)
      3. GitHub App JWT + installation token (if app credentials configured)
      4. Unauthenticated (60 req/hr, public repos only)
    """

    def __init__(self):
        self._cached_token: Optional[str] = None
        self._cached_method: Optional[str] = None
        self._app_token_expiry: float = 0

    def get_headers(self) -> Dict[str, str]:
        """Return authorization headers for GitHub API requests."""
        token = self._resolve_token()
        headers = {"Accept": "application/vnd.github.v3+json"}
        if token:
            headers["Authorization"] = f"token {token}"
        return headers

    def is_authenticated(self) -> bool:
        return self._resolve_token() is not None

    def auth_method(self) -> str:
        """Return which auth method is active: 'pat', 'gh-cli', 'github-app', or 'anonymous'."""
        self._resolve_token()
        return self._cached_method or "anonymous"

    def _resolve_token(self) -> Optional[str]:
        # Return cached token if still valid
        if self._cached_token:
            if self._cached_method != "github-app" or time.time() < self._app_token_expiry:
                return self._cached_token

        # 1. Environment variable
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            self._cached_token = token
            self._cached_method = "pat"
            return token

        # 2. gh CLI
        token = self._try_gh_cli()
        if token:
            self._cached_token = token
            self._cached_method = "gh-cli"
            return token

        # 3. GitHub App
        token = self._try_github_app()
        if token:
            self._cached_token = token
            self._cached_method = "github-app"
            self._app_token_expiry = time.time() + 3500  # ~58 min (tokens last 1 hour)
            return token

        self._cached_method = "anonymous"
        return None

    def _try_gh_cli(self) -> Optional[str]:
        """Try to get a token from the gh CLI."""
        try:
            result = subprocess.run(
                ["gh", "auth", "token"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired) as e:
            logger.debug("gh CLI token lookup failed: %s", e)
        return None

    def _try_github_app(self) -> Optional[str]:
        """Try GitHub App JWT authentication if credentials are configured."""
        app_id = os.environ.get("GITHUB_APP_ID")
        key_path = os.environ.get("GITHUB_APP_PRIVATE_KEY_PATH")
        installation_id = os.environ.get("GITHUB_APP_INSTALLATION_ID")

        if not all([app_id, key_path, installation_id]):
            return None

        try:
            import jwt  # PyJWT
        except ImportError:
            logger.debug("PyJWT not installed, skipping GitHub App auth")
            return None

        try:
            key_file = Path(key_path)
            if not key_file.exists():
                return None
            private_key = key_file.read_text(encoding="utf-8")

            now = int(time.time())
            payload = {
                "iat": now - 60,
                "exp": now + (10 * 60),
                "iss": app_id,
            }
            encoded_jwt = jwt.encode(payload, private_key, algorithm="RS256")

            resp = httpx.post(
                f"https://api.github.com/app/installations/{installation_id}/access_tokens",
                headers={
                    "Authorization": f"Bearer {encoded_jwt}",
                    "Accept": "application/vnd.github.v3+json",
                },
                timeout=10,
            )
            if resp.status_code == 201:
                return resp.json().get("token")
        except Exception as e:
            logger.debug(f"GitHub App auth failed: {e}")

        return None
