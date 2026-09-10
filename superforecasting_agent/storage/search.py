"""Session search operations behind the SessionDB API."""

import sqlite3
from typing import Any, Dict, List


def search_messages(
    self,
    query: str,
    source_filter: List[str] = None,
    exclude_sources: List[str] = None,
    role_filter: List[str] = None,
    limit: int = 20,
    offset: int = 0,
    sort: str = None,
) -> List[Dict[str, Any]]:
    """
        Full-text search across session messages using FTS5.

        Supports FTS5 query syntax:
          - Simple keywords: "docker deployment"
          - Phrases: '"exact phrase"'
          - Boolean: "docker OR kubernetes", "python NOT java"
          - Prefix: "deploy*"

        Returns matching messages with session metadata, content snippet,
        and surrounding context (1 message before and after the match).

        ``sort`` controls temporal ordering:
          - ``None`` (default): FTS5 BM25 relevance only. Time-neutral.
          - ``"newest"``: order by message timestamp DESC, then by rank.
          - ``"oldest"``: order by message timestamp ASC, then by rank.

        The short-CJK LIKE fallback already orders by timestamp DESC and
        ignores ``sort``. The trigram CJK path honours ``sort`` like the main
        FTS5 path.
        """
    if not query or not query.strip():
        return []
    query = self._sanitize_fts5_query(query)
    if not query:
        return []
    # Normalise sort. Anything not in the allowed set falls back to None
    # (FTS5 rank-only) so callers can pass through user input without
    # validation.
    if isinstance(sort, str):
        sort_norm = sort.strip().lower()
        if sort_norm not in ("newest", "oldest"):
            sort_norm = None
    else:
        sort_norm = None
    # ORDER BY shared across the main FTS5 path and trigram CJK path.
    # With sort set, timestamp is primary and rank is the tiebreaker.
    if sort_norm == "newest":
        order_by_sql = "ORDER BY m.timestamp DESC, rank"
    elif sort_norm == "oldest":
        order_by_sql = "ORDER BY m.timestamp ASC, rank"
    else:
        order_by_sql = "ORDER BY rank"
    # Build WHERE clauses dynamically
    where_clauses = ["messages_fts MATCH ?"]
    params: list = [query]
    if source_filter is not None:
        source_placeholders = ",".join("?" for _ in source_filter)
        where_clauses.append(f"s.source IN ({source_placeholders})")
        params.extend(source_filter)
    if exclude_sources is not None:
        exclude_placeholders = ",".join("?" for _ in exclude_sources)
        where_clauses.append(f"s.source NOT IN ({exclude_placeholders})")
        params.extend(exclude_sources)
    if role_filter:
        role_placeholders = ",".join("?" for _ in role_filter)
        where_clauses.append(f"m.role IN ({role_placeholders})")
        params.extend(role_filter)
    where_sql = " AND ".join(where_clauses)
    params.extend([limit, offset])
    sql = f"""
            SELECT
                m.id,
                m.session_id,
                m.role,
                snippet(messages_fts, 0, '>>>', '<<<', '...', 40) AS snippet,
                m.content,
                m.timestamp,
                m.tool_name,
                s.source,
                s.model,
                s.started_at AS session_started
            FROM messages_fts
            JOIN messages m ON m.id = messages_fts.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE {where_sql}
            {order_by_sql}
            LIMIT ? OFFSET ?
        """
    # CJK queries bypass the unicode61 FTS5 table.  The default tokenizer
    # splits CJK characters into individual tokens, so "大别山项目" becomes
    # "大 AND 别 AND 山 AND 项 AND 目" — producing false positives and
    # missing exact phrase matches.
    #
    # For queries with 3+ CJK characters, we use the trigram FTS5 table
    # (indexed substring matching with ranking and snippets).  For shorter
    # CJK queries (1-2 chars), trigram can't match (it needs ≥9 UTF-8
    # bytes = 3 CJK chars), so we fall back to LIKE.
    is_cjk = self._contains_cjk(query)
    if is_cjk:
        raw_query = query.strip('"').strip()
        cjk_count = self._count_cjk(raw_query)
        # Per-token CJK length check (#20494): trigram needs >=3 CJK chars
        # per token. A query like "广西 OR 桂林 OR 漓江" has cjk_count=6
        # (>=3) but each individual token is only 2 chars — trigram returns 0.
        # Route to LIKE when any non-operator CJK token is <3 CJK chars.
        _tokens_for_check = [
            t for t in raw_query.split()
            if t.upper() not in {"AND", "OR", "NOT"} and self._contains_cjk(t)
        ]
        _any_short_cjk = any(
            self._count_cjk(t) < 3 for t in _tokens_for_check
        )
        if cjk_count >= 3 and not _any_short_cjk:
            # Trigram FTS5 path — quote each non-operator token to handle
            # FTS5 special chars (%, *, etc.) while preserving boolean
            # operators (AND, OR, NOT) for multi-term queries.
            tokens = raw_query.split()
            parts = []
            for tok in tokens:
                if tok.upper() in {"AND", "OR", "NOT"}:
                    parts.append(tok)
                else:
                    parts.append('"' + tok.replace('"', '""') + '"')
            trigram_query = " ".join(parts)
            tri_where = ["messages_fts_trigram MATCH ?"]
            tri_params: list = [trigram_query]
            if source_filter is not None:
                tri_where.append(f"s.source IN ({','.join('?' for _ in source_filter)})")
                tri_params.extend(source_filter)
            if exclude_sources is not None:
                tri_where.append(f"s.source NOT IN ({','.join('?' for _ in exclude_sources)})")
                tri_params.extend(exclude_sources)
            if role_filter:
                tri_where.append(f"m.role IN ({','.join('?' for _ in role_filter)})")
                tri_params.extend(role_filter)
            tri_sql = f"""
                    SELECT
                        m.id,
                        m.session_id,
                        m.role,
                        snippet(messages_fts_trigram, 0, '>>>', '<<<', '...', 40) AS snippet,
                        m.content,
                        m.timestamp,
                        m.tool_name,
                        s.source,
                        s.model,
                        s.started_at AS session_started
                    FROM messages_fts_trigram
                    JOIN messages m ON m.id = messages_fts_trigram.rowid
                    JOIN sessions s ON s.id = m.session_id
                    WHERE {' AND '.join(tri_where)}
                    {order_by_sql}
                    LIMIT ? OFFSET ?
                """
            tri_params.extend([limit, offset])
            with self._lock:
                try:
                    tri_cursor = self._conn.execute(tri_sql, tri_params)
                except sqlite3.OperationalError:
                    matches = []
                else:
                    matches = [dict(row) for row in tri_cursor.fetchall()]
        else:
            # Short / mixed CJK query: trigram cannot match tokens with
            # <3 CJK chars. Fall back to LIKE substring search.
            # For multi-token OR queries (e.g. "广西 OR 桂林 OR 漓江"),
            # build one LIKE condition per non-operator token so each term
            # is matched independently (#20494).
            non_op_tokens = [
                t for t in raw_query.split()
                if t.upper() not in {"AND", "OR", "NOT"}
            ] or [raw_query]
            token_clauses = []
            like_params: list = []
            for tok in non_op_tokens:
                esc = tok.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
                token_clauses.append(
                    "(m.content LIKE ? ESCAPE '\\' OR m.tool_name LIKE ? ESCAPE '\\' OR m.tool_calls LIKE ? ESCAPE '\\')"
                )
                like_params += [f"%{esc}%", f"%{esc}%", f"%{esc}%"]
            like_where = [f"({' OR '.join(token_clauses)})"]
            if source_filter is not None:
                like_where.append(f"s.source IN ({','.join('?' for _ in source_filter)})")
                like_params.extend(source_filter)
            if exclude_sources is not None:
                like_where.append(f"s.source NOT IN ({','.join('?' for _ in exclude_sources)})")
                like_params.extend(exclude_sources)
            if role_filter:
                like_where.append(f"m.role IN ({','.join('?' for _ in role_filter)})")
                like_params.extend(role_filter)
            like_sql = f"""
                    SELECT m.id, m.session_id, m.role,
                           substr(m.content,
                                  max(1, instr(m.content, ?) - 40),
                                  120) AS snippet,
                           m.content, m.timestamp, m.tool_name,
                           s.source, s.model, s.started_at AS session_started
                    FROM messages m
                    JOIN sessions s ON s.id = m.session_id
                    WHERE {' AND '.join(like_where)}
                    ORDER BY m.timestamp DESC
                    LIMIT ? OFFSET ?
                """
            like_params.extend([limit, offset])
            # instr() for snippet uses first search token
            like_params = [non_op_tokens[0]] + like_params
            with self._lock:
                like_cursor = self._conn.execute(like_sql, like_params)
                matches = [dict(row) for row in like_cursor.fetchall()]
    else:
        with self._lock:
            try:
                cursor = self._conn.execute(sql, params)
            except sqlite3.OperationalError:
                # FTS5 query syntax error despite sanitization — return empty
                return []
            else:
                matches = [dict(row) for row in cursor.fetchall()]
    # Add surrounding context (1 message before + after each match).
    # Done outside the lock so we don't hold it across N sequential queries.
    for match in matches:
        try:
            with self._lock:
                ctx_cursor = self._conn.execute(
                    """WITH target AS (
                               SELECT session_id, timestamp, id
                               FROM messages
                               WHERE id = ?
                           )
                           SELECT role, content
                           FROM (
                               SELECT m.id, m.timestamp, m.role, m.content
                               FROM messages m
                               JOIN target t ON t.session_id = m.session_id
                               WHERE (m.timestamp < t.timestamp)
                                  OR (m.timestamp = t.timestamp AND m.id < t.id)
                               ORDER BY m.timestamp DESC, m.id DESC
                               LIMIT 1
                           )
                           UNION ALL
                           SELECT role, content
                           FROM messages
                           WHERE id = ?
                           UNION ALL
                           SELECT role, content
                           FROM (
                               SELECT m.id, m.timestamp, m.role, m.content
                               FROM messages m
                               JOIN target t ON t.session_id = m.session_id
                               WHERE (m.timestamp > t.timestamp)
                                  OR (m.timestamp = t.timestamp AND m.id > t.id)
                               ORDER BY m.timestamp ASC, m.id ASC
                               LIMIT 1
                           )""",
                    (match["id"], match["id"]),
                )
                context_msgs = []
                for r in ctx_cursor.fetchall():
                    raw = r["content"]
                    decoded = self._decode_content(raw)
                    # Multimodal context: render a compact text-only
                    # summary for search previews.
                    if isinstance(decoded, list):
                        text_parts = [
                            p.get("text", "") for p in decoded
                            if isinstance(p, dict) and p.get("type") == "text"
                        ]
                        text = " ".join(t for t in text_parts if t).strip()
                        preview = text or "[multimodal content]"
                    elif isinstance(decoded, str):
                        preview = decoded
                    else:
                        preview = ""
                    context_msgs.append(
                        {"role": r["role"], "content": preview[:200]}
                    )
            match["context"] = context_msgs
        except Exception:
            match["context"] = []
    # Remove full content from result (snippet is enough, saves tokens)
    for match in matches:
        match.pop("content", None)
    return matches


def search_sessions(
    self,
    source: str = None,
    limit: int = 20,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    """List sessions, optionally filtered by source.

        Returns rows enriched with a computed ``last_active`` column (latest
        message timestamp for the session, falling back to ``started_at``),
        ordered by most-recently-used first.
        """
    select_with_last_active = (
        "SELECT s.*, COALESCE(m.last_active, s.started_at) AS last_active "
        "FROM sessions s "
        "LEFT JOIN ("
        "SELECT session_id, MAX(timestamp) AS last_active "
        "FROM messages GROUP BY session_id"
        ") m ON m.session_id = s.id "
    )
    with self._lock:
        if source:
            cursor = self._conn.execute(
                f"{select_with_last_active}"
                "WHERE s.source = ? "
                "ORDER BY last_active DESC, s.started_at DESC, s.id DESC LIMIT ? OFFSET ?",
                (source, limit, offset),
            )
        else:
            cursor = self._conn.execute(
                f"{select_with_last_active}"
                "ORDER BY last_active DESC, s.started_at DESC, s.id DESC LIMIT ? OFFSET ?",
                (limit, offset),
            )
        return [dict(row) for row in cursor.fetchall()]
