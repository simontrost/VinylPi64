import time
import requests
import os
import base64
from urllib.parse import quote_plus
from vinylpi.paths import BASE_DIR, MB_URL, MB_UA
import re
from vinylpi.core.stats_db import (
    add_listening_seconds,
    get_duration_cache,
    get_stats_snapshot,
    increment_album_session,
    update_song_duration,
    update_song_stats,
    upsert_duration_cache,
)

def _load_stats() -> dict:
    """Compatibility helper returning the former stats.json structure."""
    return get_stats_snapshot()


def _update_stats(artist: str, title: str, album: str | None, cover_url: str | None = None) -> None:
    update_song_stats(artist, title, album, cover_url)


def _increment_album_session(album: str) -> None:
    increment_album_session(album)


_SPOTIFY_TOKEN_CACHE = {
    "access_token": None,
    "expires_at": 0,
}


def _spotify_get_access_token() -> str | None:
    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return None

    now = time.time()
    if _SPOTIFY_TOKEN_CACHE["access_token"] and now < _SPOTIFY_TOKEN_CACHE["expires_at"]:
        return _SPOTIFY_TOKEN_CACHE["access_token"]

    auth_raw = f"{client_id}:{client_secret}".encode("utf-8")
    auth_b64 = base64.b64encode(auth_raw).decode("ascii")

    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {auth_b64}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=10,
    )
    r.raise_for_status()

    data = r.json()
    token = data.get("access_token")
    expires_in = int(data.get("expires_in", 3600))

    if not token:
        return None

    _SPOTIFY_TOKEN_CACHE["access_token"] = token
    _SPOTIFY_TOKEN_CACHE["expires_at"] = now + expires_in - 60

    return token


def _clean_title_for_duration_search(title: str) -> str:
    t = title or ""

    patterns = [
        r"\s*\(feat\.?.*?\)",
        r"\s*\(featuring\s+.*?\)",
        r"\s*\(ft\.?.*?\)",
        r"\s*\[feat\.?.*?\]",
        r"\s*\[featuring\s+.*?\]",
        r"\s*\[ft\.?.*?\]",
        r"\s+feat\.?\s+.*$",
        r"\s+featuring\s+.*$",
        r"\s+ft\.?\s+.*$",
    ]

    for pat in patterns:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)

    t = re.sub(r"\s+", " ", t).strip()
    return t

def _spotify_fetch_track_length_ms(artist: str, title: str, album: str | None = None) -> int | None:
    token = _spotify_get_access_token()
    if not token:
        return None

    a = (artist or "").strip()
    t_raw = (title or "").strip()
    t = _clean_title_for_duration_search(t_raw)
    al = (album or "").strip()

    if not a or not t:
        return None

    query = f'track:"{t}" artist:"{a}"'
    if al:
        query += f' album:"{al}"'

    r = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "q": query,
            "type": "track",
            "limit": 10,
        },
        timeout=10,
    )
    r.raise_for_status()

    items = (((r.json().get("tracks") or {}).get("items")) or [])
    if not items:
        return None

    title_cf = t.casefold()
    artist_cf = a.casefold()
    album_cf = al.casefold()

    best_ms = None
    best_score = -10_000

    for item in items:
        duration_ms = item.get("duration_ms")
        if not duration_ms:
            continue

        score = 0

        item_title = (item.get("name") or "").strip().casefold()
        if item_title == title_cf:
            score += 60
        elif title_cf in item_title or item_title in title_cf:
            score += 30

        item_artists = item.get("artists") or []
        artist_names = [
            (ar.get("name") or "").strip().casefold()
            for ar in item_artists
        ]

        if artist_cf in artist_names:
            score += 60
        elif any(artist_cf in x or x in artist_cf for x in artist_names if x):
            score += 25

        item_album = item.get("album") or {}
        item_album_name = (item_album.get("name") or "").strip().casefold()

        if album_cf:
            if item_album_name == album_cf:
                score += 40
            elif album_cf in item_album_name or item_album_name in album_cf:
                score += 20

        if item.get("explicit") is True:
            score += 1

        if duration_ms < 30_000:
            score -= 50
        if duration_ms > 30 * 60_000:
            score -= 50

        if score > best_score:
            best_score = score
            best_ms = int(duration_ms)

    return best_ms

def _mb_fetch_track_length_ms(artist: str, title: str, album: str | None = None) -> int | None:
    a = (artist or "").strip()
    t = (title or "").strip()
    if not a or not t:
        return None

    query = f'recording:"{t}" AND artist:"{a}"'

    params = {
        "query": query,
        "fmt": "json",
        "limit": 25,
        "inc": "releases",
    }

    r = requests.get(MB_URL, params=params, headers={"User-Agent": MB_UA}, timeout=10)
    r.raise_for_status()
    recs = (r.json().get("recordings") or [])
    if not recs:
        return None

    album_cf = (album or "").strip().casefold()
    title_cf = t.casefold()

    best_len = None
    best_score = -10_000

    for rec in recs:
        length = rec.get("length")
        if not length:
            continue

        score = 0

        if (rec.get("title") or "").strip().casefold() == title_cf:
            score += 50

        dis = (rec.get("disambiguation") or "").casefold()
        if "live" in dis:
            score -= 80

        releases = rec.get("releases") or []
        if releases:
            score += 10

            if any((rel.get("status") or "").casefold() == "official" for rel in releases):
                score += 20

            if any((rel.get("status") or "").casefold() == "bootleg" for rel in releases):
                score -= 80

            if album_cf:
                for rel in releases:
                    rel_title = (rel.get("title") or "").strip().casefold()
                    if rel_title and (rel_title == album_cf or album_cf in rel_title or rel_title in album_cf):
                        score += 40
                        break

        if length < 30_000:
            score -= 50
        if length > 30 * 60_000:
            score -= 50

        if score > best_score:
            best_score = score
            best_len = int(length)

    return best_len



def add_listen_time_minutes_for_confirmed_song(
    artist: str,
    title: str,
    album: str | None = None,
) -> dict:
    cached_entry = get_duration_cache(artist, title)
    source = None

    if cached_entry and cached_entry.get("ms"):
        ms = int(cached_entry["ms"])
        minutes = float(cached_entry.get("minutes", ms / 60000.0))
        source = cached_entry.get("source", "cache")
        cached = True
    else:
        ms = None
        spotify_error = None

        try:
            ms = _spotify_fetch_track_length_ms(artist, title, album)
            if ms:
                source = "spotify"
        except Exception as exc:
            spotify_error = str(exc)

        if not ms:
            try:
                ms = _mb_fetch_track_length_ms(artist, title, album)
                if ms:
                    source = "musicbrainz"
            except Exception as exc:
                return {
                    "ok": False,
                    "error": (
                        "Spotify and MusicBrainz request failed: "
                        f"spotify={spotify_error}, musicbrainz={exc}"
                    ),
                }

        if not ms:
            return {"ok": False, "error": "No duration found on Spotify or MusicBrainz"}

        minutes = ms / 60000.0
        cached = False
        upsert_duration_cache(
            artist, title, album, int(ms), float(minutes), source
        )

    total_seconds = add_listening_seconds(ms / 1000.0)
    update_song_duration(
        artist,
        title,
        album,
        int(ms),
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

