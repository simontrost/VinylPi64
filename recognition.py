# recognition.py
import asyncio
import threading
import time

from shazamio import Shazam
from PIL import Image

from config_loader import CONFIG
from image_utils import load_image, prepare_track_layout, render_track_frame, TrackLayout
from divoom_api import PixooClient, PixooError


_scroll_thread = None
_scroll_stop_event = threading.Event()

_shazam = Shazam()

_last_track_key = None
_last_was_fallback = False


async def _recognize_async(wav_bytes: bytes) -> None:
    global _last_track_key, _last_was_fallback

    shazam_cfg = CONFIG.get("shazam", {})
    timeout_s = shazam_cfg.get("timeout_seconds", 15)

    debug_cfg = CONFIG.get("debug", {})
    debug_log = debug_cfg.get("logs", False)

    if debug_log:
        print("Start of Shazam recognition...")

    try:
        result = await asyncio.wait_for(_shazam.recognize(wav_bytes), timeout=timeout_s)
    except asyncio.TimeoutError:
        if debug_log:
            print(f"Shazam-recognition after {timeout_s}s terminated (Timeout).")
        show_fallback_image()
        _last_was_fallback = True
        return
    except Exception as e:
        print(f"Error during Shazam-recognition: {e}")
        show_fallback_image()
        _last_was_fallback = True
        return

    track = result.get("track") or {}
    if not track:
        if debug_log:
            print("Shazam-result doesn't contain 'track' infom show fallback.")
        show_fallback_image()
        _last_was_fallback = True
        return

    title = track.get("title") or "UNKNOWN"
    artist = track.get("subtitle") or "UNKNOWN"
    images = track.get("images") or {}
    cover_url = images.get("coverart")

    if debug_log:
        print(f"Erkannt: {artist} – {title}")
        print(f"Cover-URL: {cover_url}")

    track_key = f"{artist}::{title}"

    if track_key == _last_track_key and not _last_was_fallback:
        if debug_log:
            print("Same track as before, nothing to do.")
        return

    if not cover_url:
        if debug_log:
            print("No cover URL found, showing fallback image.")
        show_fallback_image()
        _last_track_key = track_key
        _last_was_fallback = True
        return

    try:
        cover_img = load_image(cover_url)
        layout = prepare_track_layout(cover_img, artist, title)
    except Exception as e:
        print(f"Error on loading/processing cover image: {e}")
        show_fallback_image()
        _last_track_key = track_key
        _last_was_fallback = True
        return

    start_scrolling_display(layout, artist, title)

    _last_track_key = track_key
    _last_was_fallback = False

    if debug_log:
        print("Scrolling display started.")


def run_recognition(wav_bytes: bytes) -> None:
    try:
        asyncio.run(_recognize_async(wav_bytes))
    except Exception as e:
        print(f"Error while detecting: {e}")
        show_fallback_image()


def _scroll_loop(layout: TrackLayout, artist: str, title: str) -> None:
    debug_cfg = CONFIG.get("debug", {})
    img_cfg = CONFIG["image"]

    pixoo = PixooClient()
    tick = 0
    first_frame_saved = False

    marquee_speed = img_cfg.get("marquee_speed", 1)
    frame_delay = img_cfg.get("frame_delay_seconds", 0.1)

    while not _scroll_stop_event.is_set():
        frame = render_track_frame(layout, artist, title, tick)

        if not first_frame_saved:
            pixoo_frame_path = debug_cfg.get("pixoo_frame_path", "")
            preview_path = debug_cfg.get("preview_path", "")

            if pixoo_frame_path:
                try:
                    frame.save(pixoo_frame_path)
                    if debug_cfg.get("logs", False):
                        print(f"Finished: {pixoo_frame_path} created.")
                except Exception as e:
                    print(f"Error saving pixoo_frame_path '{pixoo_frame_path}': {e}")

            if preview_path:
                try:
                    scale = img_cfg.get("preview_scale", 8)
                    size = img_cfg["canvas_size"]
                    preview = frame.resize(
                        (size * scale, size * scale),
                        Image.Resampling.NEAREST
                    )
                    preview.save(preview_path)
                    if debug_cfg.get("logs", False):
                        print(f"Finished: {preview_path} created.")
                except Exception as e:
                    print(f"Error creating preview '{preview_path}': {e}")

            first_frame_saved = True

        try:
            pixoo.send_frame(frame)
        except PixooError as e:
            print(f"Pixoo not available or API-error: {e}")
            break

        tick += marquee_speed
        time.sleep(frame_delay)


def start_scrolling_display(layout: TrackLayout, artist: str, title: str) -> None:
    global _scroll_thread, _scroll_stop_event

    if _scroll_thread is not None and _scroll_thread.is_alive():
        _scroll_stop_event.set()
        _scroll_thread.join()

    _scroll_stop_event = threading.Event()
    _scroll_thread = threading.Thread(
        target=_scroll_loop,
        args=(layout, artist, title),
        daemon=True,
    )
    _scroll_thread.start()


def show_fallback_image() -> None:
    fallback_cfg = CONFIG.get("fallback", {})
    if not fallback_cfg.get("enabled", False):
        print("Fallback disabled in config, nothing to show.")
        return

    path = fallback_cfg.get("image_path")
    if not path:
        print("Fallback image path not set.")
        return

    img_cfg = CONFIG["image"]
    size = img_cfg["canvas_size"]

    global _scroll_thread, _scroll_stop_event
    if _scroll_thread is not None and _scroll_thread.is_alive():
        _scroll_stop_event.set()
        _scroll_thread.join()

    try:
        fallback_img = Image.open(path).convert("RGB")
        fallback_resized = fallback_img.resize(
            (size, size),
            Image.Resampling.NEAREST
        )

        pixoo = PixooClient()
        pixoo.send_frame(fallback_resized)
        print(f"Fallback image '{path}' sent to Pixoo.")
    except Exception as e:
        print(f"Error showing fallback image: {e}")