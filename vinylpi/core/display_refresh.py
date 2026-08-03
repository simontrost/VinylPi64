from __future__ import annotations

import os
import threading
import time

from vinylpi.core.display import show_fallback_image, show_side_flip_prompt, start_scrolling_display
from vinylpi.core.image_utils import load_image
from vinylpi.core.stats_db import get_current_status
from vinylpi.paths import DISPLAY_REFRESH_PATH


def request_display_refresh() -> None:
    DISPLAY_REFRESH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DISPLAY_REFRESH_PATH.with_suffix(".tmp")
    tmp.write_text(str(time.time_ns()), encoding="utf-8")
    os.replace(tmp, DISPLAY_REFRESH_PATH)


def _read_refresh_token(*, debug_log: bool = False) -> str | None:
    try:
        return DISPLAY_REFRESH_PATH.read_text(encoding="utf-8").strip() or None
    except FileNotFoundError:
        return None
    except Exception as exc:
        if debug_log:
            print(f"Display refresh watcher error: {exc}")
        return None


def refresh_current_display() -> bool:
    status = get_current_status()
    if not status:
        return False

    # A side-flip prompt is a real display state. Refreshing settings or
    # restarting the recognizer must not replace it with the last song.
    if bool(status.get("side_flip_prompt_active")):
        shown = show_side_flip_prompt(
            status.get("side_flip_to_side"),
            next_position=status.get("side_flip_next_position"),
        )
        if shown:
            return True
        # If the turn-record image was disabled while it was active, fall back
        # to the independently configured generic fallback instead.
        if show_fallback_image():
            return True

    artist = str(status.get("artist") or "").strip()
    title = str(status.get("title") or "").strip()
    cover_url = str(status.get("cover_url") or "").strip()
    if not artist or not title or not cover_url:
        return False

    cover_image = load_image(cover_url)
    start_scrolling_display(cover_image, artist, title)
    return True


def start_display_refresh_watcher(*, debug_log: bool = False) -> threading.Thread:
    def watch() -> None:
        # Treat a token already present on disk as processed. Otherwise every
        # recognizer restart replays the last saved song immediately.
        last_token = _read_refresh_token(debug_log=debug_log)

        while True:
            token = _read_refresh_token(debug_log=debug_log)

            if token and token != last_token:
                last_token = token
                try:
                    refreshed = refresh_current_display()
                    if debug_log:
                        print(
                            "Pixoo display refreshed from current status."
                            if refreshed
                            else "No current display state available for Pixoo refresh."
                        )
                except Exception as exc:
                    print(f"Could not refresh current Pixoo display: {exc}")

            time.sleep(0.25)

    thread = threading.Thread(
        target=watch,
        name="vinylpi-display-refresh",
        daemon=True,
    )
    thread.start()
    return thread
