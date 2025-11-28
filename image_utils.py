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
    GAP = img_cfg["margin_image_text"]  
    LINE_SPACING = img_cfg["line_spacing_margin"]
    TARGET_LINE_HEIGHT = img_cfg["line_height"]  
    FONT_START_SIZE = img_cfg["font_size"]       
    BOTTOM_MARGIN = img_cfg["bottom_margin"]

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

    text_area_top = y_cover + COVER_SIZE + GAP
    text_area_bottom = CANVAS_SIZE - BOTTOM_MARGIN
    available_h = text_area_bottom - text_area_top 

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    def load_font(size):
        try:
            return ImageFont.truetype(img_cfg["font_path"], size)
        except:
            print(f"using default font, {img_cfg["font_path"]} not found")
            return ImageFont.load_default()

    font_size = FONT_START_SIZE
    final_font = load_font(font_size)

    while font_size > 1:
        f = load_font(font_size)
        _, h_test = text_size("TEST", f)
        if h_test <= TARGET_LINE_HEIGHT:
            final_font = f
            break
        font_size -= 1

    def fit_width(txt, font):
        max_w = CANVAS_SIZE - 2
        w, _ = text_size(txt, font)
        if w <= max_w:
            return txt
        while w > max_w and len(txt) > 2:
            txt = txt[:-2] + "…"
            w, _ = text_size(txt, font)
        return txt

    artist = fit_width(artist, final_font)
    title = fit_width(title, final_font)

    w1, h1 = text_size(artist, final_font)
    w2, h2 = text_size(title, final_font)

    total_h = h1 + LINE_SPACING + h2

    y1 = text_area_top + max(0, (available_h - total_h) // 2)
    y2 = y1 + h1 + LINE_SPACING

    draw = ImageDraw.Draw(canvas)
    x1 = (CANVAS_SIZE - w1) // 2
    x2 = (CANVAS_SIZE - w2) // 2
    draw.text((x1, y1), artist, font=final_font, fill=text_color)
    draw.text((x2, y2), title, font=final_font, fill=text_color)

    bg_r, bg_g, bg_b = img_cfg["background_color"]
    pixels = canvas.load()
    for y in range(text_area_top, CANVAS_SIZE):
        for x in range(CANVAS_SIZE):
            r, g, b = pixels[x, y]
            if (r, g, b) != (bg_r, bg_g, bg_b):
                pixels[x, y] = (0, 0, 0)

    return canvas
