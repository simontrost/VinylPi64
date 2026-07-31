from __future__ import annotations

import re
import time
import unicodedata
from collections.abc import Iterable
from typing import Any

from vinylpi.core.database import get_connection, init_db
from vinylpi.core.title_variants import canonicalize_title

_DISCOGS_ARTIST_SUFFIX = re.compile(r"\s*\(\d+\)\s*$")
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.casefold().replace("&", " and ")
    text = _NON_ALNUM.sub(" ", text)
    return " ".join(text.split())


def normalize_artist(value: str | None) -> str:
    text = _DISCOGS_ARTIST_SUFFIX.sub("", value or "")
    text = re.sub(r"\s+(feat\.?|ft\.?|featuring)\s+.*$", "", text, flags=re.IGNORECASE)
    return normalize_text(text)


def upsert_release_summary(data: dict[str, Any]) -> None:
    init_db()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO discogs_releases (
                release_id, instance_id, folder_id, title, artist, year, country,
                label, catalog_number, format_text, thumb_url, cover_url,
                date_added, details_loaded, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(release_id) DO UPDATE SET
                instance_id = excluded.instance_id,
                folder_id = excluded.folder_id,
                title = excluded.title,
                artist = excluded.artist,
                year = excluded.year,
                country = COALESCE(excluded.country, discogs_releases.country),
                label = COALESCE(excluded.label, discogs_releases.label),
                catalog_number = COALESCE(excluded.catalog_number, discogs_releases.catalog_number),
                format_text = excluded.format_text,
                thumb_url = COALESCE(NULLIF(excluded.thumb_url, ''), discogs_releases.thumb_url),
                cover_url = COALESCE(NULLIF(excluded.cover_url, ''), discogs_releases.cover_url),
                date_added = excluded.date_added,
                synced_at = excluded.synced_at
            """,
            (
                int(data["release_id"]),
                data.get("instance_id"),
                data.get("folder_id"),
                data.get("title") or "Unknown release",
                data.get("artist") or "Unknown artist",
                data.get("year"),
                data.get("country"),
                data.get("label"),
                data.get("catalog_number"),
                data.get("format_text"),
                data.get("thumb_url"),
                data.get("cover_url"),
                data.get("date_added"),
                int(bool(data.get("details_loaded", False))),
                int(data.get("synced_at") or time.time()),
            ),
        )


def replace_release_details(release: dict[str, Any], tracks: Iterable[dict[str, Any]]) -> None:
    init_db()
    release_id = int(release["release_id"])
    now = int(time.time())
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO discogs_releases (
                release_id, instance_id, folder_id, title, artist, year, country,
                label, catalog_number, format_text, thumb_url, cover_url,
                date_added, details_loaded, synced_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)
            ON CONFLICT(release_id) DO UPDATE SET
                instance_id = COALESCE(excluded.instance_id, discogs_releases.instance_id),
                folder_id = COALESCE(excluded.folder_id, discogs_releases.folder_id),
                title = excluded.title,
                artist = excluded.artist,
                year = excluded.year,
                country = excluded.country,
                label = excluded.label,
                catalog_number = excluded.catalog_number,
                format_text = excluded.format_text,
                thumb_url = COALESCE(NULLIF(excluded.thumb_url, ''), discogs_releases.thumb_url),
                cover_url = COALESCE(NULLIF(excluded.cover_url, ''), discogs_releases.cover_url),
                date_added = COALESCE(excluded.date_added, discogs_releases.date_added),
                details_loaded = 1,
                synced_at = excluded.synced_at
            """,
            (
                release_id,
                release.get("instance_id"),
                release.get("folder_id"),
                release.get("title") or "Unknown release",
                release.get("artist") or "Unknown artist",
                release.get("year"),
                release.get("country"),
                release.get("label"),
                release.get("catalog_number"),
                release.get("format_text"),
                release.get("thumb_url"),
                release.get("cover_url"),
                release.get("date_added"),
                now,
            ),
        )
        conn.execute("DELETE FROM discogs_tracks WHERE release_id = ?", (release_id,))
        conn.executemany(
            """
            INSERT INTO discogs_tracks (
                release_id, track_index, position, side, title, artist,
                duration_seconds, normalized_title, normalized_artist
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    release_id,
                    int(track["track_index"]),
                    track.get("position"),
                    track.get("side"),
                    track.get("title") or "Unknown track",
                    track.get("artist") or release.get("artist") or "Unknown artist",
                    track.get("duration_seconds"),
                    normalize_text(canonicalize_title(track.get("title") or "")),
                    normalize_artist(track.get("artist") or release.get("artist")),
                )
                for track in tracks
            ],
        )


def get_detailed_release_ids() -> set[int]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT release_id FROM discogs_releases WHERE details_loaded = 1"
        ).fetchall()
    return {int(row["release_id"]) for row in rows}


def delete_releases_not_in(release_ids: set[int]) -> None:
    init_db()
    with get_connection() as conn:
        if not release_ids:
            conn.execute("DELETE FROM discogs_releases")
            return
        placeholders = ",".join("?" for _ in release_ids)
        conn.execute(
            f"DELETE FROM discogs_releases WHERE release_id NOT IN ({placeholders})",
            tuple(sorted(release_ids)),
        )


def set_sync_state(
    *,
    username: str | None = None,
    status: str,
    message: str | None = None,
    error: str | None = None,
    failed_releases: int | None = None,
    completed: bool = False,
) -> None:
    init_db()
    with get_connection() as conn:
        counts = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM discogs_releases) AS releases_count,
                (SELECT COUNT(*) FROM discogs_tracks) AS tracks_count
            """
        ).fetchone()
        conn.execute(
            """
            UPDATE discogs_sync_state
            SET username = COALESCE(?, username),
                status = ?,
                message = ?,
                last_error = ?,
                releases_count = ?,
                tracks_count = ?,
                failed_releases = COALESCE(?, failed_releases),
                last_synced_at = CASE WHEN ? THEN strftime('%s', 'now') ELSE last_synced_at END,
                updated_at = strftime('%s', 'now')
            WHERE id = 1
            """,
            (
                username,
                status,
                message,
                error,
                int(counts["releases_count"] or 0),
                int(counts["tracks_count"] or 0),
                failed_releases,
                int(completed),
            ),
        )


