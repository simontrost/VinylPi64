import json
from vinylpi.paths import STATS_PATH

def get_top_stats(limit: int = 10):
    if not STATS_PATH.exists():
        return {"top_songs": [], "top_artists": [], "top_albums": []}

    try:
        stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"top_songs": [], "top_artists": [], "top_albums": []}

    songs = list((stats.get("songs") or {}).values())
    artists_map = stats.get("artists") or {}
    albums_map = stats.get("albums") or {}

    songs_sorted = sorted(songs, key=lambda s: s.get("count", 0), reverse=True)[:limit]
    artists_sorted = sorted(
        [{"name": k, "count": v} for k, v in artists_map.items()],
        key=lambda a: a["count"],
        reverse=True
    )[:limit]
    albums_sorted = sorted(
        [{"name": k, "count": v} for k, v in albums_map.items()],
        key=lambda a: a["count"],
        reverse=True
    )[:limit]

    return {"top_songs": songs_sorted, "top_artists": artists_sorted, "top_albums": albums_sorted}
