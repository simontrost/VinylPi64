from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from vinylpi.core.database import get_connection, init_db


def make_song_key(artist: str, title: str) -> str:
    return f"{artist} – {title}"


def _as_int(value: Any, default: int | None = None) -> int | None:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float | None = None) -> float | None:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def update_song_stats(
    artist: str,
    title: str,
    album: str | None = None,
    cover_url: str | None = None,
    genre: str | None = None,
    shazam_track_id: str | None = None,
    shazam_artist_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    if not artist or not title:
        return

    init_db()
    song_key = make_song_key(artist, title)
    now = int(time.time())

    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO songs (
                song_key, artist, title, album, cover_url, genre, genre_source,
                shazam_track_id, shazam_artist_id, play_count, duration_ms,
                duration_minutes, duration_source, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            ON CONFLICT(song_key) DO UPDATE SET
                play_count = songs.play_count + 1,
                album = COALESCE(NULLIF(excluded.album, ''), songs.album),
                cover_url = COALESCE(NULLIF(excluded.cover_url, ''), songs.cover_url),
                genre = COALESCE(NULLIF(excluded.genre, ''), songs.genre),
                genre_source = CASE
                    WHEN excluded.genre IS NOT NULL AND excluded.genre != ''
                    THEN excluded.genre_source ELSE songs.genre_source END,
                shazam_track_id = COALESCE(NULLIF(excluded.shazam_track_id, ''), songs.shazam_track_id),
                shazam_artist_id = COALESCE(NULLIF(excluded.shazam_artist_id, ''), songs.shazam_artist_id),
                duration_ms = COALESCE(excluded.duration_ms, songs.duration_ms),
                duration_minutes = COALESCE(excluded.duration_minutes, songs.duration_minutes),
                duration_source = COALESCE(excluded.duration_source, songs.duration_source),
                updated_at = excluded.updated_at
            """,
            (
                song_key,
                artist,
                title,
                album,
                cover_url,
                genre,
                "shazam" if genre else None,
                shazam_track_id,
                shazam_artist_id,
                int(duration_ms) if duration_ms else None,
                round(int(duration_ms) / 60000.0, 2) if duration_ms else None,
                "shazam" if duration_ms else None,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO artist_totals (artist, play_count, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(artist) DO UPDATE SET
                play_count = artist_totals.play_count + 1,
                updated_at = excluded.updated_at
            """,
            (artist, now),
        )


def increment_album_session(album: str | None) -> None:
    if not album:
        return
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO album_sessions (album, session_count, updated_at)
            VALUES (?, 1, strftime('%s', 'now'))
            ON CONFLICT(album) DO UPDATE SET
                session_count = album_sessions.session_count + 1,
                updated_at = strftime('%s', 'now')
            """,
            (album,),
        )


def get_duration_cache(artist: str, title: str) -> dict | None:
    init_db()
    cache_key = make_song_key(artist, title).casefold()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT artist, title, album, duration_ms, duration_minutes, source, fetched_at
            FROM duration_cache WHERE cache_key = ?
            """,
            (cache_key,),
        ).fetchone()
    if not row:
        return None
    return {
        "ms": int(row["duration_ms"]),
        "minutes": float(row["duration_minutes"]),
        "ts": int(row["fetched_at"] or 0),
        "artist": row["artist"],
        "title": row["title"],
        "album": row["album"],
        "source": row["source"],
    }


def upsert_duration_cache(
    artist: str,
    title: str,
    album: str | None,
    ms: int,
    minutes: float,
    source: str | None,
    fetched_at: int | None = None,
) -> None:
    if not artist or not title or not ms:
        return
    init_db()
    cache_key = make_song_key(artist, title).casefold()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO duration_cache (
                cache_key, artist, title, album, duration_ms,
                duration_minutes, source, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                int(fetched_at or time.time()),
            ),
        )


