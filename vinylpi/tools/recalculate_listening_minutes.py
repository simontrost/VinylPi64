#!/usr/bin/env python3
import base64
import os
import time
from pathlib import Path

from vinylpi.core.stats_db import (
    clear_duration_cache,
    get_stats_snapshot,
    replace_listening_total,
    update_song_duration,
    upsert_duration_cache,
)
from vinylpi.paths import BASE_DIR, DB_PATH

import requests

import re

def clean_title_for_search(title: str) -> str:
    t = title or ""

    patterns = [
        r"\s*\(feat\.?.*?\)",
        r"\s*\(ft\.?.*?\)",
        r"\s*\[feat\.?.*?\]",
        r"\s*\[ft\.?.*?\]",
        r"\s+feat\.?\s+.*$",
        r"\s+ft\.?\s+.*$",
    ]

    for pat in patterns:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)

    t = re.sub(r"\s+", " ", t).strip()
    return t

MB_URL = "https://musicbrainz.org/ws/2/recording"
MB_UA = "VinylPi64/1.0 (https://github.com/simontrost/VinylPi64)"

_SPOTIFY_TOKEN = None
_SPOTIFY_EXPIRES_AT = 0


def load_env_file(path: Path):
    if not path.exists():
        return

    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def spotify_token():
    global _SPOTIFY_TOKEN, _SPOTIFY_EXPIRES_AT

    now = time.time()
    if _SPOTIFY_TOKEN and now < _SPOTIFY_EXPIRES_AT:
        return _SPOTIFY_TOKEN

    client_id = os.environ.get("SPOTIFY_CLIENT_ID", "").strip()
    client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET", "").strip()

    if not client_id or not client_secret:
        return None

    auth = base64.b64encode(f"{client_id}:{client_secret}".encode("utf-8")).decode("ascii")

    r = requests.post(
        "https://accounts.spotify.com/api/token",
        headers={
            "Authorization": f"Basic {auth}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    r.raise_for_status()

    data = r.json()
    _SPOTIFY_TOKEN = data["access_token"]
    _SPOTIFY_EXPIRES_AT = now + int(data.get("expires_in", 3600)) - 60
    return _SPOTIFY_TOKEN


def spotify_duration_ms(artist, title, album=None):
    search_title = clean_title_for_search(title)

    artist_cf = artist.casefold().strip()
    title_cf = search_title.casefold().strip()
    token = spotify_token()
    if not token:
        return None

    q = f'track:"{search_title}" artist:"{artist}"'
    if album:
        q += f' album:"{album}"'

    r = requests.get(
        "https://api.spotify.com/v1/search",
        headers={"Authorization": f"Bearer {token}"},
        params={"q": q, "type": "track", "limit": 10},
        timeout=15,
    )
    r.raise_for_status()

    items = (((r.json().get("tracks") or {}).get("items")) or [])
    if not items:
        return None

    artist_cf = artist.casefold().strip()
    title_cf = title.casefold().strip()
    album_cf = (album or "").casefold().strip()

    best = None
    best_score = -10_000

    for item in items:
        ms = item.get("duration_ms")
        if not ms:
            continue

        score = 0
        item_title = (item.get("name") or "").casefold().strip()

        if item_title == title_cf:
            score += 60
        elif title_cf in item_title or item_title in title_cf:
            score += 30

        artist_names = [
            (a.get("name") or "").casefold().strip()
            for a in item.get("artists", [])
        ]

        if artist_cf in artist_names:
            score += 60
        elif any(artist_cf in x or x in artist_cf for x in artist_names if x):
            score += 25

        item_album = ((item.get("album") or {}).get("name") or "").casefold().strip()
        if album_cf:
            if item_album == album_cf:
                score += 40
            elif album_cf in item_album or item_album in album_cf:
                score += 20

        if ms < 30_000:
            score -= 50
        if ms > 30 * 60_000:
            score -= 50

        if score > best_score:
            best_score = score
            best = int(ms)

    return best


def musicbrainz_duration_ms(artist, title, album=None):
    query = f'recording:"{title}" AND artist:"{artist}"'

    r = requests.get(
        MB_URL,
        params={
            "query": query,
            "fmt": "json",
            "limit": 25,
            "inc": "releases",
        },
        headers={"User-Agent": MB_UA},
        timeout=15,
    )
    r.raise_for_status()

    recs = r.json().get("recordings") or []
    if not recs:
        return None

    title_cf = title.casefold().strip()
    album_cf = (album or "").casefold().strip()

    best = None
    best_score = -10_000

    for rec in recs:
        ms = rec.get("length")
        if not ms:
            continue

        score = 0

        if (rec.get("title") or "").casefold().strip() == title_cf:
            score += 50

        dis = (rec.get("disambiguation") or "").casefold()
        if "live" in dis:
            score -= 80

        releases = rec.get("releases") or []
        if releases:
            score += 10

            if any((rel.get("status") or "").casefold() == "official" for rel in releases):
                score += 20

            if album_cf:
                for rel in releases:
                    rel_title = (rel.get("title") or "").casefold().strip()
                    if rel_title and (rel_title == album_cf or album_cf in rel_title or rel_title in album_cf):
                        score += 40
                        break

        if ms < 30_000:
            score -= 50
        if ms > 30 * 60_000:
            score -= 50

        if score > best_score:
            best_score = score
            best = int(ms)

    return best


def fetch_duration_ms(artist, title, album=None):
    try:
        ms = spotify_duration_ms(artist, title, album)
        if ms:
            return ms, "spotify"
    except Exception as e:
        print(f"  Spotify failed: {e}")

    try:
        ms = musicbrainz_duration_ms(artist, title, album)
        if ms:
            return ms, "musicbrainz"
    except Exception as e:
        print(f"  MusicBrainz failed: {e}")

    return None, "none"


def main():
    load_env_file(BASE_DIR / "vinylpi.env")
    load_env_file(BASE_DIR / ".env")

    stats = get_stats_snapshot()
    clear_duration_cache()
    songs = stats.get("songs") or {}

    durations_cache = {}
    total_seconds = 0.0

    print(f"Recalculating listening minutes for {len(songs)} songs...\n")

    for song_key, entry in songs.items():
        artist = entry.get("artist")
        title = entry.get("title")
        album = entry.get("album")
        count = int(entry.get("count", 0) or 0)

        if not artist or not title or count <= 0:
            continue

        cache_key = f"{artist} – {title}".casefold()

        cached = durations_cache.get(cache_key)
        if isinstance(cached, dict) and cached.get("ms"):
            ms = int(cached["ms"])
            source = cached.get("source", "unknown")
            print(f"[cached:{source}] {artist} – {title} = {round(ms / 60000, 2)} min x {count}")
        else:
            print(f"[fetch] {artist} – {title}")
            ms, source = fetch_duration_ms(artist, title, album)

            if not ms:
                print("  -> no duration found, skipped")
                continue

            durations_cache[cache_key] = {
                "ms": int(ms),
                "minutes": ms / 60000.0,
                "source": source,
            }
            upsert_duration_cache(
                artist, title, album, int(ms), ms / 60000.0, source
            )

            print(f"  -> {source}: {round(ms / 60000, 2)} min x {count}")

        update_song_duration(
            artist, title, album, int(ms), round(ms / 60000.0, 2), source
        )
        total_seconds += (ms / 1000.0) * count

        time.sleep(0.15)

    replace_listening_total(
        total_seconds,
        recalculated_at=int(time.time()),
        recalculated_from_song_counts=True,
    )

    print("\nDone.")
    print(f"New total: {round(total_seconds / 60.0, 2)} minutes")
    print(f"Database updated: {DB_PATH}")


if __name__ == "__main__":
    main()