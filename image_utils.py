from io import BytesIO
from collections import Counter

import requests
from PIL import Image, ImageDraw, ImageFont

from config_loader import CONFIG


def load_image(path_or_url: str) -> Image.Image:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        resp = requests.get(path_or_url, timeout=15)
        resp.raise_for_status()
        img = Image.open(BytesIO(resp.content))
    else:
        img = Image.open(path_or_url)
    return img.convert("RGB")


def relative_luminance(rgb):
    r, g, b = rgb
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def get_contrasting_color(img, k=8):
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


def text_size(text, font):
    dummy = Image.new("RGB", (1, 1))
    d = ImageDraw.Draw(dummy)
    bbox = d.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def build_static_frame(cover_img, artist: str, title: str) -> Image.Image:
    img_cfg = CONFIG["image"]

    CANVAS_SIZE = img_cfg["canvas_size"]
    COVER_SIZE = img_cfg["cover_size"]
    TOP_MARGIN = img_cfg["top_margin"]
    GAP_BETWEEN_COVER_TEXT = img_cfg["margin_image_text"]

    bg_r, bg_g, bg_b = img_cfg["background_color"]

    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (bg_r, bg_g, bg_b))

    w, h = cover_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.BILINEAR)

    if img_cfg["text_color_mode"] == "manual":
        text_color = tuple(img_cfg["text_color_manual"])
    else:
        text_color = get_contrasting_color(cover_resized)

    x_cover = (CANVAS_SIZE - COVER_SIZE) // 2
    y_cover = TOP_MARGIN
    canvas.paste(cover_resized, (x_cover, y_cover))

    text_area_top = y_cover + COVER_SIZE + GAP_BETWEEN_COVER_TEXT
    draw = ImageDraw.Draw(canvas)
    if text_area_top < CANVAS_SIZE:
        draw.rectangle([0, text_area_top, CANVAS_SIZE - 1, CANVAS_SIZE - 1],
                       fill=(bg_r, bg_g, bg_b))

    def load_font(size):
        try:
            return ImageFont.truetype(img_cfg["font_path"], size)
        except OSError:
            return ImageFont.load_default()

    if img_cfg["use_dynamic_font"]:
        font = load_font(img_cfg["font_size"])  
    else:
        font = load_font(img_cfg["font_size"])

    if img_cfg["uppercase"]:
        artist = artist.upper()
        title = title.upper()

    line1 = artist
    line2 = title

    max_width = CANVAS_SIZE - 2

    def fit_text(line):
        w, _ = text_size(line, font)
        if w <= max_width:
            return line
        while w > max_width and len(line) > 1:
            line = line[:-2] + "…"
            w, _ = text_size(line, font)
        return line

    line1 = fit_text(line1)
    line2 = fit_text(line2)

    w1, h1 = text_size(line1, font)
    w2, h2 = text_size(line2, font)

    remaining_h = CANVAS_SIZE - text_area_top
    total_text_h = h1 + 1 + h2
    y_text_start = text_area_top + max(0, (remaining_h - total_text_h) // 2)

    x1 = (CANVAS_SIZE - w1) // 2
    y1 = y_text_start
    draw.text((x1, y1), line1, font=font, fill=text_color)

    x2 = (CANVAS_SIZE - w2) // 2
    y2 = y1 + h1 + 1
    draw.text((x2, y2), line2, font=font, fill=text_color)

    return canvas