def add_listening_seconds(seconds: float) -> float:
    seconds = max(0.0, float(seconds))
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE listening_totals
            SET total_seconds = total_seconds + ?, updated_at = strftime('%s', 'now')
            WHERE id = 1
            """,
            (seconds,),
        )
        row = conn.execute(
            "SELECT total_seconds FROM listening_totals WHERE id = 1"
        ).fetchone()
    return float(row["total_seconds"] or 0.0)


def update_song_duration(
    artist: str,
    title: str,
    album: str | None,
    duration_ms: int,
    duration_minutes: float,
    duration_source: str | None,
    measured_listen_seconds: float | None = None,
) -> None:
    if not artist or not title:
        return
    init_db()
    song_key = make_song_key(artist, title)
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO songs (
                song_key, artist, title, album, play_count, duration_ms,
                duration_minutes, duration_source, measured_listen_seconds, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?, ?, strftime('%s', 'now'))
            ON CONFLICT(song_key) DO UPDATE SET
                album = CASE
                    WHEN (songs.album IS NULL OR songs.album = '')
                    THEN excluded.album ELSE songs.album END,
                duration_ms = excluded.duration_ms,
                duration_minutes = excluded.duration_minutes,
                duration_source = excluded.duration_source,
                measured_listen_seconds = CASE
                    WHEN excluded.measured_listen_seconds IS NOT NULL
                    THEN excluded.measured_listen_seconds
                    ELSE songs.measured_listen_seconds END,
                updated_at = strftime('%s', 'now')
            """,
            (
                song_key,
                artist,
                title,
                album,
                int(duration_ms),
                float(duration_minutes),
                duration_source,
                measured_listen_seconds,
            ),
        )


def get_cached_tags(artist: str, title: str) -> list[dict] | None:
    init_db()
    cache_key = make_song_key(artist, title).casefold()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT tags_json FROM tag_cache WHERE cache_key = ?",
            (cache_key,),
        ).fetchone()
    if not row:
        return None
    try:
        tags = json.loads(row["tags_json"] or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return tags if isinstance(tags, list) else []


def upsert_tag_cache(
    artist: str,
    title: str,
    tags: list[dict],
    fetched_at: int | None = None,
) -> None:
    if not artist or not title:
        return
    init_db()
    cache_key = make_song_key(artist, title).casefold()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO tag_cache (cache_key, artist, title, tags_json, fetched_at)
            VALUES (?, ?, ?, ?, ?)
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
                int(fetched_at or time.time()),
            ),
        )


def write_current_status(data: dict) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO current_status (
                id, artist, title, cover_url, album, genre, bg_color,
                track_id, artist_id, duration_ms, discogs_release_id,
                discogs_position, discogs_side, discogs_track_index,
                discogs_track_count, discogs_side_track_number,
                discogs_side_track_count, discogs_match_source,
                discogs_confidence, discogs_cover_url, discogs_year,
                discogs_label, discogs_catalog_number,
                discogs_expected_next_title, discogs_expected_next_artist,
                discogs_expected_next_position, discogs_expected_next_side,
                updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                artist = excluded.artist,
                title = excluded.title,
                cover_url = excluded.cover_url,
                album = excluded.album,
                genre = excluded.genre,
                bg_color = excluded.bg_color,
                track_id = excluded.track_id,
                artist_id = excluded.artist_id,
                duration_ms = excluded.duration_ms,
                discogs_release_id = excluded.discogs_release_id,
                discogs_position = excluded.discogs_position,
                discogs_side = excluded.discogs_side,
                discogs_track_index = excluded.discogs_track_index,
                discogs_track_count = excluded.discogs_track_count,
                discogs_side_track_number = excluded.discogs_side_track_number,
                discogs_side_track_count = excluded.discogs_side_track_count,
                discogs_match_source = excluded.discogs_match_source,
                discogs_confidence = excluded.discogs_confidence,
                discogs_cover_url = excluded.discogs_cover_url,
                discogs_year = excluded.discogs_year,
                discogs_label = excluded.discogs_label,
                discogs_catalog_number = excluded.discogs_catalog_number,
                discogs_expected_next_title = excluded.discogs_expected_next_title,
                discogs_expected_next_artist = excluded.discogs_expected_next_artist,
                discogs_expected_next_position = excluded.discogs_expected_next_position,
                discogs_expected_next_side = excluded.discogs_expected_next_side,
                updated_at = excluded.updated_at
            """,
            (
                data.get("artist"),
                data.get("title"),
                data.get("cover_url"),
                data.get("album"),
                data.get("genre"),
                data.get("bg_color"),
                data.get("track_id"),
                data.get("artist_id"),
                data.get("duration_ms"),
                data.get("discogs_release_id"),
                data.get("discogs_position"),
                data.get("discogs_side"),
                data.get("discogs_track_index"),
                data.get("discogs_track_count"),
                data.get("discogs_side_track_number"),
                data.get("discogs_side_track_count"),
                data.get("discogs_match_source"),
                data.get("discogs_confidence"),
                data.get("discogs_cover_url"),
                data.get("discogs_year"),
                data.get("discogs_label"),
                data.get("discogs_catalog_number"),
                data.get("discogs_expected_next_title"),
                data.get("discogs_expected_next_artist"),
                data.get("discogs_expected_next_position"),
                data.get("discogs_expected_next_side"),
                int(time.time() * 1000),
            ),
        )


def get_current_status() -> dict | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT artist, title, cover_url, album, genre, bg_color,
                   track_id, artist_id, duration_ms, discogs_release_id,
                   discogs_position, discogs_side, discogs_track_index,
                   discogs_track_count, discogs_side_track_number,
                   discogs_side_track_count, discogs_match_source,
                   discogs_confidence, discogs_cover_url, discogs_year,
                   discogs_label, discogs_catalog_number,
                   discogs_expected_next_title, discogs_expected_next_artist,
                   discogs_expected_next_position, discogs_expected_next_side,
                   updated_at
            FROM current_status WHERE id = 1
            """
        ).fetchone()
    if not row:
        return None
    return {key: row[key] for key in row.keys()}


