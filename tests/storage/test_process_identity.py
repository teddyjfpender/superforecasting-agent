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
    assert (
        identity.host_identity()
        == hashlib.sha256(f"fixture-host:{node}".encode()).hexdigest()
    )
    monkeypatch.setattr(identity.uuid, "getnode", lambda: 0x010000000001)
    with pytest.raises(RuntimeError, match="No stable machine identity"):
        identity.host_identity()


@pytest.mark.parametrize(
    "value", ["", "garbage", "00000000-0000-0000-0000-000000000000"]
)
def test_macos_invalid_boot_identity_is_not_replaced_by_network(value, monkeypatch):
    monkeypatch.setattr(identity, "sys", SimpleNamespace(platform="darwin"))
    monkeypatch.setattr(
        identity.subprocess, "run", lambda *a, **kw: SimpleNamespace(stdout=value)
    )
    monkeypatch.setattr(
        identity.uuid, "getnode", Mock(side_effect=AssertionError("no fallback"))
    )
    with pytest.raises(RuntimeError, match="macOS kernel boot"):
        identity.host_identity()


def test_macos_boot_identity_survives_random_network_and_changes_on_reboot(monkeypatch):
    monkeypatch.setattr(identity, "sys", SimpleNamespace(platform="darwin"))
    probe = Mock(
        return_value=SimpleNamespace(stdout="11111111-1111-1111-1111-111111111111\n")
    )
    monkeypatch.setattr(identity.subprocess, "run", probe)
    monkeypatch.setattr(identity.uuid, "getnode", lambda: 0x010000000001)
    first = identity.host_identity()
    assert first.startswith("v2:darwin:")
    assert first == identity.host_identity()
    assert probe.call_args.kwargs["timeout"] == 2
    probe.return_value.stdout = "22222222-2222-2222-2222-222222222222"
    assert identity.host_identity() != first
    probe.side_effect = identity.subprocess.TimeoutExpired("sysctl", 2)
    with pytest.raises(RuntimeError, match="macOS kernel boot"):
        identity.host_identity()


def test_foreign_or_legacy_identity_cannot_retire_local_process(monkeypatch):
    import psutil

    monkeypatch.setattr(identity, "host_identity", lambda: "v2:darwin:current")
    inspect = Mock(side_effect=AssertionError("foreign PID must not be inspected"))
    monkeypatch.setattr(psutil, "Process", inspect)
    assert not identity.process_has_exited("old-unversioned-digest", 100, 123.0)
    assert not identity.process_has_exited("v2:darwin:other", 100, 123.0)
    inspect.assert_not_called()


def test_local_retirement_requires_positive_absence_or_pid_reuse(monkeypatch):
    import psutil

    monkeypatch.setattr(identity, "host_identity", lambda: "host")
    process = Mock()
    monkeypatch.setattr(psutil, "Process", process)
    process.return_value.create_time.return_value = 123.0
    assert not identity.process_has_exited("host", 100, 123.0)
    process.return_value.create_time.return_value = 124.0
    assert identity.process_has_exited("host", 100, 123.0)
    process.side_effect = psutil.AccessDenied(100)
    assert not identity.process_has_exited("host", 100, 123.0)
    process.side_effect = psutil.NoSuchProcess(100)
    assert identity.process_has_exited("host", 100, 123.0)
