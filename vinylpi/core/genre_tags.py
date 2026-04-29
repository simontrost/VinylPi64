import os
import time
import requests

LASTFM_URL = "https://ws.audioscrobbler.com/2.0/"

BLACKLIST = {
    "seen live",
    "favorites",
    "favourite",
    "favorite",
    "awesome",
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

    r = requests.get(LASTFM_URL, params=params, timeout=10)
    r.raise_for_status()

    data = r.json()
    raw_tags = ((data.get("toptags") or {}).get("tag") or [])

    tags = []
    for tag in raw_tags[:8]:
        name = (tag.get("name") or "").strip().lower()
        count = int(tag.get("count") or 0)

        if not name or name in BLACKLIST:
            continue

        tags.append({
            "name": name,
            "count": count,
        })

    return tags


def get_cached_or_fetch_tags(stats: dict, artist: str, title: str) -> list[dict]:
    cache = stats.setdefault("tag_cache", {})
    key = f"{artist} – {title}".casefold()

    cached = cache.get(key)
    if isinstance(cached, dict) and isinstance(cached.get("tags"), list):
        return cached["tags"]

    try:
        tags = fetch_lastfm_track_tags(artist, title)
    except Exception as e:
        print(f"Last.fm tags failed for {artist} – {title}: {e}")
        tags = []

    cache[key] = {
        "artist": artist,
        "title": title,
        "tags": tags,
        "ts": int(time.time()),
    }

    return tags