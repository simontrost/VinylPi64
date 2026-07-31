from __future__ import annotations

import threading
import time
from typing import Optional

from PIL import Image, ImageDraw

from vinylpi.core.image_utils import (
    _get_font_for_config,
    dynamic_bg_color,
    dynamic_text_color,
    text_size,
)
from vinylpi.integrations.divoom_api import PixooClient, PixooError
from vinylpi.config.runtime import read_config

_scroll_thread: Optional[threading.Thread] = None
_scroll_stop_event = threading.Event()
_pixoo_client: Optional[PixooClient] = None
_display_lock = threading.RLock()


def _get_pixoo() -> PixooClient:
    global _pixoo_client
    if _pixoo_client is None:
        _pixoo_client = PixooClient()
    return _pixoo_client


def _reset_pixoo_client() -> None:
    global _pixoo_client
    _pixoo_client = None


def stop_scrolling_display() -> None:
    global _scroll_thread, _scroll_stop_event

    with _display_lock:
        if _scroll_thread is not None and _scroll_thread.is_alive():
            _scroll_stop_event.set()
            _scroll_thread.join(timeout=3)

        _scroll_thread = None
        _scroll_stop_event = threading.Event()


def _prepare_base_canvas(cover_img: Image.Image, bg_color: tuple[int, int, int]) -> Image.Image:
    img_cfg = read_config()["image"]
    canvas_size = int(img_cfg["canvas_size"])
    cover_size = int(img_cfg["cover_size"])
    top_margin = int(img_cfg["top_margin"])

    canvas = Image.new("RGB", (canvas_size, canvas_size), bg_color)

    width, height = cover_img.size
    side = min(width, height)
    left = (width - side) // 2
    top = (height - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize(
        (cover_size, cover_size),
        Image.Resampling.BILINEAR,
    )

    x_cover = (canvas_size - cover_size) // 2
    canvas.paste(cover_resized, (x_cover, top_margin))
    return canvas


def _prepare_scroll_resources(cover_img: Image.Image, artist: str, title: str) -> dict:
    img_cfg = read_config()["image"]
    canvas_size = int(img_cfg["canvas_size"])
    gap_between_lines = int(img_cfg["line_spacing_margin"])
    gap_after_cover = int(img_cfg["margin_image_text"])
    top_margin = int(img_cfg["top_margin"])
    cover_size = int(img_cfg["cover_size"])

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    if img_cfg.get("use_dynamic_bg", True):
        bg_color = dynamic_bg_color(cover_img)
    else:
        bg_color = tuple(img_cfg["manual_bg_color"])

    base_canvas = _prepare_base_canvas(cover_img, bg_color)
    font, glyph_height = _get_font_for_config()
    artist_width, _ = text_size(artist, font)
    title_width, _ = text_size(title, font)

    if img_cfg.get("use_dynamic_text_color", False):
        text_color = dynamic_text_color(bg_color)
    else:
        text_color = tuple(img_cfg["text_color"])

    artist_y = top_margin + cover_size + gap_after_cover
    title_y = artist_y + glyph_height + gap_between_lines

    return {
        "artist": artist,
        "title": title,
        "base_canvas": base_canvas,
        "font": font,
        "artist_width": artist_width,
        "title_width": title_width,
        "artist_y": artist_y,
        "title_y": title_y,
        "text_color": text_color,
        "canvas_size": canvas_size,
    }


def _text_x(width: int, tick: int, *, canvas_size: int, shared_range: int | None) -> int:
    if width <= canvas_size:
        effective_width = max(0, width - 1) if width < canvas_size else width
        return (canvas_size - effective_width) // 2

    scroll_range = shared_range or (width + canvas_size)
    return canvas_size - (tick % scroll_range)


def _scroll_loop(cover_img: Image.Image, artist: str, title: str) -> None:
    cfg = read_config()
    debug_log = bool(cfg["debug"]["logs"])
    debug_cfg = cfg["debug"]
    img_cfg = cfg["image"]

    try:
        pixoo = _get_pixoo()
    except PixooError as exc:
        print(f"Pixoo not available or API-error: {exc}")
        _reset_pixoo_client()
        return

    resources = _prepare_scroll_resources(cover_img, artist, title)
    speed_px_per_s = float(img_cfg.get("marquee_speed", 18))
    sleep_seconds = max(0.01, float(img_cfg.get("sleep_seconds", 0.05)))

    artist_width = resources["artist_width"]
    title_width = resources["title_width"]
    canvas_size = resources["canvas_size"]
    both_scroll = artist_width > canvas_size and title_width > canvas_size
    shared_range = max(artist_width, title_width) + canvas_size if both_scroll else None

    first_frame_saved = False
    tick_float = 0.0
    last_time = time.monotonic()

    while not _scroll_stop_event.is_set():
        now = time.monotonic()
        tick_float += speed_px_per_s * (now - last_time)
        last_time = now
        tick = int(tick_float)

        frame = resources["base_canvas"].copy()
        draw = ImageDraw.Draw(frame)
        artist_x = _text_x(
            artist_width,
            tick,
            canvas_size=canvas_size,
            shared_range=shared_range,
        )
        title_x = _text_x(
            title_width,
            tick,
            canvas_size=canvas_size,
            shared_range=shared_range,
        )

        draw.text(
            (artist_x, resources["artist_y"]),
            resources["artist"],
            font=resources["font"],
            fill=resources["text_color"],
        )
        draw.text(
            (title_x, resources["title_y"]),
            resources["title"],
            font=resources["font"],
            fill=resources["text_color"],
        )

        if not first_frame_saved:
            pixoo_frame_path = debug_cfg.get("pixoo_frame_path") or ""
            preview_path = debug_cfg.get("preview_path") or ""
            if pixoo_frame_path:
                frame.save(pixoo_frame_path)
                if debug_log:
                    print(f"Finished: {pixoo_frame_path} created.")
            if preview_path:
                scale = int(img_cfg["preview_scale"])
                preview = frame.resize(
                    (canvas_size * scale, canvas_size * scale),
                    Image.Resampling.NEAREST,
                )
                preview.save(preview_path)
                if debug_log:
                    print(f"Finished: {preview_path} created.")
            first_frame_saved = True

        try:
            pixoo.send_frame(frame)
        except PixooError as exc:
            print(f"Pixoo not available or API-error: {exc}")
            _reset_pixoo_client()
            break

        if _scroll_stop_event.wait(sleep_seconds):
            break


def start_scrolling_display(cover_img: Image.Image, artist: str, title: str) -> None:
    global _scroll_thread, _scroll_stop_event

    with _display_lock:
        stop_scrolling_display()
        _scroll_stop_event = threading.Event()
        _scroll_thread = threading.Thread(
            target=_scroll_loop,
            args=(cover_img, artist, title),
            name="vinylpi-pixoo-scroll",
            daemon=True,
        )
        _scroll_thread.start()


def _send_static_frame(frame: Image.Image, *, debug_label: str | None = None) -> None:
    cfg = read_config()
    debug_log = bool(cfg["debug"]["logs"])

    with _display_lock:
        stop_scrolling_display()
        try:
            _get_pixoo().send_frame(frame)
            if debug_log and debug_label:
                print(debug_label)
        except Exception as exc:
            _reset_pixoo_client()
            print(f"Error showing static Pixoo image: {exc}")


def _generate_side_flip_prompt_frame(
    next_side: str | None,
    *,
    next_position: str | None = None,
) -> Image.Image:
    cfg = read_config()
    size = int(cfg["image"]["canvas_size"])
    img = Image.new("RGB", (size, size), (20, 16, 28))
    draw = ImageDraw.Draw(img)

    accent = (245, 197, 66)
    pink = (223, 55, 144)
    text = (250, 247, 242)
    muted = (164, 156, 176)
    vinyl_fill = (11, 11, 14)
    vinyl_outline = (76, 72, 91)

    draw.rounded_rectangle((1, 1, size - 2, size - 2), radius=8, outline=(66, 56, 80), width=1)
    draw.ellipse((5, 9, 31, 35), fill=vinyl_fill, outline=vinyl_outline, width=1)
    draw.ellipse((10, 14, 26, 30), outline=(110, 100, 120), width=1)
    draw.ellipse((16, 20, 20, 24), fill=accent)
    draw.arc((10, 3, 34, 27), 320, 80, fill=pink, width=2)
    draw.polygon([(33, 6), (39, 9), (34, 13)], fill=pink)

    font, _ = _get_font_for_config()
    label_one = "TURN"
    label_two = "RECORD"
    side_text = f"SIDE {str(next_side or '?').upper()}"
    pos_text = (str(next_position or "").strip().upper() or side_text)

    draw.text((37, 10), label_one, font=font, fill=text)
    draw.text((37, 18), label_two, font=font, fill=text)
    draw.text((7, 44), side_text, font=font, fill=accent)
    if pos_text and pos_text != side_text:
        draw.text((7, 52), pos_text, font=font, fill=muted)
    else:
        draw.text((7, 52), "FLIP TO CONTINUE", font=font, fill=muted)
    return img


def _load_side_flip_prompt_frame(
    next_side: str | None,
    *,
    next_position: str | None = None,
) -> Image.Image:
    cfg = read_config()
    size = int(cfg["image"]["canvas_size"])
    fallback_cfg = cfg.get("fallback") or {}
    path = str(fallback_cfg.get("side_flip_image_path") or "").strip()

    if path:
        try:
            frame = Image.open(path).convert("RGB")
            if frame.size != (size, size):
                frame = frame.resize((size, size), Image.Resampling.NEAREST)

            # The bundled asset contains a bottom badge. Repaint its center so
            # the same image can be used for A -> B and C -> D transitions.
            draw = ImageDraw.Draw(frame)
            badge_left = max(1, int(size * 0.245))
            badge_top = max(1, int(size * 0.82))
            badge_right = min(size - 2, int(size * 0.755))
            badge_bottom = min(size - 2, int(size * 0.955))
            draw.rectangle(
                (badge_left, badge_top, badge_right, badge_bottom),
                fill=(10, 8, 17),
            )

            font, _ = _get_font_for_config()
            side_label = f"SIDE {str(next_side or '?').upper()}"
            bbox = draw.textbbox((0, 0), side_label, font=font)
            text_width = bbox[2] - bbox[0]
            text_height = bbox[3] - bbox[1]
            x = max(1, (size - text_width) // 2)
            y = badge_top + max(0, (badge_bottom - badge_top - text_height) // 2) - bbox[1]
            draw.text((x, y), side_label, font=font, fill=(245, 197, 66))
            return frame
        except Exception as exc:
            if bool(cfg["debug"]["logs"]):
                print(f"Could not load side-flip image '{path}': {exc}; using generated prompt.")

    return _generate_side_flip_prompt_frame(next_side, next_position=next_position)


def show_side_flip_prompt(next_side: str | None, *, next_position: str | None = None) -> None:
    frame = _load_side_flip_prompt_frame(next_side, next_position=next_position)
    label = f"Side-flip prompt for side {next_side or '?'} sent to Pixoo."
    _send_static_frame(frame, debug_label=label)


def show_fallback_image() -> None:
    cfg = read_config()
    debug_log = bool(cfg["debug"]["logs"])
    fallback_cfg = cfg.get("fallback") or {}
    if not fallback_cfg.get("enabled", False):
        if debug_log:
            print("Fallback disabled in config, nothing to show.")
        return

    path = fallback_cfg.get("image_path")
    if not path:
        if debug_log:
            print("Fallback image path not set.")
        return

    size = int(cfg["image"]["canvas_size"])

    try:
        fallback_img = Image.open(path).convert("RGB")
        fallback_resized = fallback_img.resize(
            (size, size),
            Image.Resampling.NEAREST,
        )
        _send_static_frame(fallback_resized, debug_label=f"Fallback image '{path}' sent to Pixoo.")
    except Exception as exc:
        _reset_pixoo_client()
        print(f"Error showing fallback image: {exc}")
