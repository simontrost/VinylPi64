from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

from vinylpi.paths import DB_PATH

SCHEMA_VERSION = 3
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


def _column_names(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if column not in _column_names(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS songs (
            song_key TEXT PRIMARY KEY,
            artist TEXT NOT NULL,
            title TEXT NOT NULL,
            album TEXT,
            cover_url TEXT,
            genre TEXT,
            genre_source TEXT,
            shazam_track_id TEXT,
            shazam_artist_id TEXT,
            play_count INTEGER NOT NULL DEFAULT 0 CHECK (play_count >= 0),
            duration_ms INTEGER,
            duration_minutes REAL,
            duration_source TEXT,
            measured_listen_seconds REAL,
            created_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

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
            genre TEXT,
            bg_color TEXT,
            track_id TEXT,
            artist_id TEXT,
            duration_ms INTEGER,
            discogs_release_id INTEGER,
            discogs_position TEXT,
            discogs_side TEXT,
            discogs_track_index INTEGER,
            discogs_track_count INTEGER,
            discogs_side_track_number INTEGER,
            discogs_side_track_count INTEGER,
            discogs_match_source TEXT,
            discogs_confidence REAL,
            discogs_cover_url TEXT,
            discogs_year INTEGER,
            discogs_label TEXT,
            discogs_catalog_number TEXT,
            discogs_expected_next_title TEXT,
            discogs_expected_next_artist TEXT,
            discogs_expected_next_position TEXT,
            discogs_expected_next_side TEXT,
            side_flip_prompt_active INTEGER NOT NULL DEFAULT 0,
            side_flip_from_side TEXT,
            side_flip_to_side TEXT,
            side_flip_next_title TEXT,
            side_flip_next_position TEXT,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS discogs_releases (
            release_id INTEGER PRIMARY KEY,
            instance_id INTEGER,
            folder_id INTEGER,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            year INTEGER,
            country TEXT,
            label TEXT,
            catalog_number TEXT,
            format_text TEXT,
            thumb_url TEXT,
            cover_url TEXT,
            date_added TEXT,
            details_loaded INTEGER NOT NULL DEFAULT 0,
            synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS discogs_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER NOT NULL REFERENCES discogs_releases(release_id) ON DELETE CASCADE,
            track_index INTEGER NOT NULL,
            position TEXT,
            side TEXT,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            duration_seconds INTEGER,
            normalized_title TEXT NOT NULL,
            normalized_artist TEXT NOT NULL,
            UNIQUE(release_id, track_index)
        );

        CREATE TABLE IF NOT EXISTS discogs_sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT,
            status TEXT NOT NULL DEFAULT 'never',
            message TEXT,
            last_error TEXT,
            releases_count INTEGER NOT NULL DEFAULT 0,
            tracks_count INTEGER NOT NULL DEFAULT 0,
            failed_releases INTEGER NOT NULL DEFAULT 0,
            last_synced_at INTEGER,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        INSERT OR IGNORE INTO discogs_sync_state (id) VALUES (1);

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


def _migrate_schema(conn: sqlite3.Connection) -> None:
    """Apply additive migrations without replacing the user's database."""
    for column, declaration in (
        ("genre", "TEXT"),
        ("genre_source", "TEXT"),
        ("shazam_track_id", "TEXT"),
        ("shazam_artist_id", "TEXT"),
    ):
        _add_column_if_missing(conn, "songs", column, declaration)

    for column, declaration in (
        ("genre", "TEXT"),
        ("duration_ms", "INTEGER"),
        ("discogs_release_id", "INTEGER"),
        ("discogs_position", "TEXT"),
        ("discogs_side", "TEXT"),
        ("discogs_track_index", "INTEGER"),
        ("discogs_track_count", "INTEGER"),
        ("discogs_side_track_number", "INTEGER"),
        ("discogs_side_track_count", "INTEGER"),
        ("discogs_match_source", "TEXT"),
        ("discogs_confidence", "REAL"),
        ("discogs_cover_url", "TEXT"),
        ("discogs_year", "INTEGER"),
        ("discogs_label", "TEXT"),
        ("discogs_catalog_number", "TEXT"),
        ("discogs_expected_next_title", "TEXT"),
        ("discogs_expected_next_artist", "TEXT"),
        ("discogs_expected_next_position", "TEXT"),
        ("discogs_expected_next_side", "TEXT"),
        ("side_flip_prompt_active", "INTEGER NOT NULL DEFAULT 0"),
        ("side_flip_from_side", "TEXT"),
        ("side_flip_to_side", "TEXT"),
        ("side_flip_next_title", "TEXT"),
        ("side_flip_next_position", "TEXT"),
    ):
        _add_column_if_missing(conn, "current_status", column, declaration)

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS discogs_releases (
            release_id INTEGER PRIMARY KEY,
            instance_id INTEGER,
            folder_id INTEGER,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            year INTEGER,
            country TEXT,
            label TEXT,
            catalog_number TEXT,
            format_text TEXT,
            thumb_url TEXT,
            cover_url TEXT,
            date_added TEXT,
            details_loaded INTEGER NOT NULL DEFAULT 0,
            synced_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        CREATE TABLE IF NOT EXISTS discogs_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release_id INTEGER NOT NULL REFERENCES discogs_releases(release_id) ON DELETE CASCADE,
            track_index INTEGER NOT NULL,
            position TEXT,
            side TEXT,
            title TEXT NOT NULL,
            artist TEXT NOT NULL,
            duration_seconds INTEGER,
            normalized_title TEXT NOT NULL,
            normalized_artist TEXT NOT NULL,
            UNIQUE(release_id, track_index)
        );

        CREATE TABLE IF NOT EXISTS discogs_sync_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            username TEXT,
            status TEXT NOT NULL DEFAULT 'never',
            message TEXT,
            last_error TEXT,
            releases_count INTEGER NOT NULL DEFAULT 0,
            tracks_count INTEGER NOT NULL DEFAULT 0,
            failed_releases INTEGER NOT NULL DEFAULT 0,
            last_synced_at INTEGER,
            updated_at INTEGER NOT NULL DEFAULT (strftime('%s', 'now'))
        );

        INSERT OR IGNORE INTO discogs_sync_state (id) VALUES (1);

        CREATE INDEX IF NOT EXISTS idx_songs_artist ON songs(artist);
        CREATE INDEX IF NOT EXISTS idx_songs_album ON songs(album);
        CREATE INDEX IF NOT EXISTS idx_songs_genre ON songs(genre);
        CREATE INDEX IF NOT EXISTS idx_songs_shazam_track_id ON songs(shazam_track_id);
        CREATE INDEX IF NOT EXISTS idx_songs_play_count ON songs(play_count DESC);
        CREATE INDEX IF NOT EXISTS idx_discogs_tracks_title ON discogs_tracks(normalized_title);
        CREATE INDEX IF NOT EXISTS idx_discogs_tracks_artist ON discogs_tracks(normalized_artist);
        CREATE INDEX IF NOT EXISTS idx_discogs_tracks_release ON discogs_tracks(release_id, track_index);
        CREATE INDEX IF NOT EXISTS idx_discogs_releases_title ON discogs_releases(title);
        """
    )


def init_db(db_path: Path | str | None = None) -> None:
    """Create and migrate all database tables once per process."""
    path = Path(db_path) if db_path is not None else DB_PATH
    path_key = str(path.resolve())
    if path_key in _INITIALIZED_PATHS:
        return

    with _INIT_LOCK:
        if path_key in _INITIALIZED_PATHS:
            return

        with get_connection(path) as conn:
            _create_schema(conn)
            _migrate_schema(conn)
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
