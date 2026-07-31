from __future__ import annotations

import os
import threading
import time

from vinylpi.core.display import start_scrolling_display
from vinylpi.core.image_utils import load_image
from vinylpi.core.stats_db import get_current_status
from vinylpi.paths import DISPLAY_REFRESH_PATH


def request_display_refresh() -> None:
    DISPLAY_REFRESH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = DISPLAY_REFRESH_PATH.with_suffix(".tmp")
    tmp.write_text(str(time.time_ns()), encoding="utf-8")
    os.replace(tmp, DISPLAY_REFRESH_PATH)


def refresh_current_display() -> bool:
    status = get_current_status()
    if not status:
        return False

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
        last_token = None
        while True:
            try:
                token = DISPLAY_REFRESH_PATH.read_text(encoding="utf-8").strip()
            except FileNotFoundError:
                token = None
            except Exception as exc:
                if debug_log:
                    print(f"Display refresh watcher error: {exc}")
                token = None

            if token and token != last_token:
                last_token = token
                try:
                    refreshed = refresh_current_display()
                    if debug_log:
                        print("Pixoo display refreshed from current status." if refreshed else "No current song available for Pixoo refresh.")
                except Exception as exc:
                    print(f"Could not refresh current Pixoo display: {exc}")

            time.sleep(0.25)

    thread = threading.Thread(target=watch, name="vinylpi-display-refresh", daemon=True)
    thread.start()
    return thread
