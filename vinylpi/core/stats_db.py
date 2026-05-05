from __future__ import annotations

from vinylpi.core.database import get_connection, init_db


def make_song_key(artist: str, title: str) -> str:
    return f"{artist} – {title}"


def update_song_stats(
    artist: str,
    title: str,
    album: str | None = None,
    cover_url: str | None = None,
) -> None:
    """
    Increment play count for a song.

    Behaves like the old JSON logic:
    - new song -> insert with play_count = 1
    - existing song -> play_count + 1
    - album/cover_url are only filled if missing
    """
    if not artist or not title:
        return

    init_db()
    song_key = make_song_key(artist, title)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO songs (
                song_key,
                artist,
                title,
                album,
                cover_url,
                play_count,
                updated_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                1,
                strftime('%s', 'now')
            )
            ON CONFLICT(song_key) DO UPDATE SET
                play_count = songs.play_count + 1,

                album = CASE
                    WHEN (songs.album IS NULL OR songs.album = '')
                         AND excluded.album IS NOT NULL
                         AND excluded.album != ''
                    THEN excluded.album
                    ELSE songs.album
                END,

                cover_url = CASE
                    WHEN (songs.cover_url IS NULL OR songs.cover_url = '')
                         AND excluded.cover_url IS NOT NULL
                         AND excluded.cover_url != ''
                    THEN excluded.cover_url
                    ELSE songs.cover_url
                END,

                updated_at = strftime('%s', 'now')
            """,
            (song_key, artist, title, album, cover_url),
        )


def increment_album_session(album: str | None) -> None:
    """
    Increment album session count.

    This replaces the old stats["albums"][album] += 1 logic.
    """
    if not album:
        return

    init_db()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO album_sessions (
                album,
                session_count,
                updated_at
            )
            VALUES (
                ?,
                1,
                strftime('%s', 'now')
            )
            ON CONFLICT(album) DO UPDATE SET
                session_count = album_sessions.session_count + 1,
                updated_at = strftime('%s', 'now')
            """,
            (album,),
        )

def get_total_listening_seconds() -> float:
    init_db()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT total_seconds
            FROM listening_totals
            WHERE id = 1
            """
        ).fetchone()

    if row is None:
        return 0.0

    return float(row["total_seconds"] or 0.0)


def add_listening_seconds(seconds: float) -> float:
    """
    Add listening seconds to the global listening total.

    Returns the new total_seconds value.
    """
    if seconds <= 0:
        return get_total_listening_seconds()

    init_db()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO listening_totals (
                id,
                total_seconds,
                updated_at
            )
            VALUES (
                1,
                ?,
                strftime('%s', 'now')
            )
            ON CONFLICT(id) DO UPDATE SET
                total_seconds = listening_totals.total_seconds + excluded.total_seconds,
                updated_at = strftime('%s', 'now')
            """,
            (float(seconds),),
        )

        row = conn.execute(
            """
            SELECT total_seconds
            FROM listening_totals
            WHERE id = 1
            """
        ).fetchone()

    return float(row["total_seconds"] or 0.0)


def update_song_duration(
    artist: str,
    title: str,
    duration_ms: int | None,
    duration_minutes: float | None,
    duration_source: str | None,
) -> None:
    """
    Store duration info on a song row.
    """
    if not artist or not title:
        return

    init_db()
    song_key = make_song_key(artist, title)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO songs (
                song_key,
                artist,
                title,
                duration_ms,
                duration_minutes,
                duration_source,
                play_count,
                updated_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                0,
                strftime('%s', 'now')
            )
            ON CONFLICT(song_key) DO UPDATE SET
                duration_ms = excluded.duration_ms,
                duration_minutes = excluded.duration_minutes,
                duration_source = excluded.duration_source,
                updated_at = strftime('%s', 'now')
            """,
            (
                song_key,
                artist,
                title,
                duration_ms,
                duration_minutes,
                duration_source,
            ),
        )


def add_measured_seconds_to_song(
    artist: str,
    title: str,
    seconds: float,
) -> None:
    """
    Add measured listening seconds to one song.
    """
    if not artist or not title or seconds <= 0:
        return

    init_db()
    song_key = make_song_key(artist, title)

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO songs (
                song_key,
                artist,
                title,
                measured_listen_seconds,
                play_count,
                updated_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                0,
                strftime('%s', 'now')
            )
            ON CONFLICT(song_key) DO UPDATE SET
                measured_listen_seconds =
                    COALESCE(songs.measured_listen_seconds, 0) + excluded.measured_listen_seconds,
                updated_at = strftime('%s', 'now')
            """,
            (
                song_key,
                artist,
                title,
                float(seconds),
            ),
        )

