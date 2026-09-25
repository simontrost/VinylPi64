from io import BytesIO
import colorsys

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from vinylpi.config.runtime import read_config
from vinylpi.core.display_layout import normalize_image_config

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


def _load_font(size: int, font_path: str | None = None) -> ImageFont.FreeTypeFont:
    if font_path is None:
        font_path = str(read_config()["image"]["font_path"])
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

def _get_font_for_config(img_cfg: dict | None = None) -> tuple[ImageFont.FreeTypeFont, int]:
    img_cfg = img_cfg or read_config()["image"]
    target_glyph_height = int(img_cfg["font_size"])
    font_path = str(img_cfg["font_path"])

    best_font = _load_font(5, font_path)
    best_h = _measure_text_height(best_font)

    for size in range(1, 25):
        f = _load_font(size, font_path)
        h_test = _measure_text_height(f)
        if h_test == target_glyph_height:
            return f, h_test
        if abs(h_test - target_glyph_height) < abs(best_h - target_glyph_height):
            best_font = f
            best_h = h_test

    return best_font, best_h

def dynamic_text_color(bg_rgb: tuple[int, int, int]) -> tuple[int, int, int]:
    CONFIG = read_config()
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



def resolve_display_colors(
    cover_img: Image.Image,
    img_cfg: dict,
    *,
    bg_color: tuple[int, int, int] | None = None,
) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Resolve background/text colors while preserving manual selections.

    Normal automatic mode uses the dominant cover color as background and a
    black/white contrast color as text. In inverted automatic mode the cover
    color becomes the text color, while the automatic background becomes
    black or white for contrast. Manual colors are never swapped or changed.
    """
    use_dynamic_bg = bool(img_cfg.get("use_dynamic_bg", True))
    use_dynamic_text = bool(img_cfg.get("use_dynamic_text_color", False))
    invert_dynamic = bool(img_cfg.get("invert_dynamic_colors", False))

    cover_color = dynamic_bg_color(cover_img)

    if bg_color is not None:
        resolved_bg = tuple(bg_color)
    elif use_dynamic_bg:
        resolved_bg = dynamic_text_color(cover_color) if invert_dynamic else cover_color
    else:
        resolved_bg = tuple(img_cfg.get("manual_bg_color", [0, 0, 0]))

    if use_dynamic_text:
        resolved_text = cover_color if invert_dynamic else dynamic_text_color(resolved_bg)
    else:
        resolved_text = tuple(img_cfg.get("text_color", [255, 255, 255]))

    return resolved_bg, resolved_text

def build_static_frame(
    cover_img: Image.Image,
    artist: str,
    title: str,
    tick: int = 0,
    bg_color: tuple[int, int, int] | None = None,
    album: str | None = None,
) -> Image.Image:
    img_cfg = normalize_image_config(read_config()["image"])
    canvas_size = int(img_cfg["canvas_size"])
    top_margin = int(img_cfg["top_margin"])
    cover_size = int(img_cfg["cover_size"])
    cover_gap = int(img_cfg["margin_image_text"])
    line_gap = int(img_cfg["line_spacing_margin"])
    bg_color, text_color = resolve_display_colors(cover_img, img_cfg, bg_color=bg_color)

    canvas = Image.new("RGB", (canvas_size, canvas_size), bg_color)
    if img_cfg.get("show_cover", True):
        width, height = cover_img.size
        side = min(width, height)
        left = (width - side) // 2
        top = (height - side) // 2
        cover_square = cover_img.crop((left, top, left + side, top + side))
        cover_resized = cover_square.resize((cover_size, cover_size), Image.Resampling.BILINEAR)
        canvas.paste(cover_resized, ((canvas_size - cover_size) // 2, top_margin))

    values = {
        "artist": str(artist or ""),
        "title": str(title or ""),
        "album": str(album or ""),
    }
    if img_cfg.get("uppercase", False):
        values = {key: value.upper() for key, value in values.items()}

    font, glyph_height = _get_font_for_config(img_cfg)
    lines = [
        (key, values[key])
        for key in ("artist", "title", "album")
        if img_cfg.get(f"show_{key}", key != "album") and values[key]
    ]

    y = top_margin + (cover_size if img_cfg.get("show_cover", True) else 0)
    if img_cfg.get("show_cover", True) and lines:
        y += cover_gap

    prepared = []
    for index, (key, text) in enumerate(lines):
        width, _ = text_size(text, font)
        prepared.append((key, text, width, y))
        y += glyph_height
        if index < len(lines) - 1:
            y += line_gap

    scrolling = [width for _, _, width, _ in prepared if width > canvas_size]
    shared_range = max(scrolling) + canvas_size if len(scrolling) >= 2 else None
    draw = ImageDraw.Draw(canvas)

    for _, text, width, line_y in prepared:
        if width <= canvas_size:
            effective_width = max(0, width - 1) if width < canvas_size else width
            x = (canvas_size - effective_width) // 2
        else:
            scroll_range = shared_range or (width + canvas_size)
            x = canvas_size - (tick % scroll_range)
        draw.text((x, line_y), text, font=font, fill=text_color)

    return canvas

