"""MySQL persistence for bot data (Railway compatible)."""

import os
import time
import mysql.connector
from urllib.parse import urlparse


# ---------- CONNECTION ----------

def get_conn():
    url = urlparse(os.getenv("DATABASE_URL"))

    return mysql.connector.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.path.lstrip("/"),
        autocommit=False,
    )


# ---------- INIT DB ----------

def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            chat_id BIGINT PRIMARY KEY,
            rules TEXT,
            welcome_enabled INT DEFAULT 1,
            goodbye_enabled INT DEFAULT 1,
            welcome_msg TEXT,
            goodbye_msg TEXT,
            log_channel_id BIGINT,
            warn_limit INT DEFAULT 3,
            antiflood_count INT DEFAULT 5,
            antiflood_seconds INT DEFAULT 60
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance (
            chat_id BIGINT,
            chat_title TEXT,
            chat_type TEXT,
            user_id BIGINT,
            username TEXT,
            full_name TEXT,
            date VARCHAR(32),
            weekday INT,
            created_at BIGINT,
            PRIMARY KEY (chat_id, user_id, date)
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        CREATE INDEX idx_attendance_date ON attendance(date);
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS attendance_whitelist (
            user_id BIGINT PRIMARY KEY,
            label TEXT NOT NULL,
            username TEXT,
            full_name TEXT,
            created_at BIGINT
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS warns (
            chat_id BIGINT,
            user_id BIGINT,
            admin_id BIGINT,
            reason TEXT,
            created_at BIGINT,
            PRIMARY KEY (chat_id, user_id, created_at)
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            chat_id BIGINT,
            user_id BIGINT,
            note TEXT,
            admin_id BIGINT,
            created_at BIGINT,
            PRIMARY KEY (chat_id, user_id)
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS banned_words (
            chat_id BIGINT,
            word TEXT,
            PRIMARY KEY (chat_id, word(255))
        ) ENGINE=InnoDB;
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_messages (
            chat_id BIGINT,
            user_id BIGINT,
            timestamp DOUBLE,
            PRIMARY KEY (chat_id, user_id, timestamp)
        ) ENGINE=InnoDB;
    """)

    conn.commit()
    cursor.close()
    conn.close()


# ---------- DATABASE CLASS ----------

class Database:
    def __init__(self):
        init_db()

    # ---------- GROUPS ----------

    def get_group(self, chat_id: int):
        conn = get_conn()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM groups WHERE chat_id = %s", (chat_id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row

    def set_group(self, chat_id: int, **kwargs):
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute("SELECT 1 FROM groups WHERE chat_id = %s", (chat_id,))
        exists = cursor.fetchone()

        if exists:
            cols = ", ".join(f"{k} = %s" for k in kwargs)
            values = list(kwargs.values()) + [chat_id]
            cursor.execute(f"UPDATE groups SET {cols} WHERE chat_id = %s", values)
        else:
            columns = ["chat_id"] + list(kwargs.keys())
            placeholders = ", ".join(["%s"] * len(columns))
            cursor.execute(
                f"INSERT INTO groups ({', '.join(columns)}) VALUES ({placeholders})",
                [chat_id] + list(kwargs.values())
            )

        conn.commit()
        cursor.close()
        conn.close()

    def get_rules(self, chat_id: int):
        group = self.get_group(chat_id)
        return group["rules"] if group else None

    def set_rules(self, chat_id: int, rules: str):
        self.set_group(chat_id, rules=rules)

    # ---------- WARNS ----------

    def add_warn(self, chat_id, user_id, admin_id, reason):
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute(
            "INSERT INTO warns (chat_id, user_id, admin_id, reason, created_at) VALUES (%s, %s, %s, %s, %s)",
            (chat_id, user_id, admin_id, reason or "No reason", int(time.time()))
        )

        cursor.execute(
            "SELECT COUNT(*) FROM warns WHERE chat_id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        count = cursor.fetchone()[0]

        conn.commit()
        cursor.close()
        conn.close()
        return count

    def warn_count(self, chat_id, user_id):
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM warns WHERE chat_id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        count = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return count

    # ---------- NOTES ----------

    def set_note(self, chat_id, user_id, note, admin_id):
        conn = get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            REPLACE INTO notes (chat_id, user_id, note, admin_id, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (chat_id, user_id, note, admin_id, int(time.time())))

        conn.commit()
        cursor.close()
        conn.close()

    def get_note(self, chat_id, user_id):
        conn = get_conn()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT note FROM notes WHERE chat_id = %s AND user_id = %s",
            (chat_id, user_id)
        )
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        return row[0] if row else None
