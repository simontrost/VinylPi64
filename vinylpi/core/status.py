from vinylpi.core.stats_db import write_current_status


def write_status(
    artist: str,
    title: str,
    cover_url: str | None = None,
    album: str | None = None,
    genre: str | None = None,
    bg_color: str | None = None,
    track_id: str | None = None,
    artist_id: str | None = None,
    duration_ms: int | None = None,
) -> None:
    try:
        write_current_status(
            {
                "artist": artist,
                "title": title,
                "cover_url": cover_url,
                "album": album,
                "genre": genre,
                "bg_color": bg_color,
                "track_id": track_id,
                "artist_id": artist_id,
                "duration_ms": duration_ms,
            }
        )
    except Exception as exc:
        print(f"Could not write status to database: {exc}")
