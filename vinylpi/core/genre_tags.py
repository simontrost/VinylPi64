import os
import time

import requests

from vinylpi.core.stats_db import get_cached_tags, upsert_tag_cache

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

BLACKLIST = {
    "seen live",
    "favorites",
    "favourite",
    "favorite",
    "awesome",
    "beautiful",
    "good",
    "spotify",
}


def fetch_lastfm_track_tags(artist: str, title: str) -> list[dict]:
    api_key = os.getenv("LAST_FM_API_KEY")
    if not api_key:
        print("[LastFM] Missing LAST_FM_API_KEY")
        return []

    params = {
        "method": "track.getTopTags",
        "artist": artist,
        "track": title,
        "api_key": api_key,
        "format": "json",
        "autocorrect": 1,
    }

    response = requests.get(LASTFM_URL, params=params, timeout=10)
    response.raise_for_status()
    raw_tags = ((response.json().get("toptags") or {}).get("tag") or [])

    tags = []
    for tag in raw_tags[:8]:
        name = (tag.get("name") or "").strip().lower()
        count = int(tag.get("count") or 0)
        if not name or name in BLACKLIST:
            continue
        tags.append({"name": name, "count": count})
    return tags


def get_cached_or_fetch_tags(*args) -> list[dict]:
    """Read genre tags from SQLite and fetch/store them when missing.

    Accepts both the old ``(stats, artist, title)`` and the new
    ``(artist, title)`` call shape for compatibility.
    """
    if len(args) == 3:
        _, artist, title = args
    elif len(args) == 2:
        artist, title = args
    else:
        raise TypeError("Expected (artist, title) or (stats, artist, title)")

    cached = get_cached_tags(artist, title)
    if cached is not None:
        return cached

    try:
        tags = fetch_lastfm_track_tags(artist, title)
    except Exception as exc:
        print(f"Last.fm tags failed for {artist} – {title}: {exc}")
        tags = []

    upsert_tag_cache(artist, title, tags, fetched_at=int(time.time()))
    return tags
