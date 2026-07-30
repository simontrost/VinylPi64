from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from vinylpi.paths import DB_PATH

SCHEMA_VERSION = 1
_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a configured SQLite connection for VinylPi."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path, timeout=10.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 10000")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def init_db(db_path: Path | str | None = None) -> None:
    """Create all database tables once per process and database path."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path_key = str(path.resolve())
    if path_key in _INITIALIZED_PATHS:
        return

    with _INIT_LOCK:
        if path_key in _INITIALIZED_PATHS:
            return
        with get_connection(path) as conn:
            conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS songs (
                song_key TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT,
                cover_url TEXT,
                play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
                duration_ms INTEGER,
                duration_minutes REAL,
                duration_source TEXT,
                measured_listen_seconds REAL,
                created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist);
            CREATE INDEX IF NOT EXISTS idx_songs_album ON songs(album);
            CREATE INDEX IF NOT EXISTS idx_songs_play_count ON songs(play_count DESC);

            CREATE TABLE IF NOT EXISTS artist_totals (
                artist TEXT PRIMARY KEY,
                play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS album_sessions (
                album TEXT PRIMARY KEY,
                session_count INTEGER NOT NULL DEFAULT 0 CHECK (session_count >= 0),
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS listening_totals (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                total_seconds REAL NOT NULL DEFAULT 0,
                recalculated_at INTEGER,
                recalculated_from_song_counts INTEGER NOT NULL DEFAULT 0,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS duration_cache (
                cache_key TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                album TEXT,
                duration_ms INTEGER NOT NULL,
                duration_minutes REAL NOT NULL,
                source TEXT,
                fetched_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS tag_cache (
                cache_key TEXT PRIMARY KEY,
                artist TEXT NOT NULL,
                title TEXT NOT NULL,
                tags_json TEXT NOT NULL DEFAULT '[]',
                fetched_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS album_covers (
                album TEXT PRIMARY KEY,
                artist TEXT,
                play_count INTEGER NOT NULL DEFAULT 0,
                mbid TEXT,
                cover_url TEXT,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS current_status (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                artist TEXT,
                title TEXT,
                cover_url TEXT,
                album TEXT,
                bg_color TEXT,
                track_id TEXT,
                artist_id TEXT,
                updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
            );

            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            CREATE TABLE IF NOT EXISTS legacy_imports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_name TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                imported_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
                raw_json TEXT NOT NULL,
                UNIQUE(source_sha256)
            );

            INSERT OR IGNORE INTO listening_totals (id, total_seconds)
            VALUES (1, 0);
            """
            )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (str(SCHEMA_VERSION),),
            )
        _INITIALIZED_PATHS.add(path_key)


def database_has_statistics(db_path: Path | str | None = None) -> bool:
    init_db(db_path)
    with get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM songs) AS songs,
                (SELECT COUNT(*) FROM artist_totals) AS artists,
                (SELECT COUNT(*) FROM album_sessions) AS albums,
                (SELECT total_seconds FROM listening_totals WHERE id = 1) AS total_seconds
            """
        ).fetchone()
    return bool(
        row
        and (
            int(row["songs"] or 0) > 0
            or int(row["artists"] or 0) > 0
            or int(row["albums"] or 0) > 0
            or float(row["total_seconds"] or 0.0) > 0.0
        )
    )
