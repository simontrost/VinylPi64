import asyncio
import threading
import time
from typing import Optional, Tuple

from shazamio import Shazam

from .config_loader import CONFIG
from .image_utils import (
    load_image,
    dynamic_bg_color,
    _get_font_for_config,
    text_size,
    dynamic_text_color,
)
from .divoom_api import PixooClient, PixooError
from PIL import Image, ImageDraw

_scroll_thread: Optional[threading.Thread] = None
_scroll_stop_event = threading.Event()

_shazam: Optional[Shazam] = None
_pixoo_client: Optional[PixooClient] = None


def _get_shazam() -> Shazam:
    global _shazam
    if _shazam is None:
        _shazam = Shazam()
    return _shazam


def _get_pixoo() -> PixooClient:
    global _pixoo_client
    if _pixoo_client is None:
        _pixoo_client = PixooClient()
    return _pixoo_client


def _stop_scroll_thread():
    global _scroll_thread, _scroll_stop_event

    if _scroll_thread is not None and _scroll_thread.is_alive():
        _scroll_stop_event.set()
        _scroll_thread.join()

    _scroll_thread = None
    _scroll_stop_event = threading.Event()

async def _recognize_async(wav_bytes: bytes):
    debug_log = CONFIG["debug"]["logs"]
    if debug_log:
        print("Starting Shazam-recognition ...")

    shazam = _get_shazam()

    shazam_cfg = CONFIG.get("shazam", {})
    timeout_s = shazam_cfg.get("timeout_seconds", 15)
    result = await asyncio.wait_for(shazam.recognize(wav_bytes), timeout=timeout_s)

    track = result.get("track") or {}
    title = track.get("title") or "UNKNOWN"
    artist = track.get("subtitle") or "UNKNOWN"
    images = track.get("images") or {}
    cover_url = images.get("coverart")

    album = None
    sections = track.get("sections") or []
    for sec in sections:
        if sec.get("type") == "SONG":
            for md in sec.get("metadata", []):
                if md.get("title") == "Album":
                    album = md.get("text")
                    break
            if album:
                break

    if debug_log:
        print(f"Detected: {artist} – {title}")
        print(f"Album: {album}")
        print(f"Cover-URL: {cover_url}")

    if not cover_url:
        if debug_log:
            print("No cover image found in Shazam response.")
        return None

    cover_img = load_image(cover_url)
    return artist, title, cover_img, album, cover_url


def recognize_song(wav_bytes: bytes,) -> Optional[Tuple[str, str, Image.Image, str | None, str | None]]:
    try:
        return asyncio.run(_recognize_async(wav_bytes))
    except Exception as e:
        print(f"Error while detecting: {e}")
        return None



def _prepare_base_canvas(cover_img: Image.Image, bg_color) -> Image.Image:
    img_cfg = CONFIG["image"]
    CANVAS_SIZE = img_cfg["canvas_size"]
    COVER_SIZE = img_cfg["cover_size"]
    TOP_MARGIN = img_cfg["top_margin"]

    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), bg_color)

    w, h = cover_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.BILINEAR)

    x_cover = (CANVAS_SIZE - COVER_SIZE) // 2
    y_cover = TOP_MARGIN
    canvas.paste(cover_resized, (x_cover, y_cover))

    return canvas

def _prepare_scroll_resources(cover_img: Image.Image, artist: str, title: str):
    img_cfg = CONFIG["image"]
    CANVAS_SIZE = img_cfg["canvas_size"]
    GAP_BETWEEN_LINES = img_cfg["line_spacing_margin"]
    GAP_BETWEEN_COVER_AND_BAND = img_cfg["margin_image_text"]
    TOP_MARGIN = img_cfg["top_margin"]
    COVER_SIZE = img_cfg["cover_size"]

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    use_dynamic_bg = img_cfg.get("use_dynamic_bg", True)
    if use_dynamic_bg:
        bg_color = dynamic_bg_color(cover_img)
    else:
        bg_color = tuple(img_cfg["manual_bg_color"])

    base_canvas = _prepare_base_canvas(cover_img, bg_color)

    font, glyph_h = _get_font_for_config()
    w1, _ = text_size(artist, font)
    w2, _ = text_size(title, font)

    if img_cfg.get("use_dynamic_text_color", False):
        TEXT_COLOR = dynamic_text_color(bg_color)
    else:
        TEXT_COLOR = tuple(img_cfg["text_color"])


    y_band = TOP_MARGIN + COVER_SIZE + GAP_BETWEEN_COVER_AND_BAND
    y_title = y_band + glyph_h + GAP_BETWEEN_LINES

    return {
        "artist": artist,
        "title": title,
        "bg_color": bg_color,
        "base_canvas": base_canvas,
        "font": font,
        "glyph_h": glyph_h,
        "w1": w1,
        "w2": w2,
        "y_band": y_band,
        "y_title": y_title,
        "TEXT_COLOR": TEXT_COLOR,
        "CANVAS_SIZE": CANVAS_SIZE,
    }


