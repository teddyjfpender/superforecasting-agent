"""Session telegram_schema operations behind the SessionDB API."""


def apply_telegram_topic_migration(self) -> None:
    """Create Telegram DM topic-mode tables on explicit /topic opt-in.

    This migration is deliberately not part of automatic SessionDB startup
    reconciliation. Operators must be able to upgrade Superforecasting
    Agent, keep the old Telegram bot behavior running, and only mutate
    topic-mode state when the user executes /topic to opt into the feature.

    Schema versions:
      v1 — initial shape (no ON DELETE CASCADE on session_id FK)
      v2 — session_id FK gets ON DELETE CASCADE so session pruning
           automatically clears bindings.
    """

    def _do(conn):
        conn.executescript(
            """
                CREATE TABLE IF NOT EXISTS telegram_dm_topic_mode (
                    chat_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    activated_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    has_topics_enabled INTEGER,
                    allows_users_to_create_topics INTEGER,
                    capability_checked_at REAL,
                    intro_message_id TEXT,
                    pinned_message_id TEXT
                );

                CREATE TABLE IF NOT EXISTS telegram_dm_topic_bindings (
                    chat_id TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    session_key TEXT NOT NULL,
                    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                    managed_mode TEXT NOT NULL DEFAULT 'auto',
                    linked_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (chat_id, thread_id)
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_telegram_dm_topic_bindings_session
                ON telegram_dm_topic_bindings(session_id);

                CREATE INDEX IF NOT EXISTS idx_telegram_dm_topic_bindings_user
                ON telegram_dm_topic_bindings(user_id, chat_id);
                """
        )
        # v1 → v2: rebuild telegram_dm_topic_bindings if its session_id FK
        # lacks ON DELETE CASCADE. SQLite can't ALTER a foreign key, so we
        # rebuild the table. Only runs once per DB (version gate).
        current = conn.execute(
            "SELECT value FROM state_meta WHERE key = ?",
            ("telegram_dm_topic_schema_version",),
        ).fetchone()
        current_version = (
            int(current[0]) if current and str(current[0]).isdigit() else 0
        )
        if current_version < 2:
            fk_rows = conn.execute(
                "PRAGMA foreign_key_list('telegram_dm_topic_bindings')"
            ).fetchall()
            needs_rebuild = any(
                row[2] == "sessions" and (row[6] or "") != "CASCADE" for row in fk_rows
            )
            if needs_rebuild:
                conn.executescript(
                    """
                        CREATE TABLE telegram_dm_topic_bindings_new (
                            chat_id TEXT NOT NULL,
                            thread_id TEXT NOT NULL,
                            user_id TEXT NOT NULL,
                            session_key TEXT NOT NULL,
                            session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                            managed_mode TEXT NOT NULL DEFAULT 'auto',
                            linked_at REAL NOT NULL,
                            updated_at REAL NOT NULL,
                            PRIMARY KEY (chat_id, thread_id)
                        );
                        INSERT INTO telegram_dm_topic_bindings_new
                            SELECT chat_id, thread_id, user_id, session_key,
                                   session_id, managed_mode, linked_at, updated_at
                            FROM telegram_dm_topic_bindings;
                        DROP TABLE telegram_dm_topic_bindings;
                        ALTER TABLE telegram_dm_topic_bindings_new
                            RENAME TO telegram_dm_topic_bindings;
                        CREATE UNIQUE INDEX idx_telegram_dm_topic_bindings_session
                            ON telegram_dm_topic_bindings(session_id);
                        CREATE INDEX idx_telegram_dm_topic_bindings_user
                            ON telegram_dm_topic_bindings(user_id, chat_id);
                        """
                )
        conn.execute(
            "INSERT INTO state_meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            ("telegram_dm_topic_schema_version", "2"),
        )

    self._execute_write(_do)
