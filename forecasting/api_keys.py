"""API-key registry + .env read/write/activate for the forecast desk.

The forecasting agent calls several data providers that work better (or only
work) with an API key — FRED becomes reliable instead of flaky, EIA stops 403s,
paid web-search backends become available. Operators have historically had to
hand-edit ``.env`` to set these. This module powers a friendlier flow
(``forecast api-key set <provider> <value>`` + a TUI ``/api-key`` slash) that
writes the key to the user's ``.env``, activates it in the running process
(``os.environ``), and lists known providers + whether a key is currently set.

Values are treated as secrets: ``list`` / ``show`` redact them.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from forecasting.models import ValidationError


@dataclass(frozen=True)
class ApiKeyProvider:
    """A known API-key slot the user can set from the agent."""

    name: str
    env_var: str
    description: str
    signup_url: str | None = None
    aliases: tuple[str, ...] = ()

    def matches(self, query: str) -> bool:
        def _norm(value: str) -> str:
            return value.strip().lower().replace("-", "_")

        q = _norm(query)
        candidates = {_norm(self.name), _norm(self.env_var), *(_norm(a) for a in self.aliases)}
        return q in candidates


# Curated list of providers the forecasting desk knows about. The registry is
# extensible — `forecast api-key set <ENV_VAR_NAME> <value>` also accepts any
# uppercase ENV-style name (treated as a custom provider) so power users aren't
# restricted to this list.
API_KEY_PROVIDERS: tuple[ApiKeyProvider, ...] = (
    ApiKeyProvider(
        name="fred",
        env_var="FRED_API_KEY",
        description="FRED — Federal Reserve Economic Data. Makes the FRED adapter use the official API (reliable; the public CSV endpoint is flaky from some networks).",
        signup_url="https://fred.stlouisfed.org/docs/api/api_key.html",
    ),
    ApiKeyProvider(
        name="eia",
        env_var="EIA_API_KEY",
        description="EIA — US Energy Information Administration. Required for EIA energy series (gasoline, crude, electricity); without it EIA imports return HTTP 403.",
        signup_url="https://www.eia.gov/opendata/register.php",
    ),
    ApiKeyProvider(
        name="bls",
        env_var="BLS_API_KEY",
        description="BLS — US Bureau of Labor Statistics (CPI, employment, wages). Optional: registering lifts the public-API limit from 25 to 500 queries/day and unlocks longer history. BLS works without it at the lower limit.",
        signup_url="https://data.bls.gov/registrationEngine/",
    ),
    ApiKeyProvider(
        name="firecrawl",
        env_var="FIRECRAWL_API_KEY",
        description="Firecrawl — paid web search + page-content extract backend. Optional; the free ddgs backend covers search-only.",
        signup_url="https://firecrawl.dev/",
    ),
    ApiKeyProvider(
        name="exa",
        env_var="EXA_API_KEY",
        description="Exa — AI-native web search + contents (paid).",
        signup_url="https://exa.ai/",
    ),
    ApiKeyProvider(
        name="parallel",
        env_var="PARALLEL_API_KEY",
        description="Parallel — AI-native web search + extract (paid).",
        signup_url="https://parallel.ai/",
        aliases=("parallel-web",),
    ),
    ApiKeyProvider(
        name="tavily",
        env_var="TAVILY_API_KEY",
        description="Tavily — research-oriented web search (paid).",
        signup_url="https://tavily.com/",
    ),
    ApiKeyProvider(
        name="brave",
        env_var="BRAVE_API_KEY",
        description="Brave Search — independent search index (paid).",
        signup_url="https://brave.com/search/api/",
        aliases=("brave-search",),
    ),
    ApiKeyProvider(
        name="anthropic",
        env_var="ANTHROPIC_API_KEY",
        description="Anthropic — Claude API (used by the agent runtime when the Anthropic provider is selected).",
        signup_url="https://console.anthropic.com/",
    ),
    ApiKeyProvider(
        name="openai",
        env_var="OPENAI_API_KEY",
        description="OpenAI — used by the OpenAI / Codex provider runtime when selected.",
        signup_url="https://platform.openai.com/account/api-keys",
    ),
    ApiKeyProvider(
        name="openrouter",
        env_var="OPENROUTER_API_KEY",
        description="OpenRouter — multi-model gateway used by the agent runtime when the OpenRouter provider is selected.",
        signup_url="https://openrouter.ai/keys",
    ),
    ApiKeyProvider(
        name="xai",
        env_var="XAI_API_KEY",
        description="xAI — Grok models used by the agent runtime when the xAI provider is selected.",
        signup_url="https://console.x.ai/",
        aliases=("grok",),
    ),
    ApiKeyProvider(
        name="census",
        env_var="CENSUS_API_KEY",
        description="US Census Bureau — required for census.gov data imports (api.census.gov rejects keyless requests).",
        signup_url="https://api.census.gov/data/key_signup.html",
    ),
    ApiKeyProvider(
        name="kalshi",
        env_var="KALSHI_ACCESS_KEY_ID",
        description="Kalshi — needed ONLY for websocket streaming (REST market data is public/keyless). Capture BOTH the access key id and the RSA private key PEM: `forecast api-key set kalshi <key-id> --pem-file key.pem`. The PEM is written 0600 into the workspace; its path is recorded in KALSHI_PRIVATE_KEY_PATH.",
        signup_url="https://kalshi.com/account/profile",
        aliases=("kalshi-ws",),
    ),
)


_ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def lookup_provider(name: str) -> ApiKeyProvider:
    """Resolve a friendly name or env-var to an :class:`ApiKeyProvider`.

    Falls back to a synthesised ``ApiKeyProvider`` when the caller passes an
    uppercase ``ENV_VAR``-style name we don't know about — so power users can
    set arbitrary keys (e.g. a self-hosted provider) without us shipping a
    registry entry first.
    """

    needle = (name or "").strip()
    if not needle:
        raise ValidationError("api-key provider name is required")
    for provider in API_KEY_PROVIDERS:
        if provider.matches(needle):
            return provider
    candidate = needle.upper().replace("-", "_")
    if not _ENV_VAR_RE.match(candidate):
        raise ValidationError(
            f"unknown api-key provider '{name}'. Run `forecast api-key list` to see known providers,"
            " or pass an UPPERCASE_ENV_NAME for a custom one."
        )
    return ApiKeyProvider(
        name=candidate.lower(),
        env_var=candidate,
        description="Custom provider (env var assigned via `forecast api-key set`).",
    )


def default_env_path() -> Path:
    """Where api-key writes land — the user-level dotenv loaded first by the runtime."""

    from hermes_cli.env_loader import get_hermes_home

    return get_hermes_home() / ".env"


def redact(value: str | None) -> str:
    if not value:
        return "(not set)"
    text = str(value)
    if len(text) <= 8:
        return "•" * len(text)
    return f"{text[:4]}…{text[-4:]} ({len(text)} chars)"


def _read_env_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    return path.read_text(encoding="utf-8", errors="replace").splitlines()


def _write_env_file(path: Path, lines: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(lines)
    if text and not text.endswith("\n"):
        text += "\n"
    # Restrict to user-only when we create or update so secrets don't sit
    # world-readable. Best-effort: chmod can fail on some filesystems.
    path.write_text(text, encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _quote_value(value: str) -> str:
    """Quote a value for .env if it contains characters python-dotenv may mis-parse."""

    if not value:
        return '""'
    if re.search(r"[\s\"'#$=]", value):
        escaped = value.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    return value


def _format_line(env_var: str, value: str) -> str:
    return f"{env_var}={_quote_value(value)}"


_ASSIGN_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Z_][A-Z0-9_]*)\s*=")


def _key_of(line: str) -> str | None:
    match = _ASSIGN_RE.match(line)
    return match.group("key") if match else None


def set_api_key(provider_name: str, value: str, *, env_path: Path | None = None) -> ApiKeyProvider:
    """Persist a key to the user's ``.env`` and activate it in this process."""

    provider = lookup_provider(provider_name)
    value = (value or "").strip()
    if not value:
        raise ValidationError("api-key value cannot be empty (use `forecast api-key unset` to clear)")
    path = env_path or default_env_path()
    lines = _read_env_file(path)
    new_lines: list[str] = []
    replaced = False
    for line in lines:
        if _key_of(line) == provider.env_var:
            if not replaced:
                new_lines.append(_format_line(provider.env_var, value))
                replaced = True
            # Drop duplicate later assignments to keep the file tidy.
            continue
        new_lines.append(line)
    if not replaced:
        new_lines.append(_format_line(provider.env_var, value))
    _write_env_file(path, new_lines)
    os.environ[provider.env_var] = value
    return provider


