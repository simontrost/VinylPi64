import json
from vinylpi.paths import STATS_PATH
from collections import Counter
from vinylpi.core.genre_tags import get_cached_or_fetch_tags

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
    
    album_cover_map = {}

    for song in songs:
        album = song.get("album")
        cover_url = song.get("cover_url")
        if album and cover_url and album not in album_cover_map:
            album_cover_map[album] = cover_url

    top_album_covers = []
    for album in albums_sorted[:10]:
        name = album["name"]
        cover_url = album_cover_map.get(name)
        if cover_url:
            top_album_covers.append({
                "name": name,
                "count": album["count"],
                "cover_url": cover_url,
            })

    total_seconds = float(((stats.get("listening") or {}).get("total_seconds") or 0.0))
    total_minutes = int(round(total_seconds / 60.0))

    tag_counter = Counter()

    for song in songs:
        artist = song.get("artist")
        title = song.get("title")
        count = int(song.get("count", 0) or 0)

        if not artist or not title:
            continue

        tags = get_cached_or_fetch_tags(stats, artist, title)

        for tag in tags:
            name = tag.get("name")
            if not name:
                continue

            tag_counter[name] += count

    top_tags = [
        {"name": name, "count": count}
        for name, count in tag_counter.most_common(10)
    ]

    radar_tags = top_tags[:6]

    STATS_PATH.write_text(json.dumps(stats, indent=4), encoding="utf-8")

    return {
        "top_songs": songs_sorted,
        "top_artists": artists_sorted,
        "top_albums": albums_sorted,
        "top_album_covers": top_album_covers,
        "total_minutes_listened": total_minutes,
        "top_tags": top_tags,
        "radar_tags": radar_tags,
    }