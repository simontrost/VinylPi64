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
    song_entry = stats["songs"].get(song_key, {
        "artist": artist,
        "title": title,
        "album": album,
        "count": 0,
    })
    song_entry["count"] = song_entry.get("count", 0) + 1
    if album and not song_entry.get("album"):
        song_entry["album"] = album
    stats["songs"][song_key] = song_entry

    stats["artists"][artist] = stats["artists"].get(artist, 0) + 1

    if album:
        stats["albums"][album] = stats["albums"].get(album, 0) + 1

    _save_stats(stats)
