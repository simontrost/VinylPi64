from __future__ import annotations

import threading
from pathlib import Path

from vinylpi.config.runtime import read_config
from vinylpi.core.display import show_fallback_image, start_scrolling_display
from vinylpi.core.image_utils import load_image
from vinylpi.core.stats_db import get_current_status
from vinylpi.core.status import get_last_source_status
from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    SpotifyNotAuthorized,
    SpotifyNotConfigured,
    spotify_env_status,
)
from vinylpi.paths import BASE_DIR, UPLOAD_DIR
from vinylpi.web.services import recognizer, spotify

_VALID_MODES = {"off", "vinyl", "spotify"}
_lock = threading.RLock()
_source_mode = "off"


def _debug_silence() -> bool:
    try:
        return not bool((read_config().get("debug") or {}).get("logs", False))
    except Exception:
        return True


def get_mode() -> str:
    global _source_mode
    if spotify.is_running():
        _source_mode = "spotify"
    elif recognizer.is_running():
        _source_mode = "vinyl"
    elif _source_mode != "off":
        _source_mode = "off"
    return _source_mode


def _fallback_status() -> dict:
    cfg = read_config()
    fallback_path = str((cfg.get("fallback") or {}).get("image_path") or "").strip()
    cover_url = "/static/images/logo.png"
    revision = 0

    if fallback_path:
        path = Path(fallback_path)
        if not path.is_absolute():
            path = BASE_DIR / path
        try:
            resolved = path.resolve()
            resolved.relative_to(UPLOAD_DIR.resolve())
            cover_url = f"/uploads/{resolved.name}"
            revision = int(resolved.stat().st_mtime_ns // 1_000_000)
        except (OSError, ValueError):
            pass

    return {
        "source": "off",
        "artist": "",
        "title": "Playback off",
        "album": "",
        "genre": "",
        "cover_url": cover_url,
        "bg_color": "#2b2b34",
        "track_id": "",
        "artist_id": "",
        "duration_ms": None,
        "updated_at": revision,
    }


def get_visible_status() -> dict:
    """Return the dashboard status for the selected source, not just the last writer."""
    mode = get_mode()
    if mode == "off":
        return _fallback_status()

    current = get_current_status()
    if current:
        current_source = str(current.get("source") or "").strip().lower()
        if current_source == mode:
            return current

    cached = get_last_source_status(mode)
    if cached:
        return cached

    waiting = _fallback_status()
    waiting["source"] = mode
    waiting["title"] = "Waiting for Spotify…" if mode == "spotify" else "Waiting for vinyl…"
    return waiting


def _restore_source_display(source: str) -> None:
    status = get_last_source_status(source)
    if not status or not status.get("cover_url"):
        show_fallback_image()
        return
    try:
        cover = load_image(str(status["cover_url"]))
        start_scrolling_display(
            cover,
            str(status.get("artist") or ""),
            str(status.get("title") or ""),
        )
    except Exception:
        # A stale remote cover URL should never prevent changing source.
        show_fallback_image()


def get_status() -> dict:
    return {
        "mode": get_mode(),
        "vinyl_running": recognizer.is_running(),
        "spotify_running": spotify.is_running(),
        "spotify": spotify_env_status(),
    }


def set_mode(mode: str) -> dict:
    global _source_mode
    requested = str(mode or "").strip().lower()
    if requested not in _VALID_MODES:
        raise ValueError(f"Unsupported source mode: {requested}")

    with _lock:
        if requested == "off":
            spotify.stop()
            recognizer.stop()
            show_fallback_image()
            _source_mode = "off"
            return get_status()

        if requested == "vinyl":
            spotify.stop()
            _restore_source_display("vinyl")
            recognizer.start(silence_output=_debug_silence())
            _source_mode = "vinyl"
            return get_status()

        spotify_status = spotify_env_status()
        if not spotify_status.get("configured"):
            raise RuntimeError(
                "Spotify app credentials are not configured in vinylpi.env."
            )
        if not spotify_status.get("connected"):
            raise PermissionError("This VinylPi profile is not connected to Spotify yet.")

        # Validate/refresh the profile-specific OAuth credential before switching
        # away from Vinyl. Expired tokens become a visible reconnect state.
        try:
            SpotifyClient().get_currently_playing()
        except SpotifyNotConfigured as exc:
            raise RuntimeError(str(exc)) from exc
        except SpotifyNotAuthorized as exc:
            raise PermissionError(str(exc)) from exc
        except SpotifyError as exc:
            raise ConnectionError(str(exc)) from exc

        recognizer.stop()
        _restore_source_display("spotify")
        spotify.start(silence_output=_debug_silence())
        _source_mode = "spotify"
        return get_status()
