"""Durable ownership must agree across processes without network discovery."""

import hashlib
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent.storage import process_identity as identity


def test_linux_identity_uses_boot_and_pid_namespace(tmp_path, monkeypatch):
    boot = tmp_path / "boot"
    boot.write_text("11111111-1111-1111-1111-111111111111\n", encoding="ascii")
    namespace = SimpleNamespace(st_ino=73)
    monkeypatch.setattr(identity, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(identity, "Path", lambda path: boot)
    monkeypatch.setattr(identity, "os", SimpleNamespace(stat=lambda path: namespace))
    network = Mock(side_effect=AssertionError("network identity must not be consulted"))
    monkeypatch.setattr(identity.uuid, "getnode", network)
    first = identity.host_identity()
    assert identity.host_identity() == first
    namespace.st_ino = 74
    assert identity.host_identity() != first
    namespace.st_ino = 73
    boot.write_text("22222222-2222-2222-2222-222222222222\n", encoding="ascii")
    assert identity.host_identity() != first
    boot.unlink()
    with pytest.raises(RuntimeError, match="boot and PID namespace"):
        identity.host_identity()
    network.assert_not_called()


def test_network_fallback_preserves_real_identity_but_rejects_random_node(monkeypatch):
    monkeypatch.setattr(identity, "sys", SimpleNamespace(platform="win32"))
    monkeypatch.setattr(identity.socket, "gethostname", lambda: "fixture-host")
    node = 0x020000000001
    monkeypatch.setattr(identity.uuid, "getnode", lambda: node)
    assert identity.host_identity() == hashlib.sha256(f"fixture-host:{node}".encode()).hexdigest()
    monkeypatch.setattr(identity.uuid, "getnode", lambda: 0x010000000001)
    with pytest.raises(RuntimeError, match="No stable machine identity"):
        identity.host_identity()
