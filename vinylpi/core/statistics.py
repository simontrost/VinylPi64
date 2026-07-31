from __future__ import annotations

import re

import requests

from vinylpi.core.stats_db import (
    add_listening_seconds,
    get_duration_cache,
    get_stats_snapshot,
    increment_album_session,
    update_song_duration,
    update_song_stats,
    upsert_duration_cache,
)
from vinylpi.paths import MB_UA, MB_URL


def _load_stats() -> dict:
    """Compatibility helper returning the former stats.json structure."""
    return get_stats_snapshot()


def _update_stats(
    artist: str,
    title: str,
    album: str | None,
    cover_url: str | None = None,
    genre: str | None = None,
    shazam_track_id: str | None = None,
    shazam_artist_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    update_song_stats(
        artist,
        title,
        album,
        cover_url,
        genre,
        shazam_track_id,
        shazam_artist_id,
        duration_ms,
    )


def _increment_album_session(album: str) -> None:
    increment_album_session(album)


def _clean_title_for_duration_search(title: str) -> str:
    text = title or ""
    for pattern in (
        r"\s*\(feat\.?.*?\)",
        r"\s*\(featuring\s+.*?\)",
        r"\s*\(ft\.?.*?\)",
        r"\s*\[feat\.?.*?\]",
        r"\s*\[featuring\s+.*?\]",
        r"\s*\[ft\.?.*?\]",
        r"\s+feat\.?\s+.*$",
        r"\s+featuring\s+.*$",
        r"\s+ft\.?\s+.*$",
    ):
        text = re.sub(pattern, "", text, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", text).strip()


def _musicbrainz_track_length_ms(
    artist: str,
    title: str,
    album: str | None = None,
) -> int | None:
    artist = (artist or "").strip()
    title = _clean_title_for_duration_search(title)
    if not artist or not title:
        return None

    response = requests.get(
        MB_URL,
        params={
            "query": f'recording:"{title}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": 25,
            "inc": "releases",
        },
        headers={"User-Agent": MB_UA},
        timeout=10,
    )
    response.raise_for_status()
    recordings = response.json().get("recordings") or []

    album_cf = (album or "").strip().casefold()
    title_cf = title.casefold()
    best_duration = None
    best_score = -10_000

    for recording in recordings:
        length = recording.get("length")
        if not length:
            continue

        score = 0
        if str(recording.get("title") or "").strip().casefold() == title_cf:
            score += 50

        if "live" in str(recording.get("disambiguation") or "").casefold():
            score -= 80

        releases = recording.get("releases") or []
        if releases:
            score += 10
            if any(str(item.get("status") or "").casefold() == "official" for item in releases):
                score += 20
            if any(str(item.get("status") or "").casefold() == "bootleg" for item in releases):
                score -= 80

            if album_cf:
                for release in releases:
                    release_title = str(release.get("title") or "").strip().casefold()
                    if release_title and (
                        release_title == album_cf
                        or album_cf in release_title
                        or release_title in album_cf
                    ):
                        score += 40
                        break

        duration = int(length)
        if duration < 30_000 or duration > 30 * 60_000:
            score -= 50

        if score > best_score:
            best_score = score
            best_duration = duration

    return best_duration


def add_listen_time_minutes_for_confirmed_song(
    artist: str,
    title: str,
    album: str | None = None,
    shazam_duration_ms: int | None = None,
) -> dict:
    """Add one full-track duration, preferring Shazam and the local cache."""
    cached_entry = get_duration_cache(artist, title)

    if cached_entry and cached_entry.get("ms"):
        duration_ms = int(cached_entry["ms"])
        source = cached_entry.get("source") or "cache"
        cached = True
    elif shazam_duration_ms and 30_000 <= int(shazam_duration_ms) <= 30 * 60_000:
        duration_ms = int(shazam_duration_ms)
        source = "shazam"
        cached = False
        upsert_duration_cache(
            artist,
            title,
            album,
            duration_ms,
            duration_ms / 60000.0,
            source,
        )
    else:
        try:
            duration_ms = _musicbrainz_track_length_ms(artist, title, album)
        except requests.RequestException as exc:
            return {"ok": False, "error": f"MusicBrainz request failed: {exc}"}

        if not duration_ms:
            return {"ok": False, "error": "No duration found in Shazam or MusicBrainz"}

        source = "musicbrainz"
        cached = False
        upsert_duration_cache(
            artist,
            title,
            album,
            int(duration_ms),
            int(duration_ms) / 60000.0,
            source,
        )

    minutes = duration_ms / 60000.0
    total_seconds = add_listening_seconds(duration_ms / 1000.0)
    update_song_duration(
        artist,
        title,
        album,
        duration_ms,
        round(minutes, 2),
        source,
    )

    return {
        "ok": True,
        "minutes": round(minutes, 2),
        "cached": cached,
        "source": source,
        "total_minutes": round(total_seconds / 60.0, 2),
    }


def add_measured_listen_time_seconds(
    artist: str,
    title: str,
    album: str | None,
    seconds: float,
) -> dict:
    seconds = max(0.0, float(seconds))
    if seconds < 10:
        return {"ok": False, "error": "Measured listen time too short"}

    total_seconds = add_listening_seconds(seconds)
    update_song_duration(
        artist,
        title,
        album,
        int(seconds * 1000),
        round(seconds / 60.0, 2),
        "measured_timer",
        measured_listen_seconds=round(seconds, 2),
    )

    return {
        "ok": True,
        "seconds": round(seconds, 2),
        "minutes": round(seconds / 60.0, 2),
        "source": "measured_timer",
        "total_minutes": round(total_seconds / 60.0, 2),
    }
