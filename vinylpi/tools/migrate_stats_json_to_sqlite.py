import json
import sqlite3
from vinylpi.paths import STATS_PATH, DB_PATH
from vinylpi.core.database import init_db, get_connection


def as_int(value, default=None):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def as_float(value, default=None):
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def migrate() -> None:
    if not STATS_PATH.exists():
        raise FileNotFoundError(f"stats.json not found: {STATS_PATH}")

    print(f"Reading: {STATS_PATH}")
    stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))

    init_db()

    songs = stats.get("songs", {})
    albums = stats.get("albums", {})
    listening = stats.get("listening", {})
    durations_cache = stats.get("durations_cache", {})
    tag_cache = stats.get("tag_cache", {})

    with get_connection() as conn:
        for song_key, song in songs.items():
            conn.execute(
                """
                INSERT INTO songs (
                    song_key,
                    artist,
                    title,
                    album,
                    cover_url,
                    play_count,
                    duration_ms,
                    duration_minutes,
                    duration_source,
                    measured_listen_seconds
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(song_key) DO UPDATE SET
                    artist = excluded.artist,
                    title = excluded.title,
                    album = COALESCE(excluded.album, songs.album),
                    cover_url = COALESCE(excluded.cover_url, songs.cover_url),
                    play_count = excluded.play_count,
                    duration_ms = COALESCE(excluded.duration_ms, songs.duration_ms),
                    duration_minutes = COALESCE(excluded.duration_minutes, songs.duration_minutes),
                    duration_source = COALESCE(excluded.duration_source, songs.duration_source),
                    measured_listen_seconds = COALESCE(excluded.measured_listen_seconds, songs.measured_listen_seconds),
                    updated_at = strftime('%s', 'now')
                """,
                (
                    song_key,
                    song.get("artist") or "",
                    song.get("title") or "",
                    song.get("album"),
                    song.get("cover_url"),
                    as_int(song.get("count"), 0),
                    as_int(song.get("duration_ms")),
                    as_float(song.get("duration_minutes")),
                    song.get("duration_source"),
                    as_float(song.get("measured_listen_seconds")),
                ),
            )

        for album, count in albums.items():
            conn.execute(
                """
                INSERT INTO album_sessions (album, session_count)
                VALUES (?, ?)
                ON CONFLICT(album) DO UPDATE SET
                    session_count = excluded.session_count,
                    updated_at = strftime('%s', 'now')
                """,
                (album, as_int(count, 0)),
            )

        conn.execute(
            """
            INSERT INTO listening_totals (
                id,
                total_seconds,
                recalculated_at,
                recalculated_from_song_counts
            )
            VALUES (1, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                total_seconds = excluded.total_seconds,
                recalculated_at = excluded.recalculated_at,
                recalculated_from_song_counts = excluded.recalculated_from_song_counts
            """,
            (
                as_float(listening.get("total_seconds"), 0.0),
                as_int(listening.get("recalculated_at")),
                1 if listening.get("recalculated_from_song_counts") else 0,
            ),
        )

        for cache_key, item in durations_cache.items():
            ms = as_int(item.get("ms"))
            minutes = as_float(item.get("minutes"))

            if not ms or minutes is None:
                continue

            conn.execute(
                """
                INSERT INTO duration_cache (
                    cache_key,
                    artist,
                    title,
                    album,
                    duration_ms,
                    duration_minutes,
                    source,
                    fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    artist = excluded.artist,
                    title = excluded.title,
                    album = excluded.album,
                    duration_ms = excluded.duration_ms,
                    duration_minutes = excluded.duration_minutes,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                (
                    cache_key,
                    item.get("artist") or "",
                    item.get("title") or "",
                    item.get("album"),
                    ms,
                    minutes,
                    item.get("source"),
                    as_int(item.get("ts")),
                ),
            )

        for cache_key, item in tag_cache.items():
            tags = item.get("tags")
            if not isinstance(tags, list):
                continue

            conn.execute(
                """
                INSERT INTO tag_cache (
                    cache_key,
                    artist,
                    title,
                    tags_json,
                    fetched_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(cache_key) DO UPDATE SET
                    artist = excluded.artist,
                    title = excluded.title,
                    tags_json = excluded.tags_json,
                    fetched_at = excluded.fetched_at
                """,
                (
                    cache_key,
                    item.get("artist") or "",
                    item.get("title") or "",
                    json.dumps(tags, ensure_ascii=False),
                    as_int(item.get("ts")),
                ),
            )

    print(f"Done. SQLite DB created/updated: {DB_PATH}")


def print_summary() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        song_count = conn.execute("SELECT COUNT(*) FROM songs").fetchone()[0]
        artist_count = conn.execute("SELECT COUNT(DISTINCT artist) FROM songs").fetchone()[0]
        album_session_count = conn.execute("SELECT COUNT(*) FROM album_sessions").fetchone()[0]
        duration_cache_count = conn.execute("SELECT COUNT(*) FROM duration_cache").fetchone()[0]
        tag_cache_count = conn.execute("SELECT COUNT(*) FROM tag_cache").fetchone()[0]
        total_seconds = conn.execute(
            "SELECT total_seconds FROM listening_totals WHERE id = 1"
        ).fetchone()[0]

    print()
    print("Summary:")
    print(f"  songs:           {song_count}")
    print(f"  artists:         {artist_count}")
    print(f"  album sessions:  {album_session_count}")
    print(f"  duration cache:  {duration_cache_count}")
    print(f"  tag cache:       {tag_cache_count}")
    print(f"  total minutes:   {round(total_seconds / 60, 2)}")


if __name__ == "__main__":
    migrate()
    print_summary()