def get_sync_state() -> dict[str, Any]:
    init_db()
    with get_connection() as conn:
        row = conn.execute("SELECT * FROM discogs_sync_state WHERE id = 1").fetchone()
    return {key: row[key] for key in row.keys()} if row else {}


def get_collection_counts() -> dict[str, int]:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                (SELECT COUNT(*) FROM discogs_releases) AS releases,
                (SELECT COUNT(*) FROM discogs_tracks) AS tracks
            """
        ).fetchone()
    return {"releases": int(row["releases"] or 0), "tracks": int(row["tracks"] or 0)}


_TRACK_SELECT = """
    SELECT
        t.release_id, t.track_index, t.position, t.side, t.title AS track_title,
        t.artist AS track_artist, t.duration_seconds, t.normalized_title,
        t.normalized_artist, r.title AS release_title, r.artist AS release_artist,
        r.year, r.country, r.label, r.catalog_number, r.format_text,
        COALESCE(NULLIF(r.cover_url, ''), r.thumb_url) AS cover_url
    FROM discogs_tracks t
    JOIN discogs_releases r ON r.release_id = t.release_id
"""


def find_exact_title_tracks(normalized_title: str, limit: int = 100) -> list[dict[str, Any]]:
    if not normalized_title:
        return []
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            _TRACK_SELECT + " WHERE t.normalized_title = ? ORDER BY t.release_id, t.track_index LIMIT ?",
            (normalized_title, int(limit)),
        ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def get_release_tracks(release_id: int) -> list[dict[str, Any]]:
    init_db()
    with get_connection() as conn:
        rows = conn.execute(
            _TRACK_SELECT + " WHERE t.release_id = ? ORDER BY t.track_index",
            (int(release_id),),
        ).fetchall()
    return [{key: row[key] for key in row.keys()} for row in rows]


def get_release_track(release_id: int, track_index: int) -> dict[str, Any] | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            _TRACK_SELECT + " WHERE t.release_id = ? AND t.track_index = ?",
            (int(release_id), int(track_index)),
        ).fetchone()
    return {key: row[key] for key in row.keys()} if row else None


def get_next_track(release_id: int, track_index: int) -> dict[str, Any] | None:
    init_db()
    with get_connection() as conn:
        row = conn.execute(
            _TRACK_SELECT
            + " WHERE t.release_id = ? AND t.track_index > ? ORDER BY t.track_index LIMIT 1",
            (int(release_id), int(track_index)),
        ).fetchone()
    return {key: row[key] for key in row.keys()} if row else None


def get_track_counts(release_id: int, track_index: int, side: str | None) -> dict[str, int]:
    init_db()
    with get_connection() as conn:
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM discogs_tracks WHERE release_id = ?",
            (int(release_id),),
        ).fetchone()["n"]
        if side:
            side_rows = conn.execute(
                """
                SELECT track_index FROM discogs_tracks
                WHERE release_id = ? AND side = ? ORDER BY track_index
                """,
                (int(release_id), side),
            ).fetchall()
            indices = [int(row["track_index"]) for row in side_rows]
        else:
            indices = []
    side_number = indices.index(int(track_index)) + 1 if int(track_index) in indices else 0
    return {
        "track_count": int(total or 0),
        "side_track_number": side_number,
        "side_track_count": len(indices),
    }
