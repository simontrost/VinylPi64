from __future__ import annotations

import sqlite3

from vinylpi.paths import DB_PATH


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")

    return conn


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    with get_connection() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS songs (
                song_key TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT,
                cover_url TEXT,
                play_count INTEGER NOT NULL DEFAULT 0,
                duration_ms INTEGER,
                duration_minutes REAL,
                duration_source TEXT,
                measured_listen_seconds REAL NOT NULL DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS album_sessions (
                album TEXT PRIMARY KEY,
                session_count INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS listening_totals (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_seconds REAL NOT NULL DEFAULT 0,
                recalculated_at INTEGER,
                recalculated_from_song_counts INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS duration_cache (
                cache_key TEXT PRIMARY KEY,
                artist TEXT,
                title TEXT,
                album TEXT,
                ms INTEGER,
                minutes REAL,
                source TEXT,
                ts INTEGER
            );

            CREATE TABLE IF NOT EXISTS tag_cache (
                cache_key TEXT PRIMARY KEY,
                artist TEXT,
                title TEXT,
                tags_json TEXT NOT NULL DEFAULT '[]',
                ts INTEGER
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            INSERT OR IGNORE INTO listening_totals (
                id,
                total_seconds,
                updated_at
            )
            VALUES (
                1,
                0,
                strftime('%s', 'now')
            );
            """
        )