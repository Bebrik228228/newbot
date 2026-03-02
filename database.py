"""SQLite persistence for bot data."""

import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "bot_data.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id INTEGER PRIMARY KEY,
            rules TEXT,
            welcome_enabled INTEGER DEFAULT 1,
            goodbye_enabled INTEGER DEFAULT 1,
            welcome_msg TEXT DEFAULT NULL,
            goodbye_msg TEXT DEFAULT NULL,
            log_channel_id INTEGER DEFAULT NULL,
            warn_limit INTEGER DEFAULT 3,
            antiflood_count INTEGER DEFAULT 5,
            antiflood_seconds INTEGER DEFAULT 60
        );
        CREATE TABLE IF NOT EXISTS attendance (
            chat_id INTEGER,
            chat_title TEXT,
            chat_type TEXT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            date TEXT,
            weekday INTEGER,
            created_at INTEGER,
            PRIMARY KEY (chat_id, user_id, date)
        );
        CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(date);
        CREATE TABLE IF NOT EXISTS attendance_whitelist (
            user_id INTEGER PRIMARY KEY,
            label TEXT NOT NULL,
            username TEXT,
            full_name TEXT,
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS warns (
            chat_id INTEGER,
            user_id INTEGER,
            admin_id INTEGER,
            reason TEXT,
            created_at INTEGER,
            PRIMARY KEY (chat_id, user_id, created_at)
        );
        CREATE TABLE IF NOT EXISTS notes (
            chat_id INTEGER,
            user_id INTEGER,
            note TEXT,
            admin_id INTEGER,
            created_at INTEGER,
            PRIMARY KEY (chat_id, user_id)
        );
        CREATE TABLE IF NOT EXISTS banned_words (
            chat_id INTEGER,
            word TEXT,
            PRIMARY KEY (chat_id, word)
        );
        CREATE TABLE IF NOT EXISTS user_messages (
            chat_id INTEGER,
            user_id INTEGER,
            timestamp REAL,
            PRIMARY KEY (chat_id, user_id, timestamp)
        );
    """)
    conn.commit()
    conn.close()


class Database:
    def __init__(self):
        init_db()

    def get_group(self, chat_id: int) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT * FROM groups WHERE chat_id = ?", (chat_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def set_group(self, chat_id: int, **kwargs):
        conn = get_conn()
        exists = conn.execute("SELECT 1 FROM groups WHERE chat_id = ?", (chat_id,)).fetchone()
        if exists:
            cols = ", ".join(f"{k} = ?" for k in kwargs)
            vals = list(kwargs.values()) + [chat_id]
            conn.execute(f"UPDATE groups SET {cols} WHERE chat_id = ?", vals)
        else:
            all_cols = ["chat_id"] + list(kwargs.keys())
            placeholders = ", ".join(["?"] * len(all_cols))
            conn.execute(
                f"INSERT INTO groups ({', '.join(all_cols)}) VALUES ({placeholders})",
                [chat_id] + list(kwargs.values())
            )
        conn.commit()
        conn.close()

    def get_rules(self, chat_id: int) -> str | None:
        g = self.get_group(chat_id)
        return g["rules"] if g and "rules" in g else None

    def set_rules(self, chat_id: int, rules: str):
        self.set_group(chat_id, rules=rules)

    def add_warn(self, chat_id: int, user_id: int, admin_id: int, reason: str) -> int:
        import time
        conn = get_conn()
        conn.execute(
            "INSERT INTO warns (chat_id, user_id, admin_id, reason, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, admin_id, reason or "No reason", int(time.time()))
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM warns WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()[0]
        conn.commit()
        conn.close()
        return count

    def remove_warn(self, chat_id: int, user_id: int, created_at: int):
        conn = get_conn()
        conn.execute(
            "DELETE FROM warns WHERE chat_id = ? AND user_id = ? AND created_at = ?",
            (chat_id, user_id, created_at)
        )
        conn.commit()
        conn.close()

    def get_warns(self, chat_id: int, user_id: int) -> list:
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM warns WHERE chat_id = ? AND user_id = ? ORDER BY created_at",
            (chat_id, user_id)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def warn_count(self, chat_id: int, user_id: int) -> int:
        conn = get_conn()
        c = conn.execute(
            "SELECT COUNT(*) FROM warns WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()[0]
        conn.close()
        return c

    def set_note(self, chat_id: int, user_id: int, note: str, admin_id: int):
        import time
        conn = get_conn()
        conn.execute(
            "INSERT OR REPLACE INTO notes (chat_id, user_id, note, admin_id, created_at) VALUES (?, ?, ?, ?, ?)",
            (chat_id, user_id, note, admin_id, int(time.time()))
        )
        conn.commit()
        conn.close()

    def get_note(self, chat_id: int, user_id: int) -> str | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT note FROM notes WHERE chat_id = ? AND user_id = ?",
            (chat_id, user_id)
        ).fetchone()
        conn.close()
        return row[0] if row else None

    def add_banned_word(self, chat_id: int, word: str):
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO banned_words (chat_id, word) VALUES (?, ?)", (chat_id, word.lower()))
        conn.commit()
        conn.close()

    def remove_banned_word(self, chat_id: int, word: str):
        conn = get_conn()
        conn.execute("DELETE FROM banned_words WHERE chat_id = ? AND word = ?", (chat_id, word.lower()))
        conn.commit()
        conn.close()

    def get_banned_words(self, chat_id: int) -> list:
        conn = get_conn()
        rows = conn.execute("SELECT word FROM banned_words WHERE chat_id = ?", (chat_id,)).fetchall()
        conn.close()
        return [r[0] for r in rows]

    def record_message(self, chat_id: int, user_id: int) -> int:
        import time
        conn = get_conn()
        ts = time.time()
        conn.execute(
            "INSERT INTO user_messages (chat_id, user_id, timestamp) VALUES (?, ?, ?)",
            (chat_id, user_id, ts)
        )
        g = self.get_group(chat_id)
        window = g.get("antiflood_seconds", 60) if g else 60
        conn.execute(
            "DELETE FROM user_messages WHERE chat_id = ? AND user_id = ? AND timestamp < ?",
            (chat_id, user_id, ts - window)
        )
        count = conn.execute(
            "SELECT COUNT(*) FROM user_messages WHERE chat_id = ? AND user_id = ? AND timestamp >= ?",
            (chat_id, user_id, ts - window)
        ).fetchone()[0]
        conn.commit()
        conn.close()
        return count

    def add_attendance(
        self,
        chat_id: int,
        chat_title: str | None,
        chat_type: str | None,
        user_id: int,
        username: str | None,
        full_name: str | None,
        date: str,
        weekday: int,
        created_at: int,
    ) -> bool:
        """Добавляет отметку пользователя на указанную дату.

        Возвращает True, если вставка произошла, иначе False (уже был отмечен).
        """
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO attendance
              (chat_id, chat_title, chat_type, user_id, username, full_name, date, weekday, created_at)
            VALUES
              (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                chat_id,
                chat_title,
                chat_type,
                user_id,
                username,
                full_name,
                date,
                weekday,
                created_at,
            ),
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def list_attendance_by_date(self, date: str) -> list[dict]:
        """Список отметок за дату по всем чатам. Содержит whitelist_label при наличии."""
        conn = get_conn()
        rows = conn.execute(
            """
            SELECT
              a.chat_id, a.chat_title, a.chat_type,
              a.user_id, a.username, a.full_name,
              a.date, a.weekday, a.created_at,
              w.label AS whitelist_label
            FROM attendance a
            LEFT JOIN attendance_whitelist w ON a.user_id = w.user_id
            WHERE a.date = ?
            ORDER BY a.chat_title ASC, a.chat_id ASC, a.full_name ASC, a.username ASC
            """,
            (date,),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    # ---------- Whitelist (кто может отмечаться и как подписан) ----------

    def is_in_whitelist(self, user_id: int) -> bool:
        conn = get_conn()
        row = conn.execute(
            "SELECT 1 FROM attendance_whitelist WHERE user_id = ?", (user_id,)
        ).fetchone()
        conn.close()
        return row is not None

    def add_to_whitelist(
        self, user_id: int, label: str, username: str | None = None, full_name: str | None = None
    ) -> bool:
        """Добавить в вайтлист. Возвращает True, если вставлен, False если уже был."""
        import time
        conn = get_conn()
        cur = conn.execute(
            """
            INSERT OR IGNORE INTO attendance_whitelist (user_id, label, username, full_name, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, label or str(user_id), username, full_name, int(time.time())),
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def set_whitelist_label(self, user_id: int, label: str) -> bool:
        """Изменить подпись пользователя в вайтлисте. Возвращает True, если обновлён."""
        conn = get_conn()
        cur = conn.execute(
            "UPDATE attendance_whitelist SET label = ? WHERE user_id = ?",
            (label or str(user_id), user_id),
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def remove_from_whitelist(self, user_id: int) -> bool:
        conn = get_conn()
        cur = conn.execute(
            "DELETE FROM attendance_whitelist WHERE user_id = ?", (user_id,)
        )
        conn.commit()
        changed = cur.rowcount > 0
        conn.close()
        return changed

    def get_whitelist_user(self, user_id: int) -> dict | None:
        conn = get_conn()
        row = conn.execute(
            "SELECT user_id, label, username, full_name FROM attendance_whitelist WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_whitelist(self) -> list[dict]:
        conn = get_conn()
        rows = conn.execute(
            "SELECT user_id, label, username, full_name FROM attendance_whitelist ORDER BY label"
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
