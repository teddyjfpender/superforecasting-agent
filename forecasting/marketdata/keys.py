"""Server-side API-key resolution for market-data providers.

Keys live in the ONE shared secret store the whole desk uses — the process env
populated from ``~/.superforecasting-agent/.env`` (``forecasting.api_keys`` /
``/api-key`` write it, ``load_forecast_dotenv`` loads it into ``os.environ`` at
gateway boot). This module maps a market-data provider slug to its env var and
reads it, so the TUI stops reading env keys itself (Arc C) and the agent and the
tape resolve the SAME key.

Absence is ``None`` (never ``""``): a keyed provider with no key is simply
skipped by the service, exactly as the client skipped it.
"""

from __future__ import annotations

import os

# provider slug -> env var (mirrors ``keyEnv`` in ui-tui marketProviders.ts).
PROVIDER_ENV: dict[str, str] = {
    "fred": "FRED_API_KEY",
    "bls": "BLS_API_KEY",
    "bea": "BEA_API_KEY",
}


def resolve_key(provider: str, *, env: dict[str, str] | None = None) -> str | None:
    """The provider's API key, or ``None`` when unset / keyless.

    ``env`` is injectable for tests; it defaults to ``os.environ`` so a key
    added via ``forecast api-key set`` (already in the process env) is picked up
    without a restart.
    """

    env_var = PROVIDER_ENV.get((provider or "").strip().lower())
    if not env_var:
        return None
    source = os.environ if env is None else env
    value = source.get(env_var)
    value = value.strip() if isinstance(value, str) else value
    return value or None


__all__ = ["PROVIDER_ENV", "resolve_key"]
