"""Short-lived Kanban operations own their SQLite connection and transaction."""

import sqlite3
from contextlib import closing

import pytest

from superforecasting_agent.runtime import kanban_db as kb


@pytest.mark.parametrize("fail", [False, True])
def test_scoped_connection_closes_after_commit_or_rollback(tmp_path, fail):
    path = tmp_path / "board.db"
    with closing(kb.connect(path)) as setup:
        setup.execute("CREATE TABLE lifecycle_probe (value TEXT)")

    try:
        with kb.connection(path) as conn:
            conn.execute("BEGIN")
            conn.execute("INSERT INTO lifecycle_probe VALUES ('saved')")
            if fail:
                raise ValueError("abort transaction")
    except ValueError:
        assert fail

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        conn.execute("SELECT 1")
    with closing(kb.connect(path)) as reader:
        assert reader.execute("SELECT COUNT(*) FROM lifecycle_probe").fetchone()[0] == (0 if fail else 1)
