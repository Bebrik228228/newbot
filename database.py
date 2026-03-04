"""Database module: MySQL connector for bot, auto-creates tables if needed."""

import os
import mysql.connector
from mysql.connector import errorcode

DB_URL = os.getenv("DATABASE_URL")  # должно быть типа mysql://user:pass@host:port/dbname
if not DB_URL:
    raise RuntimeError("DATABASE_URL is not set")

from urllib.parse import urlparse
url = urlparse(DB_URL)

MYSQL_CONFIG = {
    "host": url.hostname,
    "port": url.port or 3306,
    "user": url.username,
    "password": url.password,
    "database": url.path.lstrip("/"),
    "autocommit": True,
}

def get_conn():
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except mysql.connector.Error as err:
        if err.errno == errorcode.ER_BAD_DB_ERROR:
            # База не существует — создаём её и повторяем
            tmp_config = MYSQL_CONFIG.copy()
            tmp_config.pop("database")
            tmp_conn = mysql.connector.connect(**tmp_config)
            tmp_cursor = tmp_conn.cursor()
            tmp_cursor.execute(f"CREATE DATABASE `{MYSQL_CONFIG['database']}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            tmp_cursor.close()
            tmp_conn.close()
            # Теперь пробуем снова
            conn = mysql.connector.connect(**MYSQL_CONFIG)
            return conn
        else:
            raise

def init_db():
    """Создаёт все таблицы, если их ещё нет."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SET NAMES utf8mb4;")
    cursor.execute("SET FOREIGN_KEY_CHECKS=0;")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance_whitelist (
        user_id BIGINT PRIMARY KEY,
        label VARCHAR(255) NOT NULL,
        username VARCHAR(255),
        full_name VARCHAR(255),
        created_at BIGINT
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        chat_id BIGINT,
        chat_title VARCHAR(255),
        chat_type VARCHAR(50),
        user_id BIGINT,
        username VARCHAR(255),
        full_name VARCHAR(255),
        date DATE,
        weekday TINYINT,
        created_at BIGINT,
        PRIMARY KEY (chat_id, user_id, date)
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS groups (
        chat_id BIGINT PRIMARY KEY,
        rules TEXT,
        welcome_enabled TINYINT DEFAULT 1,
        goodbye_enabled TINYINT DEFAULT 1,
        welcome_msg TEXT,
        goodbye_msg TEXT,
        log_channel_id BIGINT,
        warn_limit INT DEFAULT 3,
        antiflood_count INT DEFAULT 5,
        antiflood_seconds INT DEFAULT 60
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS warns (
        chat_id BIGINT,
        user_id BIGINT,
        admin_id BIGINT,
        reason TEXT,
        created_at BIGINT,
        PRIMARY KEY (chat_id, user_id, created_at)
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notes (
        chat_id BIGINT,
        user_id BIGINT,
        note TEXT,
        admin_id BIGINT,
        created_at BIGINT,
        PRIMARY KEY (chat_id, user_id)
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS banned_words (
        chat_id BIGINT,
        word VARCHAR(255),
        PRIMARY KEY (chat_id, word)
    );
    """)
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS user_messages (
        chat_id BIGINT,
        user_id BIGINT,
        timestamp DOUBLE,
        PRIMARY KEY (chat_id, user_id, timestamp)
    );
    """)
    
    cursor.execute("SET FOREIGN_KEY_CHECKS=1;")
    cursor.close()
    conn.close()


class Database:
    def __init__(self):
        init_db()
    
    # Тут можно вставлять все методы из твоего старого database.py
    # Например: add_attendance, list_attendance_by_date, add_to_whitelist и т.д.
    # Они будут использовать get_conn() для подключения к MySQL

DB = Database()
