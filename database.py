import os
import pymysql
from urllib.parse import urlparse


def get_conn():
    url = os.getenv("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    url = urlparse(url)

    return pymysql.connect(
        host=url.hostname,
        port=url.port or 3306,
        user=url.username,
        password=url.password,
        database=url.path.lstrip("/"),
        charset="utf8mb4",
        autocommit=True,
        cursorclass=pymysql.cursors.DictCursor,
    )


def init_db():
    conn = get_conn()

    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS attendance (
                id INT AUTO_INCREMENT PRIMARY KEY,
                chat_id BIGINT,
                chat_title TEXT,
                chat_type TEXT,
                user_id BIGINT,
                username TEXT,
                full_name TEXT,
                date DATE,
                weekday INT,
                created_at BIGINT
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS whitelist (
                user_id BIGINT PRIMARY KEY,
                label TEXT,
                username TEXT,
                full_name TEXT
            )
            """
        )

    conn.close()


class Database:
    def __init__(self):
        init_db()

    def add_attendance(
        self,
        chat_id,
        chat_title,
        chat_type,
        user_id,
        username,
        full_name,
        date,
        weekday,
        created_at,
    ):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id FROM attendance
                WHERE user_id=%s AND date=%s
                """,
                (user_id, date),
            )

            if cur.fetchone():
                conn.close()
                return False

            cur.execute(
                """
                INSERT INTO attendance
                (chat_id, chat_title, chat_type, user_id, username, full_name, date, weekday, created_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
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

        conn.close()
        return True

    def list_attendance_by_date(self, date):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT a.*, w.label AS whitelist_label
                FROM attendance a
                LEFT JOIN whitelist w ON a.user_id = w.user_id
                WHERE a.date=%s
                ORDER BY a.chat_title
                """,
                (date,),
            )

            rows = cur.fetchall()

        conn.close()
        return rows

    def add_to_whitelist(self, user_id, label, username=None, full_name=None):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT IGNORE INTO whitelist (user_id, label, username, full_name)
                VALUES (%s,%s,%s,%s)
                """,
                (user_id, label, username, full_name),
            )

            added = cur.rowcount > 0

        conn.close()
        return added

    def remove_from_whitelist(self, user_id):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM whitelist WHERE user_id=%s",
                (user_id,),
            )

            removed = cur.rowcount > 0

        conn.close()
        return removed

    def set_whitelist_label(self, user_id, label):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE whitelist
                SET label=%s
                WHERE user_id=%s
                """,
                (label, user_id),
            )

            updated = cur.rowcount > 0

        conn.close()
        return updated

    def list_whitelist(self):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute("SELECT * FROM whitelist ORDER BY label")
            rows = cur.fetchall()

        conn.close()
        return rows

    def is_in_whitelist(self, user_id):
        conn = get_conn()

        with conn.cursor() as cur:
            cur.execute(
                "SELECT user_id FROM whitelist WHERE user_id=%s",
                (user_id,),
            )

            result = cur.fetchone()

        conn.close()
        return bool(result)
