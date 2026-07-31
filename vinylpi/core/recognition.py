from __future__ import annotations

import re
from typing import Any

from vinylpi.core.genre_tags import normalize_genre
from vinylpi.core.image_utils import load_image
from vinylpi.core.models import RecognizedTrack
from vinylpi.integrations.shazam_client import recognize_audio
from vinylpi.config.runtime import read_config


def _first_text(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _extract_album(track: dict[str, Any]) -> str | None:
    for section in track.get("sections") or []:
        if section.get("type") != "SONG":
            continue
        for item in section.get("metadata") or []:
            if str(item.get("title") or "").casefold() == "album":
                return _first_text(item.get("text"))
    return None


def _parse_duration_text(value: object) -> int | None:
    text = str(value or "").strip()
    if not text:
        return None

    if text.isdigit():
        number = int(text)
        if 30_000 <= number <= 30 * 60_000:
            return number

    match = re.fullmatch(r"(?:(\d+):)?(\d{1,2}):(\d{2})", text)
    if match:
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = int(match.group(3))
        return ((hours * 60 + minutes) * 60 + seconds) * 1000

    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text)
    if match:
        return (int(match.group(1)) * 60 + int(match.group(2))) * 1000

    return None


def _valid_duration(value: object) -> int | None:
    try:
        duration = int(float(value))
    except (TypeError, ValueError):
        return None
    if 30_000 <= duration <= 30 * 60_000:
        return duration
    return None


def _extract_duration_ms(track: dict[str, Any]) -> int | None:
    """Use duration data when Shazam includes it; many responses omit it."""
    direct_candidates = (
        track.get("durationInMillis"),
        track.get("duration_ms"),
        track.get("durationMillis"),
        (track.get("attributes") or {}).get("durationInMillis"),
    )
    for candidate in direct_candidates:
        duration = _valid_duration(candidate)
        if duration:
            return duration

    for section in track.get("sections") or []:
        for item in section.get("metadata") or []:
            label = str(item.get("title") or "").casefold()
            if label in {"duration", "length", "track length"}:
                duration = _parse_duration_text(item.get("text"))
                if duration:
                    return duration
    return None


def _extract_genre(track: dict[str, Any]) -> str | None:
    genres = track.get("genres")
    if isinstance(genres, dict):
        return normalize_genre(genres.get("primary") or genres.get("secondary"))
    return normalize_genre(genres)


def _extract_artist_id(track: dict[str, Any]) -> str | None:
    for artist in track.get("artists") or []:
        artist_id = artist.get("adamid") or artist.get("id")
        if artist_id is not None:
            return str(artist_id)
    return None


def _recognize(wav_bytes: bytes) -> RecognizedTrack | None:
    cfg = read_config()
    debug_log = bool((cfg.get("debug") or {}).get("logs", False))
    timeout_seconds = float((cfg.get("shazam") or {}).get("timeout_seconds", 15))

    if debug_log:
        print("Starting Shazam recognition ...")

    result = recognize_audio(wav_bytes, timeout_seconds=timeout_seconds)
    track = result.get("track") or {}
    if not isinstance(track, dict) or not track:
        return None

    title = _first_text(track.get("title")) or "UNKNOWN"
    artist = _first_text(track.get("subtitle")) or "UNKNOWN"
    images = track.get("images") or {}
    if not isinstance(images, dict):
        images = {}
    cover_url = _first_text(images.get("coverart") or images.get("coverarthq"))

    if not cover_url:
        if debug_log:
            print("No cover image found in Shazam response.")
        return None

    recognized = RecognizedTrack(
        artist=artist,
        title=title,
        album=_extract_album(track),
        cover_url=cover_url,
        cover_image=load_image(cover_url),
        genre=_extract_genre(track),
        shazam_track_id=_first_text(track.get("key") or track.get("id")),
        shazam_artist_id=_extract_artist_id(track),
        duration_ms=_extract_duration_ms(track),
    )

    if debug_log:
        print(f"Detected: {recognized.artist} – {recognized.title}")
        print(f"Album: {recognized.album}")
        print(f"Genre: {recognized.genre}")
        print(f"Shazam track ID: {recognized.shazam_track_id}")
        print(f"Cover URL: {recognized.cover_url}")

    return recognized


def recognize_song(wav_bytes: bytes) -> RecognizedTrack | None:
    try:
        return _recognize(wav_bytes)
    except Exception as exc:
        print(f"Error while detecting: {exc}")
        return None
