import asyncio

async def _get_shazam_info_async(
    track_id: str | None,
    artist_id: str | None,
) -> dict:
    from shazamio import Shazam

    shazam = Shazam()

    track_info = None
    artist_info = None

    if track_id:
        try:
            track_info = await shazam.track_about(track_id=track_id)
        except Exception as e:
            track_info = {
                "ok": False,
                "error": str(e),
            }

    if artist_id:
        try:
            artist_info = await shazam.artist_about(artist_id)
        except Exception as e:
            artist_info = {
                "ok": False,
                "error": str(e),
            }

    return {
        "ok": True,
        "track": track_info,
        "artist": artist_info,
    }


def get_shazam_info(
    track_id: str | None,
    artist_id: str | None,
) -> dict:
    if not track_id and not artist_id:
        return {
            "ok": False,
            "error": "missing_ids",
        }

    try:
        return asyncio.run(_get_shazam_info_async(track_id, artist_id))
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }