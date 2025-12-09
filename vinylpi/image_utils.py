from io import BytesIO
from collections import Counter
import colorsys

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .config_loader import CONFIG

def load_image(path_or_url: str) -> Image.Image:
    if not path_or_url:
        raise ValueError("load_image: path_or_url is None or empty")

    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        resp = requests.get(path_or_url, timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
    else:
        img = Image.open(path_or_url)

    img = ImageOps.exif_transpose(img)

    return img.convert("RGB")



def relative_luminance(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def text_size(text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    img_cfg = CONFIG["image"]
    font_path = img_cfg["font_path"]
    cache_key = (font_path, size)

    if cache_key in _font_cache:
        return _font_cache[cache_key]

    try:
        font = ImageFont.truetype(font_path, size)
    except Exception:
        print(f'using default font, {font_path} not found')
        font = ImageFont.load_default()

    _font_cache[cache_key] = font
    return font

def _measure_text_height(font: ImageFont.FreeTypeFont, text: str = "A") -> int:
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[3] - bbox[1]

def _get_font_for_config() -> tuple[ImageFont.FreeTypeFont, int]:
    img_cfg = CONFIG["image"]
    TARGET_GLYPH_HEIGHT = img_cfg["font_size"]

    best_font = _load_font(5)
    best_h = _measure_text_height(best_font)

    for size in range(1, 25):
        f = _load_font(size)
        h_test = _measure_text_height(f)
        if h_test == TARGET_GLYPH_HEIGHT:
            return f, h_test
        if abs(h_test - TARGET_GLYPH_HEIGHT) < abs(best_h - TARGET_GLYPH_HEIGHT):
            best_font = f
            best_h = h_test

    return best_font, best_h

def dynamic_text_color(bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    img_cfg = CONFIG["image"]
    lum_threhsold = img_cfg.get("lum_threshold", 128)
    lum = relative_luminance(bg_rgb)
    return (0, 0, 0) if lum > lum_threhsold else (255, 255, 255)


def dynamic_bg_color(cover_img: Image.Image, num_colors: int = 8) -> tuple[int, int, int]:
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

def build_static_frame(
    cover_img: Image.Image,
    artist: str,
    title: str,
    tick: int = 0,
    bg_color: tuple[int, int, int] | None = None,
) -> Image.Image:
    img_cfg = CONFIG["image"]

    CANVAS_SIZE = img_cfg["canvas_size"]
    COVER_SIZE = img_cfg["cover_size"]
    TOP_MARGIN = img_cfg["top_margin"]
    GAP_BETWEEN_COVER_AND_BAND = img_cfg["margin_image_text"]
    GAP_BETWEEN_LINES = img_cfg["line_spacing_margin"]
    USE_DYNAMIC_BG = img_cfg.get("use_dynamic_bg", True)

    USE_DYNAMIC_BG = img_cfg.get("use_dynamic_bg", True)
    USE_DYNAMIC_TEXT = img_cfg.get("use_dynamic_text_color", False)

    if bg_color is None:
        if USE_DYNAMIC_BG:
            bg_color = dynamic_bg_color(cover_img)
        else:
            bg_color = tuple(img_cfg["manual_bg_color"])

    if USE_DYNAMIC_TEXT:
        TEXT_COLOR = dynamic_text_color(bg_color)
    else:
        TEXT_COLOR = tuple(img_cfg["text_color"])


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

    font, glyph_h = _get_font_for_config()

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()
    w1, _ = text_size(artist, font)
    w2, _ = text_size(title, font)

    draw = ImageDraw.Draw(canvas)

    y_band = TOP_MARGIN + COVER_SIZE + GAP_BETWEEN_COVER_AND_BAND
    y_title = y_band + glyph_h + GAP_BETWEEN_LINES

    both_scroll = (w1 > CANVAS_SIZE) and (w2 > CANVAS_SIZE)
    if both_scroll:
        sync_range = max(w1, w2) + CANVAS_SIZE

    def compute_x(w_text: int, tick_val: int) -> int:
        if w_text <= CANVAS_SIZE:
            return (CANVAS_SIZE - w_text) // 2

        if both_scroll:
            scroll_range = sync_range
        else:
            scroll_range = w_text + CANVAS_SIZE

        offset = tick_val % scroll_range
        return CANVAS_SIZE - offset

    x_band = compute_x(w1, tick)
    x_title = compute_x(w2, tick)

    draw.text((x_band, y_band), artist, font=font, fill=TEXT_COLOR)
    draw.text((x_title, y_title), title, font=font, fill=TEXT_COLOR)

    return canvas