def upsert_duration_cache(
    artist: str,
    title: str,
    album: str | None,
    ms: int,
    minutes: float,
    source: str | None,
) -> None:
    if not artist or not title or not ms:
        return

    init_db()

    song_key = make_song_key(artist, title)
    cache_key = song_key.casefold()

    with get_connection() as conn:
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
            VALUES (
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                ?,
                strftime('%s', 'now')
            )
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
                artist,
                title,
                album,
                int(ms),
                float(minutes),
                source,
            ),
        )



import json


def upsert_tag_cache(
    artist: str,
    title: str,
    tags: list[dict],
) -> None:
    if not artist or not title:
        return

    init_db()

    song_key = make_song_key(artist, title)
    cache_key = song_key.casefold()

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO tag_cache (
                cache_key,
                artist,
                title,
                tags_json,
                fetched_at
            )
            VALUES (
                ?,
                ?,
                ?,
                ?,
                strftime('%s', 'now')
            )
            ON CONFLICT(cache_key) DO UPDATE SET
                artist = excluded.artist,
                title = excluded.title,
                tags_json = excluded.tags_json,
                fetched_at = excluded.fetched_at
            """,
            (
                cache_key,
                artist,
                title,
                json.dumps(tags or [], ensure_ascii=False),
            ),
        )

def get_stats_snapshot() -> dict:
    """
    Read all stats from SQLite and return a dict similar to the old stats.json format.

    This is useful so the dashboard/API can later switch from:
        stats = _load_stats()

    to:
        stats = get_stats_snapshot()
    """
    init_db()

    stats = {
        "songs": {},
        "artists": {},
        "albums": {},
        "listening": {
            "total_seconds": 0.0,
        },
        "durations_cache": {},
        "tag_cache": {},
    }

    with get_connection() as conn:
        # Songs
        rows = conn.execute(
            """
            SELECT
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
            FROM songs
            ORDER BY play_count DESC, artist ASC, title ASC
            """
        ).fetchall()

        for row in rows:
            song_key = row["song_key"]

            entry = {
                "artist": row["artist"],
                "title": row["title"],
                "album": row["album"],
                "count": int(row["play_count"] or 0),
            }

            if row["cover_url"]:
                entry["cover_url"] = row["cover_url"]

            if row["duration_ms"] is not None:
                entry["duration_ms"] = int(row["duration_ms"])

            if row["duration_minutes"] is not None:
                entry["duration_minutes"] = float(row["duration_minutes"])

            if row["duration_source"]:
                entry["duration_source"] = row["duration_source"]

            if row["measured_listen_seconds"]:
                entry["measured_listen_seconds"] = float(row["measured_listen_seconds"])

            stats["songs"][song_key] = entry

            artist = row["artist"]
            stats["artists"][artist] = stats["artists"].get(artist, 0) + int(row["play_count"] or 0)

        # Album sessions
        rows = conn.execute(
            """
            SELECT album, session_count
            FROM album_sessions
            ORDER BY session_count DESC, album ASC
            """
        ).fetchall()

        for row in rows:
            stats["albums"][row["album"]] = int(row["session_count"] or 0)

        # Listening total
        row = conn.execute(
            """
            SELECT total_seconds, recalculated_at, recalculated_from_song_counts
            FROM listening_totals
            WHERE id = 1
            """
        ).fetchone()

        if row:
            stats["listening"]["total_seconds"] = float(row["total_seconds"] or 0.0)

            if row["recalculated_at"] is not None:
                stats["listening"]["recalculated_at"] = int(row["recalculated_at"])

            if row["recalculated_from_song_counts"] is not None:
                stats["listening"]["recalculated_from_song_counts"] = int(
                    row["recalculated_from_song_counts"] or 0
                )

        # Duration cache
        rows = conn.execute(
            """
            SELECT
                cache_key,
                artist,
                title,
                album,
                duration_ms,
                duration_minutes,
                source,
                fetched_at
            FROM duration_cache
            """
        ).fetchall()

        for row in rows:
            stats["durations_cache"][row["cache_key"]] = {
                "ms": int(row["duration_ms"]),
                "minutes": float(row["duration_minutes"]),
                "ts": int(row["fetched_at"] or 0),
                "artist": row["artist"],
                "title": row["title"],
                "album": row["album"],
                "source": row["source"],
            }

        # Tag cache
        rows = conn.execute(
            """
            SELECT cache_key, artist, title, tags_json, fetched_at
            FROM tag_cache
            """
        ).fetchall()

        for row in rows:
            try:
                tags = json.loads(row["tags_json"] or "[]")
            except Exception:
                tags = []

            stats["tag_cache"][row["cache_key"]] = {
                "artist": row["artist"],
                "title": row["title"],
                "tags": tags,
                "ts": int(row["fetched_at"] or 0),
            }

    return stats