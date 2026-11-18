# -*- coding: utf-8 -*-
"""لایهٔ داده — SQLite با کتابخانهٔ استاندارد پایتون"""
import hashlib
import json
import os
import secrets
import sqlite3
import time

DB_PATH = os.environ.get("VAZHEBAN_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "exam.db"))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT NOT NULL,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'participant',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    exam_version TEXT NOT NULL,
    started_at INTEGER NOT NULL,
    deadline INTEGER NOT NULL,
    submitted_at INTEGER,
    status TEXT NOT NULL DEFAULT 'in_progress',
    seed INTEGER NOT NULL,
    order_json TEXT NOT NULL,
    auto_score REAL NOT NULL DEFAULT 0,
    manual_score REAL NOT NULL DEFAULT 0,
    total_score REAL NOT NULL DEFAULT 0,
    passed INTEGER,
    ip TEXT,
    UNIQUE(user_id)
);
CREATE TABLE IF NOT EXISTS answers (
    attempt_id INTEGER NOT NULL,
    qid TEXT NOT NULL,
    payload TEXT NOT NULL DEFAULT '{}',
    auto_score REAL,
    manual_score REAL,
    manual_json TEXT,
    scorer_id INTEGER,
    scored_at INTEGER,
    updated_at INTEGER NOT NULL,
    PRIMARY KEY (attempt_id, qid)
);
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempt_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    detail TEXT,
    created_at INTEGER NOT NULL
);
"""


def connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()


def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return digest.hex(), salt


def verify_password(password, stored_hash, salt):
    digest, _ = hash_password(password, salt)
    return secrets.compare_digest(digest, stored_hash)


def create_user(conn, username, display_name, password, role="participant"):
    h, s = hash_password(password)
    cur = conn.execute(
        "INSERT INTO users (username, display_name, password_hash, salt, role, active, created_at) "
        "VALUES (?,?,?,?,?,1,?)",
        (username, display_name, h, s, role, int(time.time())),
    )
    conn.commit()
    return cur.lastrowid


def set_password(conn, user_id, password):
    h, s = hash_password(password)
    conn.execute("UPDATE users SET password_hash=?, salt=? WHERE id=?", (h, s, user_id))
    conn.commit()


def get_user_by_username(conn, username):
    return conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()


def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()


def create_session(conn, user_id, days=3):
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now, now + days * 86400),
    )
    conn.commit()
    return token


def session_user(conn, token):
    if not token:
        return None
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token=? AND s.expires_at>? AND u.active=1",
        (token, int(time.time())),
    ).fetchone()
    return row


def delete_session(conn, token):
    conn.execute("DELETE FROM sessions WHERE token=?", (token,))
    conn.commit()


def log_event(conn, attempt_id, kind, detail=""):
    conn.execute(
        "INSERT INTO events (attempt_id, kind, detail, created_at) VALUES (?,?,?,?)",
        (attempt_id, kind, detail, int(time.time())),
    )
    conn.commit()
