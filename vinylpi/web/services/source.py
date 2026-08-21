from __future__ import annotations

import threading

from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    SpotifyNotAuthorized,
    SpotifyNotConfigured,
    spotify_env_status,
)
from vinylpi.web.services import recognizer, spotify
from vinylpi.config.runtime import read_config

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
            _source_mode = "off"
            return get_status()

        if requested == "vinyl":
            spotify.stop()
            recognizer.start(silence_output=_debug_silence())
            _source_mode = "vinyl"
            return get_status()

        spotify_status = spotify_env_status()
        if not spotify_status.get("configured"):
            raise RuntimeError(
                "Spotify is not configured. Add SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to .env."
            )
        if not spotify_status.get("connected"):
            raise PermissionError("Spotify is not connected yet.")

        # Validate/refresh the OAuth credential before switching away from vinyl.
        # This also turns an expired 6-month refresh token back into a visible
        # Connect Spotify state instead of spawning a worker that immediately dies.
        try:
            SpotifyClient().get_currently_playing()
        except SpotifyNotConfigured as exc:
            raise RuntimeError(str(exc)) from exc
        except SpotifyNotAuthorized as exc:
            raise PermissionError(str(exc)) from exc
        except SpotifyError as exc:
            raise ConnectionError(str(exc)) from exc

        recognizer.stop()
        spotify.start(silence_output=_debug_silence())
        _source_mode = "spotify"
        return get_status()
