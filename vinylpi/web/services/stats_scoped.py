from __future__ import annotations

from typing import Any

from vinylpi.core.spotify_stats import get_spotify_ranked_stats
from vinylpi.web.services.stats import get_top_stats as get_vinyl_top_stats


def _vinyl_stats(limit: int) -> dict[str, Any]:
    data = dict(get_vinyl_top_stats(limit=limit) or {})
    data["scope"] = "vinyl"
    data["album_count_unit"] = "session"
    return data


def _merge_ranked(
    left: list[dict],
    right: list[dict],
    *,
    key_fields: tuple[str, ...],
    limit: int,
) -> list[dict]:
    merged: dict[tuple[str, ...], dict] = {}
    for item in [*(left or []), *(right or [])]:
        key = tuple(str(item.get(field) or "").strip().casefold() for field in key_fields)
        if not any(key):
            continue
        if key not in merged:
            merged[key] = dict(item)
            merged[key]["count"] = int(item.get("count") or 0)
        else:
            merged[key]["count"] = int(merged[key].get("count") or 0) + int(item.get("count") or 0)
            for field, value in item.items():
                if field != "count" and not merged[key].get(field) and value:
                    merged[key][field] = value

    return sorted(
        merged.values(),
        key=lambda row: (
            -int(row.get("count") or 0),
            str(row.get(key_fields[-1]) or "").casefold(),
        ),
    )[:limit]


def _merge_named(left: list[dict], right: list[dict], *, limit: int) -> list[dict]:
    return _merge_ranked(left, right, key_fields=("name",), limit=limit)


def get_scoped_stats(scope: str = "vinyl", *, limit: int = 10) -> dict[str, Any]:
    scope = str(scope or "vinyl").strip().lower()
    if scope == "spotify":
        return get_spotify_ranked_stats(limit=limit)
    if scope != "combined":
        return _vinyl_stats(limit)

    vinyl = _vinyl_stats(limit=max(limit, 25))
    spotify = get_spotify_ranked_stats(limit=max(limit, 25))

    genres = _merge_named(vinyl.get("top_genres") or [], spotify.get("top_genres") or [], limit=limit)
    albums = _merge_named(vinyl.get("top_albums") or [], spotify.get("top_albums") or [], limit=limit)
    covers = _merge_named(
        vinyl.get("top_album_covers") or [],
        spotify.get("top_album_covers") or [],
        limit=limit,
    )

    coverage_v = vinyl.get("metadata_coverage") or {}
    coverage_s = spotify.get("metadata_coverage") or {}
    return {
        "scope": "combined",
        "top_songs": _merge_ranked(
            vinyl.get("top_songs") or [],
            spotify.get("top_songs") or [],
            key_fields=("artist", "title"),
            limit=limit,
        ),
        "top_artists": _merge_named(
            vinyl.get("top_artists") or [],
            spotify.get("top_artists") or [],
            limit=limit,
        ),
        "top_albums": albums,
        "top_album_covers": covers,
        "top_genres": genres,
        "radar_genres": genres[:6],
        "total_minutes_listened": int(vinyl.get("total_minutes_listened") or 0)
        + int(spotify.get("total_minutes_listened") or 0),
        "album_count_unit": "listen",
        "metadata_coverage": {
            "songs_total": int(coverage_v.get("songs_total") or 0) + int(coverage_s.get("songs_total") or 0),
            "songs_with_genre": int(coverage_v.get("songs_with_genre") or 0) + int(coverage_s.get("songs_with_genre") or 0),
            "songs_with_shazam_id": int(coverage_v.get("songs_with_shazam_id") or 0),
        },
    }
