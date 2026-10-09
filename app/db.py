from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS chats (
    chat_id INTEGER PRIMARY KEY,
    title TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL DEFAULT '',
    pattern TEXT NOT NULL,
    match_type TEXT NOT NULL DEFAULT 'contains',
    case_sensitive INTEGER NOT NULL DEFAULT 0,
    reply TEXT NOT NULL DEFAULT '',
    cooldown_seconds INTEGER NOT NULL DEFAULT 0,
    per_user_cooldown_seconds INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at REAL NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS rule_chats (
    rule_id INTEGER NOT NULL REFERENCES rules(id) ON DELETE CASCADE,
    chat_id INTEGER NOT NULL,
    PRIMARY KEY (rule_id, chat_id)
);

CREATE TABLE IF NOT EXISTS handled (
    chat_id INTEGER NOT NULL,
    message_id INTEGER NOT NULL,
    ts REAL NOT NULL,
    PRIMARY KEY (chat_id, message_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    chat_id INTEGER NOT NULL,
    chat_title TEXT NOT NULL DEFAULT '',
    user_id INTEGER NOT NULL DEFAULT 0,
    user_name TEXT NOT NULL DEFAULT '',
    message_id INTEGER NOT NULL DEFAULT 0,
    rule_id INTEGER,
    rule_name TEXT NOT NULL DEFAULT '',
    keyword TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    reply_text TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_events_chat_ts ON events(chat_id, ts);
CREATE INDEX IF NOT EXISTS idx_events_status_ts ON events(status, ts);
CREATE INDEX IF NOT EXISTS idx_events_rule_user_ts ON events(rule_id, user_id, ts);
"""


DEFAULT_SETTINGS = {
    "paused": "false",
    "ignore_bots": "true",
    "min_seconds_between_replies_in_chat": "15",
    "max_replies_per_chat_per_minute": "3",
    "max_replies_per_chat_per_day": "50",
    "max_replies_global_per_minute": "5",
    "admin_user": "admin",
    "admin_password_hash": "",
    "telegram_api_id": "",
    "telegram_api_hash": "",
    "telegram_phone": "",
    "proxy_enabled": "false",
    "proxy_kind": "socks5",
    "proxy_host": "127.0.0.1",
    "proxy_port": "1080",
    "proxy_username": "",
    "proxy_password": "",
}


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        if self.path != ":memory:":
            self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        for key, value in DEFAULT_SETTINGS.items():
            self._conn.execute(
                "INSERT OR IGNORE INTO settings(key, value) VALUES(?, ?)",
                (key, value),
            )
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _query(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def _query_one(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Row | None:
        rows = self._query(sql, params)
        return rows[0] if rows else None

    def _exec(self, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            self._conn.commit()
            return cursor

    def setting(self, key: str, default: str | None = None) -> str | None:
        row = self._query_one("SELECT value FROM settings WHERE key = ?", (key,))
        return row["value"] if row else default

    def setting_bool(self, key: str, default: bool = False) -> bool:
        raw = self.setting(key)
        if raw is None:
            return default
        return str(raw).strip().lower() in {"1", "true", "yes", "on"}

    def setting_int(self, key: str, default: int = 0) -> int:
        raw = self.setting(key)
        try:
            return int(str(raw))
        except (TypeError, ValueError):
            return default

    def settings(self) -> dict[str, str]:
        return {row["key"]: row["value"] for row in self._query("SELECT key, value FROM settings")}

    def update_settings(self, values: Mapping[str, Any]) -> None:
        with self._lock:
            for key, value in values.items():
                self._conn.execute(
                    """
                    INSERT INTO settings(key, value) VALUES(?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (str(key), str(value)),
                )
            self._conn.commit()

    def monitored_chats(self) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM chats WHERE enabled = 1 ORDER BY title")

    def monitored_chat_ids(self) -> set[int]:
        return {int(row["chat_id"]) for row in self.monitored_chats()}

    def is_monitored(self, chat_id: int) -> bool:
        row = self._query_one("SELECT 1 FROM chats WHERE chat_id = ? AND enabled = 1", (int(chat_id),))
        return row is not None

    def all_chats(self) -> list[sqlite3.Row]:
        return self._query("SELECT * FROM chats ORDER BY enabled DESC, title")

    def upsert_chat(self, chat_id: int, title: str, enabled: bool = True) -> None:
        self._exec(
            """
            INSERT INTO chats(chat_id, title, enabled, updated_at) VALUES(?, ?, ?, ?)
            ON CONFLICT(chat_id) DO UPDATE SET
                title = excluded.title,
                enabled = excluded.enabled,
                updated_at = excluded.updated_at
            """,
            (int(chat_id), title, 1 if enabled else 0, time.time()),
        )

    def set_monitored_chats(self, selected: Sequence[tuple[int, str]]) -> None:
        now = time.time()
        with self._lock:
            self._conn.execute("UPDATE chats SET enabled = 0, updated_at = ? WHERE enabled = 1", (now,))
            for chat_id, title in selected:
                self._conn.execute(
                    """
                    INSERT INTO chats(chat_id, title, enabled, updated_at) VALUES(?, ?, 1, ?)
                    ON CONFLICT(chat_id) DO UPDATE SET
                        title = excluded.title,
                        enabled = 1,
                        updated_at = excluded.updated_at
                    """,
                    (int(chat_id), title, now),
                )
            self._conn.commit()

    def rules(self, enabled_only: bool = False) -> list[sqlite3.Row]:
        sql = "SELECT * FROM rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY id"
        return self._query(sql)

    def rule(self, rule_id: int) -> sqlite3.Row | None:
        return self._query_one("SELECT * FROM rules WHERE id = ?", (int(rule_id),))

    def create_rule(
        self,
        *,
        name: str,
        pattern: str,
        match_type: str,
        case_sensitive: bool,
        reply: str,
        cooldown_seconds: int,
        per_user_cooldown_seconds: int,
        enabled: bool,
    ) -> int:
        now = time.time()
        cursor = self._exec(
            """
            INSERT INTO rules(
                name, pattern, match_type, case_sensitive, reply,
                cooldown_seconds, per_user_cooldown_seconds, enabled,
                created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                pattern,
                match_type,
                1 if case_sensitive else 0,
                reply,
                int(cooldown_seconds),
                int(per_user_cooldown_seconds),
                1 if enabled else 0,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)

    def update_rule(
        self,
        rule_id: int,
        *,
        name: str,
        pattern: str,
        match_type: str,
        case_sensitive: bool,
        reply: str,
        cooldown_seconds: int,
        per_user_cooldown_seconds: int,
        enabled: bool,
    ) -> None:
        self._exec(
            """
            UPDATE rules SET
                name = ?, pattern = ?, match_type = ?, case_sensitive = ?,
                reply = ?, cooldown_seconds = ?, per_user_cooldown_seconds = ?,
                enabled = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                name,
                pattern,
                match_type,
                1 if case_sensitive else 0,
                reply,
                int(cooldown_seconds),
                int(per_user_cooldown_seconds),
                1 if enabled else 0,
                time.time(),
                int(rule_id),
            ),
        )

    def delete_rule(self, rule_id: int) -> None:
        self._exec("DELETE FROM rules WHERE id = ?", (int(rule_id),))

    def set_rule_chats(self, rule_id: int, chat_ids: Sequence[int]) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM rule_chats WHERE rule_id = ?", (int(rule_id),))
            for chat_id in chat_ids:
                self._conn.execute(
                    "INSERT OR IGNORE INTO rule_chats(rule_id, chat_id) VALUES(?, ?)",
                    (int(rule_id), int(chat_id)),
                )
            self._conn.commit()

    def rule_chat_ids(self, rule_id: int) -> list[int]:
        rows = self._query(
            "SELECT chat_id FROM rule_chats WHERE rule_id = ? ORDER BY chat_id",
            (int(rule_id),),
        )
        return [int(row["chat_id"]) for row in rows]

    def rules_for_chat(self, chat_id: int) -> list[sqlite3.Row]:
        return self._query(
            """
            SELECT r.* FROM rules r
            WHERE r.enabled = 1
              AND (
                  NOT EXISTS (SELECT 1 FROM rule_chats rc WHERE rc.rule_id = r.id)
                  OR EXISTS (
                      SELECT 1 FROM rule_chats rc
                      WHERE rc.rule_id = r.id AND rc.chat_id = ?
                  )
              )
            ORDER BY r.id
            """,
            (int(chat_id),),
        )

    def mark_handled(self, chat_id: int, message_id: int) -> bool:
        cursor = self._exec(
            "INSERT OR IGNORE INTO handled(chat_id, message_id, ts) VALUES(?, ?, ?)",
            (int(chat_id), int(message_id), time.time()),
        )
        return cursor.rowcount == 1

    def cleanup_handled(self, older_than: float) -> None:
        self._exec("DELETE FROM handled WHERE ts < ?", (float(older_than),))

    def add_event(
        self,
        *,
        chat_id: int,
        chat_title: str,
        user_id: int,
        user_name: str,
        message_id: int,
        rule_id: int | None,
        rule_name: str,
        keyword: str,
        status: str,
        reason: str = "",
        reply_text: str = "",
        ts: float | None = None,
    ) -> None:
        self._exec(
            """
            INSERT INTO events(
                ts, chat_id, chat_title, user_id, user_name, message_id,
                rule_id, rule_name, keyword, status, reason, reply_text
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                time.time() if ts is None else float(ts),
                int(chat_id),
                chat_title,
                int(user_id),
                user_name,
                int(message_id),
                rule_id,
                rule_name,
                keyword,
                status,
                reason,
                reply_text,
            ),
        )

    def recent_events(self, limit: int = 100, chat_id: int | None = None) -> list[sqlite3.Row]:
        limit = max(1, min(int(limit), 500))
        if chat_id is None:
            return self._query("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,))
        return self._query(
            "SELECT * FROM events WHERE chat_id = ? ORDER BY ts DESC LIMIT ?",
            (int(chat_id), limit),
        )

    def last_sent(
        self,
        *,
        chat_id: int | None = None,
        rule_id: int | None = None,
        user_id: int | None = None,
    ) -> float | None:
        clauses = ["status = 'sent'"]
        params: list[Any] = []
        if chat_id is not None:
            clauses.append("chat_id = ?")
            params.append(int(chat_id))
        if rule_id is not None:
            clauses.append("rule_id = ?")
            params.append(int(rule_id))
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(int(user_id))
        row = self._query_one(f"SELECT MAX(ts) AS ts FROM events WHERE {' AND '.join(clauses)}", params)
        if not row or row["ts"] is None:
            return None
        return float(row["ts"])

    def count_sent_since(self, since: float, chat_id: int | None = None) -> int:
        if chat_id is None:
            row = self._query_one(
                "SELECT COUNT(*) AS c FROM events WHERE status = 'sent' AND ts >= ?",
                (float(since),),
            )
        else:
            row = self._query_one(
                "SELECT COUNT(*) AS c FROM events WHERE status = 'sent' AND ts >= ? AND chat_id = ?",
                (float(since), int(chat_id)),
            )
        return int(row["c"]) if row else 0

    def count_sent_between(self, start: float, end: float) -> int:
        row = self._query_one(
            "SELECT COUNT(*) AS c FROM events WHERE status = 'sent' AND ts >= ? AND ts < ?",
            (float(start), float(end)),
        )
        return int(row["c"]) if row else 0

    def count_events_since(self, status: str, since: float) -> int:
        row = self._query_one(
            "SELECT COUNT(*) AS c FROM events WHERE status = ? AND ts >= ?",
            (status, float(since)),
        )
        return int(row["c"]) if row else 0
