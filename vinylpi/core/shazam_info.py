from __future__ import annotations

from vinylpi.integrations.shazam_client import get_details


def get_shazam_info(track_id: str | None, artist_id: str | None) -> dict:
    if not track_id and not artist_id:
        return {"ok": False, "error": "missing_ids"}

    try:
        details = get_details(track_id, artist_id)
    except Exception as exc:
        return {"ok": False, "error": str(exc)}

    return {
        "ok": True,
        "track": details.get("track"),
        "artist": details.get("artist"),
    }
