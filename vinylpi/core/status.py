import json
from vinylpi.paths import STATUS_PATH

def write_status(artist: str, title: str, cover_url: str | None = None, album: str | None = None) -> None:
    data = {"artist": artist, "title": title, "cover_url": cover_url, "album": album}
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print(f"Could not write status file: {e}")
