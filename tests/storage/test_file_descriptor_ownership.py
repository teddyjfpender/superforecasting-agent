"""Failure injection for descriptor ownership before text-wrapper construction."""

import os

import pytest

from superforecasting_agent.storage import files


@pytest.mark.parametrize(
    "writer", ["configuration", "auth", "env_save", "env_remove", "env_sanitize"]
)
def test_wrapper_failure_closes_descriptor_and_preserves_target(
    tmp_path, monkeypatch, writer
):
    from superforecasting_agent.runtime import auth, config

    output = tmp_path / "output"
    output.mkdir()
    target = output / "state.json"
    original = '{"original": true}'
    if writer.startswith("env_"):
        original = "ANTHROPIC_API_KEY=fixture-original" + (
            "" if writer == "env_sanitize" else "\n"
        )
        monkeypatch.setattr(config, "get_env_path", lambda: target)
        monkeypatch.setattr(config, "is_managed", lambda: False)
        monkeypatch.setattr(config, "ensure_hermes_home", lambda: None)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "process-original")
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(auth, "_auth_file_path", lambda: target)
    opened = []

    def fail(fd, *args, **kwargs):
        identity = os.fstat(fd)
        opened.append((fd, identity.st_dev, identity.st_ino))
        raise OSError("text wrapper construction failed")

    monkeypatch.setattr(os, "fdopen", fail)
    try:
        with pytest.raises(OSError, match="text wrapper construction failed"):
            if writer == "configuration":
                files.atomic_json_write(target, {"replacement": True})
            elif writer == "auth":
                auth._save_auth_store({"providers": {}})
            elif writer == "env_save":
                config.save_env_value("ANTHROPIC_API_KEY", "replacement")
            elif writer == "env_remove":
                config.remove_env_value("ANTHROPIC_API_KEY")
            else:
                config.sanitize_env_file()
        assert target.read_text(encoding="utf-8") == original
        if writer.startswith("env_"):
            assert os.environ["ANTHROPIC_API_KEY"] == "process-original"
            assert set(output.iterdir()) == {
                target,
                target.with_name(target.name + ".lock"),
            }
        else:
            assert list(output.iterdir()) == [target]
        assert len(opened) == 1
        with pytest.raises(OSError):
            os.fstat(opened[0][0])
    finally:
        # Negative controls must never close a reused descriptor owned elsewhere.
        for fd, device, inode in opened:
            try:
                current = os.fstat(fd)
                if (current.st_dev, current.st_ino) == (device, inode):
                    os.close(fd)
            except OSError:
                pass


@pytest.mark.parametrize("interrupt", [False, True])
def test_descriptor_has_one_owner_even_when_wrapper_is_closed_early(
    tmp_path, monkeypatch, interrupt
):
    path = tmp_path / "owned.txt"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT, 0o600)
    close = os.close
    closes = []

    def record_close(target):
        closes.append(target)
        close(target)

    monkeypatch.setattr(os, "close", record_close)
    manager = files.owned_text_descriptor(fd)
    try:
        with manager as handle:
            handle.write("complete")
            handle.close()  # borrowing wrapper cannot dispose of the raw descriptor
            os.fstat(fd)
            if interrupt:
                raise KeyboardInterrupt()
    except KeyboardInterrupt:
        assert interrupt
    assert closes == [fd]
    replacement = os.open(tmp_path / "replacement.txt", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        manager.__exit__(None, None, None)  # repeated teardown is inert
        assert closes == [fd]
        os.fstat(replacement)
    finally:
        close(replacement)
