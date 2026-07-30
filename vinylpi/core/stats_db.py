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
                song_key, artist, title, album, cover_url, play_count, updated_at
            ) VALUES (?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(song_key) DO UPDATE SET
                play_count = songs.play_count + 1,
                album = CASE
                    WHEN (songs.album IS NULL OR songs.album = '')
                         AND excluded.album IS NOT NULL AND excluded.album != ''
                    THEN excluded.album ELSE songs.album END,
                cover_url = CASE
                    WHEN (songs.cover_url IS NULL OR songs.cover_url = '')
                         AND excluded.cover_url IS NOT NULL AND excluded.cover_url != ''
                    THEN excluded.cover_url ELSE songs.cover_url END,
                updated_at = excluded.updated_at
            """,
            (song_key, artist, title, album, cover_url, now),
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
                id, artist, title, cover_url, album, bg_color,
                track_id, artist_id, updated_at
            ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
            ON CONFLICT(id) DO UPDATE SET
                artist = excluded.artist,
                title = excluded.title,
                cover_url = excluded.cover_url,
                album = excluded.album,
                bg_color = excluded.bg_color,
                track_id = excluded.track_id,
                artist_id = excluded.artist_id,
                updated_at = excluded.updated_at
            """,
            (
                data.get("artist"),
                data.get("title"),
                data.get("cover_url"),
                data.get("album"),
                data.get("bg_color"),
                data.get("track_id"),
                data.get("artist_id"),
            ),
        )


def get_current_status() -> dict | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT artist, title, cover_url, album, bg_color, track_id, artist_id
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
            SELECT song_key, artist, title, album, cover_url, play_count,
                   duration_ms, duration_minutes, duration_source,
                   measured_listen_seconds
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
                    song_key, artist, title, album, cover_url, play_count,
                    duration_ms, duration_minutes, duration_source,
                    measured_listen_seconds, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                ON CONFLICT(song_key) DO UPDATE SET
                    artist = excluded.artist,
                    title = excluded.title,
                    album = excluded.album,
                    cover_url = excluded.cover_url,
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
