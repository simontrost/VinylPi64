import json
from vinylpi.paths import STATUS_PATH

import json
from vinylpi.paths import STATUS_PATH

def write_status(
    artist: str,
    title: str,
    cover_url: str | None = None,
    album: str | None = None,
    bg_color: str | None = None,
    track_id: str | None = None,
    artist_id: str | None = None,
) -> None:
    data = {
        "artist": artist,
        "title": title,
        "cover_url": cover_url,
        "album": album,
        "bg_color": bg_color,
        "track_id": track_id,
        "artist_id": artist_id,
    }

    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print(f"Could not write status file: {e}")
