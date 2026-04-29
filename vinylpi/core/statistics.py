import json
from pathlib import Path
import time
import requests
import os
import base64
from urllib.parse import quote_plus
from vinylpi.paths import STATS_PATH, BASE_DIR, MB_URL, MB_UA
import re

def _load_stats() -> dict:
    if STATS_PATH.exists():
        try:
            return json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass

    return {
        "songs": {},
        "artists": {},
        "albums": {},
    }


def _save_stats(stats: dict) -> None:
    try:
        STATS_PATH.write_text(json.dumps(stats, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"Could not write stats file: {e}")


def _update_stats(artist: str, title: str, album: str | None, cover_url: str | None = None) -> None:
    stats = _load_stats()

    song_key = f"{artist} – {title}"
    song_entry = stats["songs"].get(
        song_key,
        {
            "artist": artist,
            "title": title,
            "album": album,
            "count": 0,
            "cover_url": cover_url
        },
    )

    song_entry["count"] = song_entry.get("count", 0) + 1
    if album and not song_entry.get("album"):
        song_entry["album"] = album

    if cover_url and not song_entry.get("cover_url"):
        song_entry["cover_url"] = cover_url
        
    stats["songs"][song_key] = song_entry

    stats["artists"][artist] = stats["artists"].get(artist, 0) + 1

    _save_stats(stats)


def _increment_album_session(album: str) -> None:
    if not album:
        return

    stats = _load_stats()
    albums = stats.setdefault("albums", {})
    albums[album] = albums.get(album, 0) + 1
    _save_stats(stats)

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
    stats = _load_stats()

    stats.setdefault("listening", {})
    stats["listening"].setdefault("total_seconds", 0.0)

    cache = stats.setdefault("durations_cache", {})

    song_key = f"{artist} – {title}"
    cache_key = song_key.casefold()

    source = None

    if cache_key in cache and isinstance(cache[cache_key], dict) and cache[cache_key].get("ms"):
        ms = int(cache[cache_key]["ms"])
        minutes = float(cache[cache_key].get("minutes", ms / 60000.0))
        source = cache[cache_key].get("source", "cache")
        cached = True
    else:
        ms = None

        try:
            ms = _spotify_fetch_track_length_ms(artist, title, album)
            if ms:
                source = "spotify"
        except Exception as e:
            spotify_error = str(e)
        else:
            spotify_error = None

        if not ms:
            try:
                ms = _mb_fetch_track_length_ms(artist, title, album)
                if ms:
                    source = "musicbrainz"
            except Exception as e:
                mb_error = str(e)
                return {
                    "ok": False,
                    "error": f"Spotify and MusicBrainz request failed: spotify={spotify_error}, musicbrainz={mb_error}",
                }

        if not ms:
            return {
                "ok": False,
                "error": "No duration found on Spotify or MusicBrainz",
            }

        minutes = ms / 60000.0
        cached = False

        cache[cache_key] = {
            "ms": int(ms),
            "minutes": float(minutes),
            "ts": int(time.time()),
            "artist": artist,
            "title": title,
            "album": album,
            "source": source,
        }

    stats["listening"]["total_seconds"] = (
        float(stats["listening"]["total_seconds"]) + (ms / 1000.0)
    )

    songs = stats.setdefault("songs", {})
    entry = songs.get(song_key) or {
        "artist": artist,
        "title": title,
        "album": album,
        "count": 0,
    }

    entry["duration_ms"] = int(ms)
    entry["duration_minutes"] = round(minutes, 2)
    entry["duration_source"] = source

    songs[song_key] = entry

    _save_stats(stats)

    total_minutes = stats["listening"]["total_seconds"] / 60.0

    return {
        "ok": True,
        "minutes": round(minutes, 2),
        "cached": cached,
        "source": source,
        "total_minutes": round(total_minutes, 2),
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

    stats = _load_stats()
    stats.setdefault("listening", {})
    stats["listening"].setdefault("total_seconds", 0.0)

    stats["listening"]["total_seconds"] = (
        float(stats["listening"]["total_seconds"]) + seconds
    )

    song_key = f"{artist} – {title}"
    songs = stats.setdefault("songs", {})
    entry = songs.get(song_key) or {
        "artist": artist,
        "title": title,
        "album": album,
        "count": 0,
    }

    entry["duration_ms"] = int(seconds * 1000)
    entry["duration_minutes"] = round(seconds / 60.0, 2)
    entry["duration_source"] = "measured_timer"
    entry["measured_listen_seconds"] = round(seconds, 2)

    songs[song_key] = entry
    _save_stats(stats)

    return {
        "ok": True,
        "seconds": round(seconds, 2),
        "minutes": round(seconds / 60.0, 2),
        "source": "measured_timer",
        "total_minutes": round(stats["listening"]["total_seconds"] / 60.0, 2),
    }