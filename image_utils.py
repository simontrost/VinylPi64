from dataclasses import dataclass
from io import BytesIO
from collections import Counter
import colorsys
from typing import Tuple

import requests
from PIL import Image, ImageDraw, ImageFont

from config_loader import CONFIG


@dataclass
class TrackLayout:
    cover: Image.Image
    font: ImageFont.FreeTypeFont
    text_color: Tuple[int, int, int]
    bg_color: Tuple[int, int, int]
    y_band: int
    y_title: int
    w_band: int
    w_title: int
    canvas_size: int


def load_image(path_or_url: str) -> Image.Image:
    if path_or_url.startswith(("http://", "https://")):
        resp = requests.get(path_or_url, timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
    else:
        img = Image.open(path_or_url)
    return img.convert("RGB")


def relative_luminance(rgb: Tuple[int, int, int]) -> float:
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def get_contrasting_color(img: Image.Image, k: int = 8) -> Tuple[int, int, int]:
    small = img.resize((k, k), Image.Resampling.BILINEAR)
    pixels = list(small.getdata())
    counts = Counter(pixels)

    candidates = []
    for color, freq in counts.items():
        lum = relative_luminance(color)
        if lum < 220:
            candidates.append((freq, lum, color))

    if not candidates:
        color = counts.most_common(1)[0][0]
    else:
        candidates.sort(key=lambda x: (-x[0], x[1]))
        color = candidates[0][2]

    lum = relative_luminance(color)
    if lum > 180:
        factor = 180 / lum
        r, g, b = color
        color = (int(r * factor), int(g * factor), int(b * factor))
    return color


def text_size(text: str, font: ImageFont.FreeTypeFont) -> Tuple[int, int]:
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def choose_font_for_height(target_height: int) -> ImageFont.FreeTypeFont:
    img_cfg = CONFIG["image"]
    font_path = img_cfg.get("font_path", "")

    def load_font(size: int) -> ImageFont.FreeTypeFont:
        try:
            if font_path:
                return ImageFont.truetype(font_path, size)
            else:
                raise OSError("no font_path set")
        except Exception:
            print(f'Using default font, "{font_path}" not found or invalid.')
            return ImageFont.load_default()

    def measure_text_height(font: ImageFont.FreeTypeFont, text: str = "A") -> int:
        dummy = Image.new("RGB", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    best_font = load_font(target_height)
    best_h = measure_text_height(best_font)

    for size in range(1, 26):
        f = load_font(size)
        h_test = measure_text_height(f)
        if h_test == target_height:
            return f
        if abs(h_test - target_height) < abs(best_h - target_height):
            best_font = f
            best_h = h_test

    return best_font


def compute_x(w_text: int, tick: int, canvas_size: int) -> int:
    if w_text <= canvas_size:
        return (canvas_size - w_text) // 2
    scroll_range = w_text + canvas_size
    offset = tick % scroll_range
    return canvas_size - offset


def dynamic_bg_color(cover_img: Image.Image, num_colors: int = 8) -> Tuple[int, int, int]:
    small = cover_img.resize((64, 64), Image.Resampling.BILINEAR)

    pal_img = small.convert("P", palette=Image.ADAPTIVE, colors=num_colors)
    palette = pal_img.getpalette()
    color_counts = pal_img.getcolors()

    if not color_counts:
        return (40, 40, 40)

    color_counts.sort(reverse=True, key=lambda x: x[0])

    candidates = []
    for rank, (count, idx) in enumerate(color_counts):
        r = palette[3 * idx + 0]
        g = palette[3 * idx + 1]
        b = palette[3 * idx + 2]

        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        lum = relative_luminance((r, g, b))

        if s < 0.25:
            continue
        if lum < 30 or lum > 230:
            continue

        score = count
        if rank == 0:
            score *= 0.7 

        candidates.append((score, (r, g, b)))

    if not candidates:
        _, idx = color_counts[0]
        r = palette[3 * idx + 0]
        g = palette[3 * idx + 1]
        b = palette[3 * idx + 2]
        base = (r, g, b)
    else:
        _, base = max(candidates, key=lambda x: x[0])

    r, g, b = base

    lum = relative_luminance((r, g, b))
    target_min, target_max = 60, 180

    if lum < target_min:
        factor = target_min / max(lum, 1)
        r = min(int(r * factor), 255)
        g = min(int(g * factor), 255)
        b = min(int(b * factor), 255)
    elif lum > target_max:
        factor = target_max / lum
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)

    return (r, g, b)



def _resolve_background_color(img_cfg: dict, cover_img: Image.Image) -> Tuple[int, int, int]:
    if img_cfg.get("use_dynamic_bg", False):
        return dynamic_bg_color(cover_img)

    if "manual_bg_color" in img_cfg:
        r, g, b = img_cfg["manual_bg_color"]
        return int(r), int(g), int(b)

    bg = img_cfg.get("background_color", [0, 0, 0])
    r, g, b = bg
    return int(r), int(g), int(b)


def _resolve_text_color(img_cfg: dict, cover_img: Image.Image, bg_color: Tuple[int, int, int]) -> Tuple[int, int, int]:
    if "text_color" in img_cfg:
        r, g, b = img_cfg["text_color"]
        return int(r), int(g), int(b)

    mode = img_cfg.get("text_color_mode", "manual")

    if mode == "manual":
        r, g, b = img_cfg.get("text_color_manual", [255, 255, 255])
        return int(r), int(g), int(b)
    elif mode == "dominant":
        return get_contrasting_color(cover_img)
    else:
        bg_lum = relative_luminance(bg_color)
        return (0, 0, 0) if bg_lum > 127 else (255, 255, 255)


def prepare_track_layout(cover_img: Image.Image, artist: str, title: str) -> TrackLayout:
    img_cfg = CONFIG["image"]

    CANVAS_SIZE = img_cfg["canvas_size"]
    COVER_SIZE = img_cfg["cover_size"]
    TOP_MARGIN = img_cfg["top_margin"]
    GAP_BETWEEN_LINES = img_cfg["line_spacing_margin"]
    TARGET_GLYPH_HEIGHT = img_cfg["font_size"]

    bg_color = _resolve_background_color(img_cfg, cover_img)

    text_color = _resolve_text_color(img_cfg, cover_img, bg_color)

    w, h = cover_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.BILINEAR)

    font = choose_font_for_height(TARGET_GLYPH_HEIGHT)

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    w_band, _ = text_size(artist, font)
    w_title, _ = text_size(title, font)

    y_band = TOP_MARGIN + ((COVER_SIZE - TARGET_GLYPH_HEIGHT) // 2)
    y_title = y_band + TARGET_GLYPH_HEIGHT + GAP_BETWEEN_LINES

    return TrackLayout(
        cover=cover_resized,
        font=font,
        text_color=text_color,
        bg_color=bg_color,
        y_band=y_band,
        y_title=y_title,
        w_band=w_band,
        w_title=w_title,
        canvas_size=CANVAS_SIZE,
    )


def render_track_frame(layout: TrackLayout, artist: str, title: str, tick: int) -> Image.Image:
    img_cfg = CONFIG["image"]
    CANVAS_SIZE = layout.canvas_size
    TOP_MARGIN = img_cfg["top_margin"]

    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), layout.bg_color)
    draw = ImageDraw.Draw(canvas)

    canvas.paste(layout.cover, (0, TOP_MARGIN))

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    x_band = compute_x(layout.w_band, tick, CANVAS_SIZE)
    x_title = compute_x(layout.w_title, tick, CANVAS_SIZE)

    draw.text((x_band, layout.y_band), artist, font=layout.font, fill=layout.text_color)
    draw.text((x_title, layout.y_title), title, font=layout.font, fill=layout.text_color)

    return canvas