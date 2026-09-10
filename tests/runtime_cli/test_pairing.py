"""Tests for fork-native pairing command guidance."""

from argparse import Namespace
from pathlib import Path
import time

from superforecasting_agent.runtime import pairing


class _NoopPairingStore:
    pass


class _InvalidCodeStore:
    def approve_code(self, platform: str, code: str):
        return None

    def _is_locked_out(self, platform: str) -> bool:
        return False


class _LockedOutStore:
    def approve_code(self, platform: str, code: str):
        return None

    def _is_locked_out(self, platform: str) -> bool:
        return True

    def _load_json(self, path: Path) -> dict:
        return {"_lockout:telegram": time.time() + 120}

    def _rate_limit_path(self) -> Path:
        return Path("/unused/_rate_limits.json")


def test_unknown_pairing_action_uses_forecast_native_command(monkeypatch, capsys):
    import gateway.pairing as pairing_store_module

    monkeypatch.setattr(pairing_store_module, "PairingStore", _NoopPairingStore)

    pairing.pairing_command(Namespace(pairing_action=None))

    out = capsys.readouterr().out
    assert "Usage: superforecasting-agent pairing {list|approve|revoke|clear-pending}" in out
    assert "Run 'superforecasting-agent pairing --help' for details." in out
    assert "hermes pairing" not in out


def test_invalid_pairing_code_suggests_forecast_native_list_command(capsys):
    pairing._cmd_approve(_InvalidCodeStore(), "Telegram", "badcode")

    out = capsys.readouterr().out
    assert "Code 'BADCODE' not found or expired for platform 'telegram'." in out
    assert "Run 'superforecasting-agent pairing list' to see pending codes." in out
    assert "hermes pairing" not in out


def test_pairing_lockout_reset_hint_uses_display_home(monkeypatch, capsys):
    monkeypatch.setattr(
        pairing,
        "display_agent_home",
        lambda: "~/.superforecasting-agent/profiles/research",
    )

    pairing._cmd_approve(_LockedOutStore(), "Telegram", "badcode")

    out = capsys.readouterr().out
    assert "delete the '_lockout:telegram' entry" in out
    assert "~/.superforecasting-agent/profiles/research/platforms/pairing/_rate_limits.json" in out
    assert "~/.hermes" not in out
