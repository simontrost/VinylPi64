from __future__ import annotations

import threading
from vinylpi.config.runtime import read_config
from vinylpi.core.display import show_fallback_image
from vinylpi.core.stats_db import get_current_status
from vinylpi.core.status import get_last_source_status
from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    SpotifyNotAuthorized,
    SpotifyNotConfigured,
    spotify_env_status,
)
from vinylpi.paths import BASE_DIR
from vinylpi.profiles import (
    get_active_storage_key,
    get_runtime_profile,
    set_runtime_profile,
)
from vinylpi.web.services import recognizer, spotify

_VALID_MODES = {"off", "vinyl", "spotify"}
_lock = threading.RLock()
_source_mode = "off"


class SourceBusyError(RuntimeError):
    def __init__(self, owner_name: str):
        self.owner_name = owner_name or "another profile"
        super().__init__(f"VinylPi playback is currently in use by {self.owner_name}.")


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
    # The Pixoo still receives the configured 64x64 fallback via
    # ``show_fallback_image``. The website uses the dedicated high-resolution
    # project logo instead, so the large dashboard artwork never looks pixelated.
    logo_path = BASE_DIR / "assets" / "readme" / "Logo.png"
    try:
        revision = int(logo_path.stat().st_mtime_ns // 1_000_000)
    except OSError:
        revision = 0

    return {
        "source": "off",
        "artist": "",
        "title": "Playback off",
        "album": "",
        "genre": "",
        "cover_url": "/assets/readme/Logo.png",
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

    viewer_key = get_active_storage_key()
    runtime = get_runtime_profile()
    runtime_key = str(runtime.get("storage_key") or "_guest")
    if viewer_key != runtime_key:
        busy = _fallback_status()
        busy.update(
            {
                "source": mode,
                "artist": f"{runtime.get('name') or 'Another profile'} is using VinylPi",
                "title": "Playback in use",
                "album": "Switching sources is locked until playback is turned off.",
            }
        )
        return busy

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



def get_status() -> dict:
    mode = get_mode()
    runtime = get_runtime_profile() if mode != "off" else None
    viewer_key = get_active_storage_key()
    runtime_key = str((runtime or {}).get("storage_key") or "")
    return {
        "mode": mode,
        "vinyl_running": recognizer.is_running(),
        "spotify_running": spotify.is_running(),
        "spotify": spotify_env_status(),
        "owner": runtime,
        "busy_for_viewer": bool(mode != "off" and runtime_key and runtime_key != viewer_key),
    }


def set_mode(mode: str) -> dict:
    global _source_mode
    requested = str(mode or "").strip().lower()
    if requested not in _VALID_MODES:
        raise ValueError(f"Unsupported source mode: {requested}")

    with _lock:
        current_mode = get_mode()
        viewer_key = get_active_storage_key()
        runtime = get_runtime_profile()
        runtime_key = str(runtime.get("storage_key") or "_guest")

        if current_mode != "off" and viewer_key != runtime_key:
            raise SourceBusyError(str(runtime.get("name") or "another profile"))

        # Clicking the already active source must be a no-op. In particular,
        # never replace a currently playing Pixoo frame with the fallback while
        # the recognizer/Spotify worker is still running.
        if requested == current_mode and requested != "off":
            return get_status()

        if requested == "off":
            spotify.stop()
            recognizer.stop()
            show_fallback_image()
            _source_mode = "off"
            status = get_status()
            set_runtime_profile(None)
            return status

        if requested == "vinyl":
            # Claim the single physical playback/recognition pipeline for the
            # browser profile that started it. Other signed-in devices keep
            # their own sessions and data, but cannot run recognition at the
            # same time.
            if current_mode == "off":
                set_runtime_profile(None if viewer_key == "_guest" else viewer_key)

            # IMPORTANT: the website may *display* the last Vinyl track from
            # the database, but it must never start its own Pixoo marquee for
            # that cached track. The recognizer is a separate process; starting
            # a second scrolling thread here makes both processes continuously
            # overwrite each other's Pixoo frames. This caused new songs and
            # the fallback image to flicker back to the previous session's
            # cover. Stop the old source, show one static fallback frame, then
            # let the recognizer become the sole Pixoo writer.
            spotify.stop()
            show_fallback_image()
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

        if current_mode == "off":
            set_runtime_profile(None if viewer_key == "_guest" else viewer_key)
        recognizer.stop()
        # Same rule as Vinyl: remembered Spotify metadata is dashboard-only.
        # Keep the Pixoo on the fallback until the Spotify worker confirms a
        # track that is actually playing now.
        show_fallback_image()
        spotify.start(silence_output=_debug_silence())
        _source_mode = "spotify"
        return get_status()
