"""Tests for the support dump summary."""

from hermes_cli.dump import _memory_provider


def test_memory_provider_reports_off_when_generic_memory_disabled():
    config = {
        "memory": {"memory_enabled": False, "user_profile_enabled": False, "provider": ""}
    }

    assert _memory_provider(config) == "off"


def test_memory_provider_reports_builtin_when_generic_memory_enabled():
    config = {
        "memory": {"memory_enabled": True, "user_profile_enabled": False, "provider": ""}
    }

    assert _memory_provider(config) == "built-in"


def test_memory_provider_reports_external_provider_when_configured():
    config = {
        "memory": {
            "memory_enabled": False,
            "user_profile_enabled": False,
            "provider": "honcho",
        }
    }

    assert _memory_provider(config) == "honcho"
