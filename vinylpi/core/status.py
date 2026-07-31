from __future__ import annotations

from vinylpi.core.stats_db import get_current_status, write_current_status


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
    discogs_release_id: int | None = None,
    discogs_position: str | None = None,
    discogs_side: str | None = None,
    discogs_track_index: int | None = None,
    discogs_track_count: int | None = None,
    discogs_side_track_number: int | None = None,
    discogs_side_track_count: int | None = None,
    discogs_match_source: str | None = None,
    discogs_confidence: float | None = None,
    discogs_cover_url: str | None = None,
    discogs_year: int | None = None,
    discogs_label: str | None = None,
    discogs_catalog_number: str | None = None,
    discogs_expected_next_title: str | None = None,
    discogs_expected_next_artist: str | None = None,
    discogs_expected_next_position: str | None = None,
    discogs_expected_next_side: str | None = None,
    side_flip_prompt_active: bool = False,
    side_flip_from_side: str | None = None,
    side_flip_to_side: str | None = None,
    side_flip_next_title: str | None = None,
    side_flip_next_position: str | None = None,
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
                "discogs_release_id": discogs_release_id,
                "discogs_position": discogs_position,
                "discogs_side": discogs_side,
                "discogs_track_index": discogs_track_index,
                "discogs_track_count": discogs_track_count,
                "discogs_side_track_number": discogs_side_track_number,
                "discogs_side_track_count": discogs_side_track_count,
                "discogs_match_source": discogs_match_source,
                "discogs_confidence": discogs_confidence,
                "discogs_cover_url": discogs_cover_url,
                "discogs_year": discogs_year,
                "discogs_label": discogs_label,
                "discogs_catalog_number": discogs_catalog_number,
                "discogs_expected_next_title": discogs_expected_next_title,
                "discogs_expected_next_artist": discogs_expected_next_artist,
                "discogs_expected_next_position": discogs_expected_next_position,
                "discogs_expected_next_side": discogs_expected_next_side,
                "side_flip_prompt_active": side_flip_prompt_active,
                "side_flip_from_side": side_flip_from_side,
                "side_flip_to_side": side_flip_to_side,
                "side_flip_next_title": side_flip_next_title,
                "side_flip_next_position": side_flip_next_position,
            }
        )
    except Exception as exc:
        print(f"Could not write status to database: {exc}")


def write_side_flip_prompt(
    *,
    from_side: str | None,
    to_side: str | None,
    next_title: str | None,
    next_position: str | None,
) -> None:
    try:
        current = get_current_status() or {}
        current.update(
            {
                "side_flip_prompt_active": True,
                "side_flip_from_side": from_side,
                "side_flip_to_side": to_side,
                "side_flip_next_title": next_title,
                "side_flip_next_position": next_position,
            }
        )
        write_current_status(current)
    except Exception as exc:
        print(f"Could not write side-flip prompt status: {exc}")


def clear_side_flip_prompt() -> None:
    try:
        current = get_current_status()
        if not current:
            return
        if not current.get("side_flip_prompt_active") and not any(
            current.get(key)
            for key in (
                "side_flip_from_side",
                "side_flip_to_side",
                "side_flip_next_title",
                "side_flip_next_position",
            )
        ):
            return
        current.update(
            {
                "side_flip_prompt_active": False,
                "side_flip_from_side": None,
                "side_flip_to_side": None,
                "side_flip_next_title": None,
                "side_flip_next_position": None,
            }
        )
        write_current_status(current)
    except Exception as exc:
        print(f"Could not clear side-flip prompt status: {exc}")
