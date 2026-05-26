from pathlib import Path

import pytest

from plugins.memory.holographic import HolographicMemoryProvider


@pytest.mark.parametrize(
    "home_token",
    [
        "$SUPERFORECASTING_AGENT_HOME",
        "${SUPERFORECASTING_AGENT_HOME}",
        "$FORECAST_HOME",
        "${FORECAST_HOME}",
        "$HERMES_HOME",
        "${HERMES_HOME}",
    ],
)
def test_holographic_db_path_expands_forecast_home_aliases(
    home_token: str,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    monkeypatch.setenv("SUPERFORECASTING_AGENT_HOME", str(agent_home))
    monkeypatch.delenv("FORECAST_HOME", raising=False)
    monkeypatch.delenv("HERMES_HOME", raising=False)

    provider = HolographicMemoryProvider(
        {"db_path": f"{home_token}/memory_store.db", "hrr_dim": 8}
    )
    provider.initialize("test-session")

    try:
        assert provider._store is not None
        assert provider._store.db_path == agent_home / "memory_store.db"
        assert provider._store.db_path.exists()
    finally:
        if provider._store is not None:
            provider._store._conn.close()
        provider.shutdown()