def unset_api_key(provider_name: str, *, env_path: Path | None = None) -> ApiKeyProvider:
    """Remove a key from the user's ``.env`` and from this process's environment."""

    provider = lookup_provider(provider_name)
    path = env_path or default_env_path()
    lines = _read_env_file(path)
    kept = [line for line in lines if _key_of(line) != provider.env_var]
    if len(kept) != len(lines):
        _write_env_file(path, kept)
    os.environ.pop(provider.env_var, None)
    return provider


def get_api_key(provider_name: str) -> str | None:
    provider = lookup_provider(provider_name)
    return os.environ.get(provider.env_var)


def list_api_keys(*, include_unset: bool = True) -> list[dict[str, object]]:
    """Return the curated provider registry with redacted current values."""

    rows: list[dict[str, object]] = []
    for provider in API_KEY_PROVIDERS:
        value = os.environ.get(provider.env_var)
        if value is None and not include_unset:
            continue
        rows.append(
            {
                "name": provider.name,
                "env_var": provider.env_var,
                "set": value is not None and value != "",
                "redacted": redact(value),
                "description": provider.description,
                "signup_url": provider.signup_url,
                "aliases": list(provider.aliases),
            }
        )
    return rows


# ── Kalshi: key id + RSA private-key PEM (websocket streaming only) ───────────
#
# Kalshi's REST market data is public, so the default keyless desk works. The
# websocket handshake, though, needs an RSA-PSS signature — which needs a key
# id AND a private key. We store the key id like any other env-var provider,
# write the PEM 0600 into the workspace, and record its path in
# ``KALSHI_PRIVATE_KEY_PATH`` so the streamer can load it. Absence → the stream
# degrades to REST polling (never an error).

