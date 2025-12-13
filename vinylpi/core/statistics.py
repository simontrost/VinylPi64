import json
from pathlib import Path
import time
import requests

from vinylpi.paths import STATS_PATH, BASE_DIR, MB_URL, MB_UA

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


def _update_stats(artist: str, title: str, album: str | None) -> None:
    stats = _load_stats()

    song_key = f"{artist} – {title}"
    song_entry = stats["songs"].get(
        song_key,
        {
            "artist": artist,
            "title": title,
            "album": album,
            "count": 0,
        },
    )
    song_entry["count"] = song_entry.get("count", 0) + 1

    if album and not song_entry.get("album"):
        song_entry["album"] = album

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


def _mb_fetch_track_length_ms(artist: str, title: str, album: str | None = None) -> int | None:
    a = (artist or "").strip()
    t = (title or "").strip()
    if not a or not t:
        return None

    query = f'recording:"{t}" AND artist:"{a}"'
    if album:
        query += f' AND release:"{album.strip()}"'

    query += " AND status:official"

    params = {
        "query": query,
        "fmt": "json",
        "limit": 10,
        "inc": "releases",
    }

    r = requests.get(
        MB_URL,
        params=params,
        headers={"User-Agent": MB_UA},
        timeout=10,
    )
    r.raise_for_status()
    data = r.json()

    recs = data.get("recordings") or []
    if not recs:
        return None

    album_cf = (album or "").strip().casefold()

    best_len = None
    best_score = -10_000

    for rec in recs:
        length = rec.get("length")
        if not length:
            continue

        score = 0

        if (rec.get("title") or "").strip().casefold() == t.casefold():
            score += 50

        releases = rec.get("releases") or []
        if releases:
            score += 10
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

    if cache_key in cache and isinstance(cache[cache_key], dict) and cache[cache_key].get("ms"):
        ms = int(cache[cache_key]["ms"])
        minutes = float(cache[cache_key].get("minutes", ms / 60000.0))
        cached = True
    else:
        try:
            ms = _mb_fetch_track_length_ms(artist, title, album)
        except Exception as e:
            return {"ok": False, "error": f"MusicBrainz request failed: {e}"}

        if not ms:
            return {"ok": False, "error": "No duration found on MusicBrainz"}

        minutes = ms / 60000.0
        cached = False

        cache[cache_key] = {
            "ms": int(ms),
            "minutes": float(minutes),
            "ts": int(time.time()),
            "artist": artist,
            "title": title,
            "album": album,
        }

    stats["listening"]["total_seconds"] = float(stats["listening"]["total_seconds"]) + (ms / 1000.0)

    songs = stats.setdefault("songs", {})
    entry = songs.get(song_key) or {"artist": artist, "title": title, "album": album, "count": 0}
    entry["duration_ms"] = int(ms)
    entry["duration_minutes"] = round(minutes, 2)
    songs[song_key] = entry

    _save_stats(stats)

    total_minutes = stats["listening"]["total_seconds"] / 60.0
    return {
        "ok": True,
        "minutes": round(minutes, 2),
        "cached": cached,
        "total_minutes": round(total_minutes, 2),
    }