def _scroll_loop(cover_img: Image.Image, artist: str, title: str):
    debug_log = CONFIG["debug"]["logs"]
    debug_cfg = CONFIG["debug"]
    img_cfg = CONFIG["image"]

    pixoo = _get_pixoo()
    first_frame_saved = False

    res = _prepare_scroll_resources(cover_img, artist, title)

    speed_px_per_s = img_cfg.get("marquee_speed", 18)
    sleep_seconds = img_cfg.get("sleep_seconds", 0.01)

    tick_float = 0.0
    last_time = time.time()

    w1 = res["w1"]
    w2 = res["w2"]
    canvas_size = res["CANVAS_SIZE"]

    both_scroll = (w1 > canvas_size) and (w2 > canvas_size)
    sync_range = max(w1, w2) + canvas_size if both_scroll else None

    center_spacing_corr = 1

    while not _scroll_stop_event.is_set():
        now = time.time()
        dt = now - last_time
        last_time = now

        tick_float += speed_px_per_s * dt
        tick = int(tick_float)

        frame = res["base_canvas"].copy()
        draw = ImageDraw.Draw(frame)

        def compute_x(w_text: int, tick_val: int) -> int:
            if w_text <= canvas_size:
                if w_text < canvas_size and center_spacing_corr > 0:
                    effective_w = max(0, w_text - center_spacing_corr)
                else:
                    effective_w = w_text
                return (canvas_size - effective_w) // 2

            if both_scroll:
                scroll_range = sync_range
            else:
                scroll_range = w_text + canvas_size

            offset = tick_val % scroll_range
            return canvas_size - offset

        x_band = compute_x(w1, tick)
        x_title = compute_x(w2, tick)

        draw.text((x_band,  res["y_band"]),  res["artist"], font=res["font"], fill=res["TEXT_COLOR"])
        draw.text((x_title, res["y_title"]), res["title"],  font=res["font"], fill=res["TEXT_COLOR"])

        if not first_frame_saved:
            pixoo_frame_path = debug_cfg.get("pixoo_frame_path", "")
            preview_path = debug_cfg.get("preview_path", "")

            if pixoo_frame_path:
                frame.save(pixoo_frame_path)
                if debug_log:
                    print(f"Finished: {pixoo_frame_path} created.")

            if preview_path:
                scale = img_cfg["preview_scale"]
                size = img_cfg["canvas_size"]
                preview = frame.resize(
                    (size * scale, size * scale),
                    Image.Resampling.NEAREST,
                )
                preview.save(preview_path)
                if debug_log:
                    print(f"Finished: {preview_path} created.")

            first_frame_saved = True

        try:
            pixoo.send_frame(frame)
        except PixooError as e:
            print(f"Pixoo not available or API-error: {e}")
            break

        if _scroll_stop_event.wait(sleep_seconds):
            break


def start_scrolling_display(cover_img: Image.Image, artist: str, title: str):
    global _scroll_thread, _scroll_stop_event

    _stop_scroll_thread()

    _scroll_stop_event = threading.Event()
    _scroll_thread = threading.Thread(
        target=_scroll_loop,
        args=(cover_img, artist, title),
        daemon=True,
    )
    _scroll_thread.start()


def show_fallback_image():
    debug_log = CONFIG["debug"]["logs"]
    fallback_cfg = CONFIG.get("fallback", {})
    if not fallback_cfg.get("enabled", False):
        if debug_log:
            print("Fallback disabled in config, nothing to show.")
        return

    path = fallback_cfg.get("image_path")
    if not path:
        if debug_log:
            print("Fallback image path not set.")
        return

    img_cfg = CONFIG["image"]
    size = img_cfg["canvas_size"]

    _stop_scroll_thread()

    try:
        fallback_img = Image.open(path).convert("RGB")
        fallback_resized = fallback_img.resize(
            (size, size),
            Image.Resampling.NEAREST,
        )

        pixoo = _get_pixoo()
        pixoo.send_frame(fallback_resized)
        if debug_log:
            print(f"Fallback image '{path}' sent to Pixoo.")
    except Exception as e:
        print(f"Error showing fallback image: {e}")