KALSHI_KEY_ID_VAR = "KALSHI_ACCESS_KEY_ID"
KALSHI_PEM_PATH_VAR = "KALSHI_PRIVATE_KEY_PATH"
_KALSHI_PEM_FILENAME = "kalshi_private_key.pem"


def default_kalshi_pem_path() -> Path:
    """Where the Kalshi PEM is written — inside the workspace, beside .env."""

    return default_env_path().parent / _KALSHI_PEM_FILENAME


def set_kalshi_key(
    key_id: str,
    private_key_pem: str,
    *,
    env_path: Path | None = None,
    pem_path: Path | None = None,
) -> dict[str, str]:
    """Persist the Kalshi key id + PEM and activate both in this process.

    The PEM is written 0600; its path (plus the key id) is recorded in ``.env``
    exactly like the single-value providers, so a fresh runtime picks it up.
    """

    key_id = (key_id or "").strip()
    pem = (private_key_pem or "").strip()
    if not key_id:
        raise ValidationError("kalshi key id cannot be empty")
    if "BEGIN" not in pem or "PRIVATE KEY" not in pem:
        raise ValidationError(
            "kalshi private key must be a PEM (-----BEGIN ... PRIVATE KEY-----)"
        )
    target = pem_path or default_kalshi_pem_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    text = pem if pem.endswith("\n") else pem + "\n"
    target.write_text(text, encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:  # pragma: no cover - some filesystems reject chmod
        pass
    set_api_key(KALSHI_KEY_ID_VAR, key_id, env_path=env_path)
    set_api_key(KALSHI_PEM_PATH_VAR, str(target), env_path=env_path)
    return {"key_id_var": KALSHI_KEY_ID_VAR, "pem_path": str(target)}


def unset_kalshi_key(*, env_path: Path | None = None, remove_pem: bool = True) -> None:
    """Clear the Kalshi key id + PEM path (and optionally delete the PEM)."""

    pem = os.environ.get(KALSHI_PEM_PATH_VAR)
    unset_api_key(KALSHI_KEY_ID_VAR, env_path=env_path)
    unset_api_key(KALSHI_PEM_PATH_VAR, env_path=env_path)
    if remove_pem and pem:
        try:  # pragma: no cover - best effort
            Path(pem).unlink(missing_ok=True)
        except OSError:
            pass


def load_kalshi_credentials() -> tuple[str, str] | None:
    """Return ``(key_id, pem_text)`` when both are present, else ``None``.

    ``None`` is the polite-degradation signal the streamer checks — no key means
    REST polling, never a crash.
    """

    key_id = (os.environ.get(KALSHI_KEY_ID_VAR) or "").strip()
    pem_path = (os.environ.get(KALSHI_PEM_PATH_VAR) or "").strip()
    if not key_id or not pem_path:
        return None
    try:
        pem = Path(pem_path).read_text(encoding="utf-8")
    except OSError:
        return None
    if "PRIVATE KEY" not in pem:
        return None
    return key_id, pem


__all__ = [
    "ApiKeyProvider",
    "API_KEY_PROVIDERS",
    "default_env_path",
    "get_api_key",
    "list_api_keys",
    "lookup_provider",
    "redact",
    "set_api_key",
    "unset_api_key",
    "KALSHI_KEY_ID_VAR",
    "KALSHI_PEM_PATH_VAR",
    "default_kalshi_pem_path",
    "set_kalshi_key",
    "unset_kalshi_key",
    "load_kalshi_credentials",
]
