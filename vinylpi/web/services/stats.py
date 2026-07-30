from collections import Counter

from vinylpi.core.genre_tags import get_cached_or_fetch_tags
from vinylpi.core.stats_db import get_stats_snapshot


def get_top_stats(limit: int = 10):
    try:
        stats = get_stats_snapshot()
    except Exception as exc:
        print(f"Could not load stats from SQLite: {exc}")
        return {"top_songs": [], "top_artists": [], "top_albums": []}

    songs = list((stats.get("songs") or {}).values())
    artists_map = stats.get("artists") or {}
    albums_map = stats.get("albums") or {}
    stored_album_covers = stats.get("album_covers") or {}

    songs_sorted = sorted(
        songs, key=lambda song: song.get("count", 0), reverse=True
    )[:limit]
    artists_sorted = sorted(
        [{"name": name, "count": count} for name, count in artists_map.items()],
        key=lambda item: item["count"],
        reverse=True,
    )[:limit]
    albums_sorted = sorted(
        [{"name": name, "count": count} for name, count in albums_map.items()],
        key=lambda item: item["count"],
        reverse=True,
    )[:limit]

    album_cover_map = {
        album: item.get("cover_url")
        for album, item in stored_album_covers.items()
        if isinstance(item, dict) and item.get("cover_url")
    }
    for song in songs:
        album = song.get("album")
        cover_url = song.get("cover_url")
        if album and cover_url and album not in album_cover_map:
            album_cover_map[album] = cover_url

    top_album_covers = []
    for album in albums_sorted[:10]:
        cover_url = album_cover_map.get(album["name"])
        if cover_url:
            top_album_covers.append(
                {
                    "name": album["name"],
                    "count": album["count"],
                    "cover_url": cover_url,
                }
            )

    total_seconds = float((stats.get("listening") or {}).get("total_seconds") or 0.0)
    total_minutes = int(round(total_seconds / 60.0))

    tag_counter = Counter()
    for song in songs:
        artist = song.get("artist")
        title = song.get("title")
        count = int(song.get("count", 0) or 0)
        if not artist or not title:
            continue
        for tag in get_cached_or_fetch_tags(artist, title):
            name = tag.get("name")
            if name:
                tag_counter[name] += count

    top_tags = [
        {"name": name, "count": count}
        for name, count in tag_counter.most_common(10)
    ]

    return {
        "top_songs": songs_sorted,
        "top_artists": artists_sorted,
        "top_albums": albums_sorted,
        "top_album_covers": top_album_covers,
        "total_minutes_listened": total_minutes,
        "top_tags": top_tags,
        "radar_tags": top_tags[:6],
    }
