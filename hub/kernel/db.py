#!/usr/bin/env python3
"""
# 20200001  kernel.db — SQLite connection and schema bootstrap
Hub kernel: database layer.
All DB access goes through this module. No inline SQL in handlers.
"""
import hashlib
import os
import sqlite3
import secrets
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]  # hub/
DB_PATH = os.environ.get('HUB_DB', str(BASE_DIR.parent / 'db' / 'server.db'))

# 20200301  db_conn — open SQLite connection, row_factory=Row
def db_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

# 20200302  db_ensure_tables — create all tables + seed admin user
def db_ensure_tables():
    try:
        conn = db_conn()
        conn.execute("""CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            display TEXT,
            password_hash TEXT NOT NULL,
            role TEXT DEFAULT 'admin',
            created TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS hub_config (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS journal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            type TEXT NOT NULL,
            body TEXT NOT NULL,
            user TEXT DEFAULT ''
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS port_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            data TEXT NOT NULL
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS port_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            event TEXT NOT NULL,
            port INTEGER NOT NULL,
            process TEXT DEFAULT '',
            container TEXT DEFAULT '',
            acknowledged INTEGER DEFAULT 0
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS activity_log (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            ts      TEXT NOT NULL,
            source  TEXT NOT NULL DEFAULT 'system',
            category TEXT NOT NULL DEFAULT 'general',
            action  TEXT NOT NULL,
            detail  TEXT DEFAULT '',
            level   TEXT NOT NULL DEFAULT 'info'
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            category TEXT DEFAULT '',
            key TEXT UNIQUE NOT NULL,
            value TEXT,
            updated TEXT
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS issues (
            id TEXT PRIMARY KEY,
            service TEXT,
            title TEXT,
            body TEXT,
            status TEXT DEFAULT 'open',
            created INTEGER,
            updated INTEGER
        )""")
        conn.execute("""CREATE TABLE IF NOT EXISTS incidents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            body TEXT,
            severity TEXT DEFAULT 'info',
            created_at TEXT DEFAULT (datetime('now'))
        )""")
        # Seed default admin if no users exist
        row = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()
        if row['c'] == 0:
            h = hashlib.sha256(b'admin').hexdigest()
            conn.execute("INSERT INTO users (username,display,password_hash,role,created) VALUES (?,?,?,?,?)",
                ('admin','Administrator',h,'admin',datetime.now().isoformat()))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f'  DB init error: {e}')
