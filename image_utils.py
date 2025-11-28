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
    COVER_SIZE = 46                        
    TOP_MARGIN = 1                        
    GAP_BETWEEN_COVER_AND_BAND = 3         
    GAP_BETWEEN_LINES = 3               
    FONT_SIZE = 5                          

    bg_r, bg_g, bg_b = img_cfg["background_color"]
    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (bg_r, bg_g, bg_b))

    w, h = cover_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.BILINEAR)

    bg_lum = relative_luminance((bg_r, bg_g, bg_b))
    text_color = (0, 0, 0) if bg_lum > 127 else (255, 255, 255)

    x_cover = (CANVAS_SIZE - COVER_SIZE) // 2
    y_cover = TOP_MARGIN
    canvas.paste(cover_resized, (x_cover, y_cover))

    # Font laden (5x5 Pixel-Font)
    def load_font():
        try:
            return ImageFont.truetype(img_cfg["font_path"], FONT_SIZE)
        except Exception:
            print(f'using default font, {img_cfg["font_path"]} not found')
            return ImageFont.load_default()

    font = load_font()

    if img_cfg.get("uppercase", True):
        artist = artist.upper()
        title = title.upper()

    def text_size(text, font):
        dummy = Image.new("RGB", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    def fit_width(txt, font):
        max_w = CANVAS_SIZE  
        w, _ = text_size(txt, font)
        if w <= max_w:
            return txt
        while w > max_w and len(txt) > 2:
            txt = txt[:-2] + "…"
            w, _ = text_size(txt, font)
        return txt

    artist = fit_width(artist, font)
    title  = fit_width(title, font)

    w1, h1 = text_size(artist, font) 
    w2, h2 = text_size(title, font)

    draw = ImageDraw.Draw(canvas)

    y_band = TOP_MARGIN + COVER_SIZE + GAP_BETWEEN_COVER_AND_BAND
    y_title = y_band + h1 + GAP_BETWEEN_LINES

    x_band = (CANVAS_SIZE - w1) // 2
    x_title = (CANVAS_SIZE - w2) // 2

    draw.text((x_band, y_band), artist, font=font, fill=text_color)
    draw.text((x_title, y_title), title, font=font, fill=text_color)

    return canvas
