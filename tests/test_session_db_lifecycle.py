"""Session database resources are released even when startup fails."""

import sqlite3

import pytest

import superforecasting_agent.storage.session


def test_failed_schema_initialization_closes_connection(monkeypatch, tmp_path):
    connections = []
    real_connect = sqlite3.connect

    def connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connections.append(connection)
        return connection

    def fail_schema(self):
        raise RuntimeError("schema initialization failed")

    monkeypatch.setattr(superforecasting_agent.storage.session.sqlite3, "connect", connect)
    monkeypatch.setattr(superforecasting_agent.storage.session.SessionDB, "_init_schema", fail_schema)
    try:
        with pytest.raises(RuntimeError, match="schema initialization failed"):
            superforecasting_agent.storage.session.SessionDB(tmp_path / "state.db")
        assert len(connections) == 1
        with pytest.raises(sqlite3.ProgrammingError, match="closed"):
            connections[0].execute("SELECT 1")
    finally:
        for connection in connections:
            connection.close()


def test_default_database_tracks_active_home_after_import(tmp_path):
    import subprocess
    import sys

    # A fresh interpreter avoids the test harness's explicit DEFAULT_DB_PATH
    # override and exercises the production import-then-profile-switch path.
    result = subprocess.run([sys.executable, "-c", """
import os
import sys
from pathlib import Path
import superforecasting_agent.storage.session
for name in ('first', 'second'):
    home = Path(sys.argv[1]) / name
    os.environ['SUPERFORECASTING_AGENT_HOME'] = str(home)
    database = superforecasting_agent.storage.session.SessionDB()
    try:
        assert database.db_path == home / 'state.db', database.db_path
    finally:
        database.close()
""", str(tmp_path)], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_explicit_default_database_override_is_respected(monkeypatch, tmp_path):
    override = tmp_path / "explicit.db"
    monkeypatch.setattr(superforecasting_agent.storage.session, "DEFAULT_DB_PATH", override)
    database = superforecasting_agent.storage.session.SessionDB()
    try:
        assert database.db_path == override
    finally:
        database.close()


def test_metadata_mutation_serializes_independent_connections(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from superforecasting_agent.storage.session import SessionDB

    databases = [SessionDB(tmp_path / "state.db") for _ in range(2)]
    ready = Barrier(2)
    def increment(database):
        ready.wait(timeout=5)
        for _ in range(20):
            database.mutate_meta("counter", lambda current: str(int(current or "0") + 1))
    try:
        with ThreadPoolExecutor(max_workers=2) as workers:
            list(workers.map(increment, databases))
        assert databases[0].get_meta("counter") == "40"
        def reject(current):
            assert current == "40"
            raise ValueError("rejected update")
        with pytest.raises(ValueError, match="rejected update"):
            databases[1].mutate_meta("counter", reject)
        assert databases[0].get_meta("counter") == "40"
        with pytest.raises(TypeError, match="must return a string"):
            databases[1].mutate_meta("counter", lambda current: None)
        assert databases[0].get_meta("counter") == "40"
    finally:
        for database in databases:
            database.close()