def upsert_album_cover(
    album: str,
    artist: str | None,
    play_count: int,
    mbid: str | None,
    cover_url: str | None,
) -> None:
    if not album:
        return
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO album_covers (album, artist, play_count, mbid, cover_url, updated_at)
            VALUES (?, ?, ?, ?, ?, strftime('%s', 'now'))
            ON CONFLICT(album) DO UPDATE SET
                artist = excluded.artist,
                play_count = excluded.play_count,
                mbid = excluded.mbid,
                cover_url = excluded.cover_url,
                updated_at = excluded.updated_at
            """,
            (album, artist, int(play_count or 0), mbid, cover_url),
        )
        if cover_url:
            conn.execute(
                """
                UPDATE songs SET cover_url = ?, updated_at = strftime('%s', 'now')
                WHERE album = ? AND (cover_url IS NULL OR cover_url = '')
                """,
                (cover_url, album),
            )


def get_stats_snapshot() -> dict:
    """Return the database content in the former stats.json shape."""
    init_db()
    stats: dict[str, Any] = {
        "songs": {},
        "artists": {},
        "albums": {},
        "listening": {"total_seconds": 0.0},
        "durations_cache": {},
        "album_covers": {},
        "tag_cache": {},
    }

    with get_connection() as conn:
        for row in conn.execute(
            """
            SELECT song_key, artist, title, album, cover_url, genre, genre_source,
                   shazam_track_id, shazam_artist_id, play_count, duration_ms,
                   duration_minutes, duration_source, measured_listen_seconds
            FROM songs ORDER BY play_count DESC, artist, title
            """
        ):
            entry: dict[str, Any] = {
                "artist": row["artist"],
                "title": row["title"],
                "album": row["album"],
                "count": int(row["play_count"] or 0),
            }
            if row["cover_url"] is not None:
                entry["cover_url"] = row["cover_url"]
            if row["genre"] is not None:
                entry["genre"] = row["genre"]
            if row["genre_source"] is not None:
                entry["genre_source"] = row["genre_source"]
            if row["shazam_track_id"] is not None:
                entry["shazam_track_id"] = row["shazam_track_id"]
            if row["shazam_artist_id"] is not None:
                entry["shazam_artist_id"] = row["shazam_artist_id"]
            if row["duration_ms"] is not None:
                entry["duration_ms"] = int(row["duration_ms"])
            if row["duration_minutes"] is not None:
                entry["duration_minutes"] = float(row["duration_minutes"])
            if row["duration_source"] is not None:
                entry["duration_source"] = row["duration_source"]
            if row["measured_listen_seconds"] is not None:
                entry["measured_listen_seconds"] = float(row["measured_listen_seconds"])
            stats["songs"][row["song_key"]] = entry

        for row in conn.execute(
            "SELECT artist, play_count FROM artist_totals ORDER BY play_count DESC, artist"
        ):
            stats["artists"][row["artist"]] = int(row["play_count"] or 0)

        for row in conn.execute(
            "SELECT album, session_count FROM album_sessions ORDER BY session_count DESC, album"
        ):
            stats["albums"][row["album"]] = int(row["session_count"] or 0)

        row = conn.execute(
            """
            SELECT total_seconds, recalculated_at, recalculated_from_song_counts
            FROM listening_totals WHERE id = 1
            """
        ).fetchone()
        if row:
            stats["listening"]["total_seconds"] = float(row["total_seconds"] or 0.0)
            if row["recalculated_at"] is not None:
                stats["listening"]["recalculated_at"] = int(row["recalculated_at"])
            stats["listening"]["recalculated_from_song_counts"] = bool(
                row["recalculated_from_song_counts"]
            )

        for row in conn.execute(
            """
            SELECT cache_key, artist, title, album, duration_ms,
                   duration_minutes, source, fetched_at FROM duration_cache
            """
        ):
            stats["durations_cache"][row["cache_key"]] = {
                "ms": int(row["duration_ms"]),
                "minutes": float(row["duration_minutes"]),
                "ts": int(row["fetched_at"] or 0),
                "artist": row["artist"],
                "title": row["title"],
                "album": row["album"],
                "source": row["source"],
            }

        for row in conn.execute(
            "SELECT album, artist, play_count, mbid, cover_url FROM album_covers"
        ):
            stats["album_covers"][row["album"]] = {
                "artist": row["artist"],
                "album": row["album"],
                "count": int(row["play_count"] or 0),
                "mbid": row["mbid"],
                "cover_url": row["cover_url"],
            }

        for row in conn.execute(
            "SELECT cache_key, artist, title, tags_json, fetched_at FROM tag_cache"
        ):
            try:
                tags = json.loads(row["tags_json"] or "[]")
            except json.JSONDecodeError:
                tags = []
            stats["tag_cache"][row["cache_key"]] = {
                "artist": row["artist"],
                "title": row["title"],
                "tags": tags,
                "ts": int(row["fetched_at"] or 0),
            }

    return stats



def get_ranked_stats(limit: int = 10) -> dict[str, Any]:
    """Return statistics directly from SQL without network lookups."""
    init_db()
    limit = max(1, min(int(limit), 100))

    with get_connection() as conn:
        top_songs = [
            {
                "artist": row["artist"],
                "title": row["title"],
                "album": row["album"],
                "genre": row["genre"],
                "count": int(row["play_count"] or 0),
                "cover_url": row["cover_url"],
                "shazam_track_id": row["shazam_track_id"],
            }
            for row in conn.execute(
                """
                SELECT artist, title, album, genre, play_count, cover_url,
                       shazam_track_id
                FROM songs
                WHERE play_count > 0
                ORDER BY play_count DESC, artist COLLATE NOCASE, title COLLATE NOCASE
                LIMIT ?
                """,
                (limit,),
            )
        ]

        top_artists = [
            {"name": row["artist"], "count": int(row["play_count"] or 0)}
            for row in conn.execute(
                """
                SELECT artist, play_count
                FROM artist_totals
                ORDER BY play_count DESC, artist COLLATE NOCASE
                LIMIT ?
                """,
                (limit,),
            )
        ]

        top_albums = [
            {"name": row["album"], "count": int(row["session_count"] or 0)}
            for row in conn.execute(
                """
                SELECT album, session_count
                FROM album_sessions
                ORDER BY session_count DESC, album COLLATE NOCASE
                LIMIT ?
                """,
                (limit,),
            )
        ]

        top_genres = [
            {"name": row["genre"], "count": int(row["weighted_plays"] or 0)}
            for row in conn.execute(
                """
                SELECT genre, SUM(play_count) AS weighted_plays
                FROM songs
                WHERE genre IS NOT NULL AND TRIM(genre) != '' AND play_count > 0
                GROUP BY genre
                ORDER BY weighted_plays DESC, genre COLLATE NOCASE
                LIMIT ?
                """,
                (limit,),
            )
        ]

        top_album_covers = [
            {
                "name": row["album"],
                "count": int(row["session_count"] or 0),
                "cover_url": row["cover_url"],
            }
            for row in conn.execute(
                """
                SELECT
                    sessions.album,
                    sessions.session_count,
                    COALESCE(
                        covers.cover_url,
                        (
                            SELECT songs.cover_url
                            FROM songs
                            WHERE songs.album = sessions.album
                              AND songs.cover_url IS NOT NULL
                              AND TRIM(songs.cover_url) != ''
                            ORDER BY songs.play_count DESC
                            LIMIT 1
                        )
                    ) AS cover_url
                FROM album_sessions AS sessions
                LEFT JOIN album_covers AS covers ON covers.album = sessions.album
                WHERE COALESCE(
                    covers.cover_url,
                    (
                        SELECT songs.cover_url
                        FROM songs
                        WHERE songs.album = sessions.album
                          AND songs.cover_url IS NOT NULL
                          AND TRIM(songs.cover_url) != ''
                        ORDER BY songs.play_count DESC
                        LIMIT 1
                    )
                ) IS NOT NULL
                ORDER BY sessions.session_count DESC, sessions.album COLLATE NOCASE
                LIMIT 10
                """
            )
        ]

        listening = conn.execute(
            "SELECT total_seconds FROM listening_totals WHERE id = 1"
        ).fetchone()

        metadata = conn.execute(
            """
            SELECT
                COUNT(*) AS songs_total,
                SUM(CASE WHEN genre IS NOT NULL AND TRIM(genre) != '' THEN 1 ELSE 0 END) AS songs_with_genre,
                SUM(CASE WHEN shazam_track_id IS NOT NULL AND TRIM(shazam_track_id) != '' THEN 1 ELSE 0 END) AS songs_with_shazam_id
            FROM songs
            """
        ).fetchone()

    total_seconds = float((listening["total_seconds"] if listening else 0.0) or 0.0)
    return {
        "top_songs": top_songs,
        "top_artists": top_artists,
        "top_albums": top_albums,
        "top_album_covers": top_album_covers,
        "top_genres": top_genres,
        "radar_genres": top_genres[:6],
        "total_minutes_listened": int(round(total_seconds / 60.0)),
        "metadata_coverage": {
            "songs_total": int(metadata["songs_total"] or 0),
            "songs_with_genre": int(metadata["songs_with_genre"] or 0),
            "songs_with_shazam_id": int(metadata["songs_with_shazam_id"] or 0),
        },
    }

def import_stats_json(
    source: Path | str,
    *,
    replace: bool = False,
    keep_raw_backup: bool = True,
) -> dict[str, Any]:
    """Import legacy stats.json data without dropping any known fields."""
    source_path = Path(source)
    raw = source_path.read_text(encoding="utf-8")
    stats = json.loads(raw)
    if not isinstance(stats, dict):
        raise ValueError("The stats JSON root must be an object")

    init_db()
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    songs = stats.get("songs") or {}
    artists = stats.get("artists") or {}
    albums = stats.get("albums") or {}
    listening = stats.get("listening") or {}
    durations = stats.get("durations_cache") or {}
    album_covers = stats.get("album_covers") or {}
    tags = stats.get("tag_cache") or {}

    with get_connection() as conn:
        if replace:
            conn.executescript(
                """
                DELETE FROM songs;
                DELETE FROM artist_totals;
                DELETE FROM album_sessions;
                DELETE FROM duration_cache;
                DELETE FROM tag_cache;
                DELETE FROM album_covers;
                DELETE FROM current_status;
                UPDATE listening_totals SET total_seconds = 0,
                    recalculated_at = NULL,
                    recalculated_from_song_counts = 0,
                    updated_at = strftime('%s', 'now') WHERE id = 1;
                """
            )

        for song_key, item in songs.items():
            if not isinstance(item, dict):
                continue
            artist = str(item.get("artist") or "")
            title = str(item.get("title") or "")
            if not artist or not title:
                continue
            conn.execute(
                """
                INSERT INTO songs (
                    song_key, artist, title, album, cover_url, genre, genre_source,
                    shazam_track_id, shazam_artist_id, play_count, duration_ms,
                    duration_minutes, duration_source, measured_listen_seconds, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(song_key) DO UPDATE SET
                    artist = excluded.artist,
                    title = excluded.title,
                    album = excluded.album,
                    cover_url = excluded.cover_url,
                    genre = excluded.genre,
                    genre_source = excluded.genre_source,
                    shazam_track_id = excluded.shazam_track_id,
                    shazam_artist_id = excluded.shazam_artist_id,
                    play_count = excluded.play_count,
                    duration_ms = excluded.duration_ms,
                    duration_minutes = excluded.duration_minutes,
                    duration_source = excluded.duration_source,
                    measured_listen_seconds = excluded.measured_listen_seconds,
                    updated_at = excluded.updated_at
                """,
                (
                    str(song_key),
                    artist,
                    title,
                    item.get("album"),
                    item.get("cover_url"),
                    item.get("genre"),
                    item.get("genre_source"),
                    item.get("shazam_track_id"),
                    item.get("shazam_artist_id"),
                    _as_int(item.get("count"), 0),
                    _as_int(item.get("duration_ms")),
                    _as_float(item.get("duration_minutes")),
                    item.get("duration_source"),
                    _as_float(item.get("measured_listen_seconds")),
                ),
            )

        if not artists:
            for item in songs.values():
                if isinstance(item, dict) and item.get("artist"):
                    artists[item["artist"]] = int(artists.get(item["artist"], 0)) + int(
                        item.get("count", 0) or 0
                    )
        for artist, count in artists.items():
            conn.execute(
                """
                INSERT INTO artist_totals (artist, play_count, updated_at)
                VALUES (?, ?, strftime('%s', 'now'))
                ON CONFLICT(artist) DO UPDATE SET
                    play_count = excluded.play_count,
                    updated_at = excluded.updated_at
                """,
                (artist, _as_int(count, 0)),
            )

        for album, count in albums.items():
            conn.execute(
                """
                INSERT INTO album_sessions (album, session_count, updated_at)
                VALUES (?, ?, strftime('%s', 'now'))
                ON CONFLICT(album) DO UPDATE SET
                    session_count = excluded.session_count,
                    updated_at = excluded.updated_at
                """,
                (album, _as_int(count, 0)),
            )

        conn.execute(
            """
            UPDATE listening_totals SET
                total_seconds = ?,
                recalculated_at = ?,
                recalculated_from_song_counts = ?,
                updated_at = strftime('%s', 'now')
            WHERE id = 1
            """,
            (
                _as_float(listening.get("total_seconds"), 0.0),
                _as_int(listening.get("recalculated_at")),
                1 if listening.get("recalculated_from_song_counts") else 0,
            ),
        )

        for cache_key, item in durations.items():
            if not isinstance(item, dict):
                continue
            ms = _as_int(item.get("ms"))
            minutes = _as_float(item.get("minutes"))
            if ms is None or minutes is None:
                continue
            conn.execute(
                """
                INSERT INTO duration_cache (
                    cache_key, artist, title, album, duration_ms,
                    duration_minutes, source, fetched_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                    _as_int(item.get("ts")),
                ),
            )

        for album, item in album_covers.items():
            if not isinstance(item, dict):
                continue
            conn.execute(
                """
                INSERT INTO album_covers (
                    album, artist, play_count, mbid, cover_url, updated_at
                ) VALUES (?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(album) DO UPDATE SET
                    artist = excluded.artist,
                    play_count = excluded.play_count,
                    mbid = excluded.mbid,
                    cover_url = excluded.cover_url,
                    updated_at = excluded.updated_at
                """,
                (
                    album,
                    item.get("artist"),
                    _as_int(item.get("count"), 0),
                    item.get("mbid"),
                    item.get("cover_url"),
                ),
            )

        for cache_key, item in tags.items():
            if not isinstance(item, dict) or not isinstance(item.get("tags"), list):
                continue
            conn.execute(
                """
                INSERT INTO tag_cache (cache_key, artist, title, tags_json, fetched_at)
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
                    json.dumps(item.get("tags") or [], ensure_ascii=False),
                    _as_int(item.get("ts")),
                ),
            )

        if keep_raw_backup:
            conn.execute(
                """
                INSERT OR IGNORE INTO legacy_imports (
                    source_name, source_sha256, raw_json
                ) VALUES (?, ?, ?)
                """,
                (source_path.name, digest, raw),
            )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES('legacy_stats_sha256', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (digest,),
        )

    return {
        "songs": len(songs),
        "artists": len(artists),
        "albums": len(albums),
        "duration_cache": len(durations),
        "album_covers": len(album_covers),
        "tag_cache": len(tags),
        "total_seconds": float(listening.get("total_seconds") or 0.0),
        "sha256": digest,
    }


def clear_duration_cache() -> None:
    init_db()
    with get_connection() as conn:
        conn.execute("DELETE FROM duration_cache")


def replace_listening_total(
    total_seconds: float,
    *,
    recalculated_at: int | None = None,
    recalculated_from_song_counts: bool = False,
) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE listening_totals SET
                total_seconds = ?,
                recalculated_at = ?,
                recalculated_from_song_counts = ?,
                updated_at = strftime('%s', 'now')
            WHERE id = 1
            """,
            (
                float(total_seconds),
                recalculated_at,
                1 if recalculated_from_song_counts else 0,
            ),
        )


def get_meta(key: str) -> str | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO meta(key, value) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            (key, value),
        )
