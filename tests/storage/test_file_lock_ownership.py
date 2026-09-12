"""Lock reentrancy follows the resource, not merely its thread-local holder."""

import threading
from types import SimpleNamespace

from superforecasting_agent.storage.locking import file_lock


def test_one_holder_does_not_skip_another_paths_kernel_lock(tmp_path):
    operations = []
    backend = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda fd, mode: operations.append((fd, mode)),
    )
    holder = threading.local()
    first = tmp_path / "one.lock"
    second = tmp_path / "two.lock"
    with file_lock(first, holder, 1, "timeout", posix=backend, windows=None):
        with file_lock(first, holder, 1, "timeout", posix=backend, windows=None):
            assert [mode for _, mode in operations] == [3]
        with file_lock(second, holder, 1, "timeout", posix=backend, windows=None):
            assert [mode for _, mode in operations] == [3, 3]
        assert [mode for _, mode in operations] == [3, 3, 4]
    assert [mode for _, mode in operations] == [3, 3, 4, 4]


def test_nested_interruption_releases_only_inner_lock(tmp_path):
    import pytest

    operations = []
    backend = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda fd, mode: operations.append((fd, mode)),
    )
    holder = threading.local()
    with file_lock(tmp_path / "one", holder, 1, "timeout", posix=backend, windows=None):
        with pytest.raises(KeyboardInterrupt):
            with file_lock(
                tmp_path / "two", holder, 1, "timeout", posix=backend, windows=None
            ):
                raise KeyboardInterrupt()
        assert [mode for _, mode in operations] == [3, 3, 4]
        with file_lock(
            tmp_path / "one", holder, 1, "timeout", posix=backend, windows=None
        ):
            assert len(operations) == 3
    assert [mode for _, mode in operations] == [3, 3, 4, 4]
    assert holder.depths == {}


def test_distinct_paths_exclude_another_process(tmp_path):
    import subprocess
    import sys
    import pytest

    pytest.importorskip("fcntl")
    paths = [tmp_path / "one", tmp_path / "two"]
    holder = threading.local()
    probe = """
import fcntl, sys
for path in sys.argv[1:]:
    with open(path, "a+") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            continue
        raise SystemExit("lock unexpectedly available")
"""
    with file_lock(paths[0], holder, 1, "timeout"):
        with file_lock(paths[1], holder, 1, "timeout"):
            result = subprocess.run(
                [sys.executable, "-c", probe, *map(str, paths)],
                capture_output=True,
                text=True,
                timeout=10,
            )
            assert result.returncode == 0, result.stdout + result.stderr


def test_inherited_holder_depth_does_not_bypass_process_lock(tmp_path, monkeypatch):
    from superforecasting_agent.storage import locking

    operations = []
    backend = SimpleNamespace(
        LOCK_EX=1,
        LOCK_NB=2,
        LOCK_UN=4,
        flock=lambda fd, mode: operations.append((fd, mode)),
    )
    holder = threading.local()
    path = tmp_path / "lock"
    holder.depths = {(100, str(path.resolve())): 1}
    monkeypatch.setattr(locking.os, "getpid", lambda: 200)
    with file_lock(path, holder, 1, "timeout", posix=backend, windows=None):
        assert [mode for _, mode in operations] == [3]
    assert [mode for _, mode in operations] == [3, 4]
    assert holder.depths == {(100, str(path.resolve())): 1}
