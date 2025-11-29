# recognition.py
import asyncio
import threading
import time
from shazamio import Shazam
from PIL import Image

from config_loader import CONFIG
from image_utils import load_image, build_static_frame
from divoom_api import PixooClient, PixooError

_scroll_thread = None
_scroll_stop_event = threading.Event()


async def _recognize_async(wav_bytes: bytes):
    print("Starte Shazam-Erkennung ...")
    shazam = Shazam()

    debug_cfg = CONFIG["debug"]
    shazam_cfg = CONFIG.get("shazam", {})
    timeout_s = shazam_cfg.get("timeout_seconds", 15)

    result = await asyncio.wait_for(shazam.recognize(wav_bytes), timeout=timeout_s)

    track = result.get("track") or {}
    title = track.get("title") or "UNKNOWN"
    artist = track.get("subtitle") or "UNKNOWN"
    images = track.get("images") or {}
    cover_url = images.get("coverart")

    if debug_cfg.get("logs", False):
        print(f"Erkannt: {artist} – {title}")
        print(f"Cover-URL: {cover_url}")

    if not cover_url:
        print("Kein Cover gefunden.")
        return None

    cover_img = load_image(cover_url)
    return artist, title, cover_img


def recognize_song(wav_bytes: bytes):
    try:
        return asyncio.run(_recognize_async(wav_bytes))
    except Exception as e:
        print(f"Fehler bei der Erkennung: {e}")
        return None

def _scroll_loop(cover_img, artist: str, title: str):
    """
    Läuft in einem separaten Thread und schickt kontinuierlich Frames
    an den Pixoo, bis _scroll_stop_event gesetzt wird.
    """
    debug_cfg = CONFIG["debug"]
    img_cfg = CONFIG["image"]
    output_cfg = CONFIG.get("output", {})

    pixoo = PixooClient()
    tick = 0
    first_frame_saved = False

    while not _scroll_stop_event.is_set():
        frame = build_static_frame(cover_img, artist, title, tick=tick)

        # Debug/Preview nur einmal speichern
        if not first_frame_saved:
            pixoo_frame_path = output_cfg.get("pixoo_frame_path", "")
            preview_path = output_cfg.get("preview_path", "")

            if pixoo_frame_path:
                frame.save(pixoo_frame_path)
                if debug_cfg.get("logs", False):
                    print(f"Finished: {pixoo_frame_path} created.")

            if preview_path:
                scale = img_cfg["preview_scale"]
                size = img_cfg["canvas_size"]
                preview = frame.resize(
                    (size * scale, size * scale),
                    Image.Resampling.NEAREST
                )
                preview.save(preview_path)
                if debug_cfg.get("logs", False):
                    print(f"Finished: {preview_path} created.")

            first_frame_saved = True

        # an Pixoo senden
        try:
            pixoo.send_frame(frame)
        except PixooError as e:
            print(f"Pixoo not available or API-error: {e}")
            break

        tick += 1
        time.sleep(0.05)  # Scroll-Geschwindigkeit, hier bewusst blocking
                          # (wir sind ja in einem eigenen Thread)


def start_scrolling_display(cover_img, artist: str, title: str):
    global _scroll_thread, _scroll_stop_event

    if _scroll_thread is not None and _scroll_thread.is_alive():
        _scroll_stop_event.set()
        _scroll_thread.join()

    _scroll_stop_event = threading.Event()
    _scroll_thread = threading.Thread(
        target=_scroll_loop,
        args=(cover_img, artist, title),
        daemon=True,
    )
    _scroll_thread.start()



def show_fallback_image():
    """
    Zeigt das Fallback-Bild (aus CONFIG["fallback"]) statisch auf dem Pixoo
    und stoppt ggf. den laufenden Scroll-Thread.
    """
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

    # laufenden Scroll-Thread stoppen
    global _scroll_thread, _scroll_stop_event
    if _scroll_thread is not None and _scroll_thread.is_alive():
        _scroll_stop_event.set()
        _scroll_thread.join()

    try:
        # Bild laden (lokaler Pfad) und auf 64x64 skalieren
        fallback_img = Image.open(path).convert("RGB")
        fallback_resized = fallback_img.resize(
            (size, size),
            Image.Resampling.NEAREST  # schön „pixelig“
        )

        pixoo = PixooClient()
        pixoo.send_frame(fallback_resized)
        print(f"Fallback image '{path}' sent to Pixoo.")
    except Exception as e:
        print(f"Error showing fallback image: {e}")