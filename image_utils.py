from io import BytesIO
from collections import Counter
import requests
from PIL import Image, ImageDraw, ImageFont

from config_loader import CONFIG
def load_image(path_or_url: str) -> Image.Image:
    if not path_or_url:
        raise ValueError("load_image: path_or_url is None or empty")

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



def build_static_frame(cover_img, artist: str, title: str, tick: int = 0) -> Image.Image:
    img_cfg = CONFIG["image"]

    CANVAS_SIZE = img_cfg["canvas_size"]  
    COVER_SIZE = img_cfg["cover_size"]                        
    TOP_MARGIN = img_cfg["top_margin"]                         
    GAP_BETWEEN_COVER_AND_BAND = img_cfg["margin_image_text"]
    GAP_BETWEEN_LINES = img_cfg["line_spacing_margin"]                 
    TARGET_GLYPH_HEIGHT = img_cfg["font_size"]              
    TEXT_COLOR = tuple(img_cfg["text_color"])  
    USE_DYNAMIC_BG = img_cfg.get("use_dynamic_bg", True)
    
    if(USE_DYNAMIC_BG):
        bg_r, bg_g, bg_b = dynamic_bg_color(cover_img)
    else:
        bg_r, bg_g, bg_b = img_cfg["manual_bg_color"]
    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (bg_r, bg_g, bg_b))
    

    w, h = cover_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.BILINEAR)


    x_cover = (CANVAS_SIZE - COVER_SIZE) // 2
    y_cover = TOP_MARGIN
    canvas.paste(cover_resized, (x_cover, y_cover))

    def load_font(size):
        try:
            return ImageFont.truetype(img_cfg["font_path"], size)
        except Exception:
            print(f'using default font, {img_cfg["font_path"]} not found')
            return ImageFont.load_default()

    def measure_text_height(font, text="A"):
        dummy = Image.new("RGB", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[3] - bbox[1]

    best_font = load_font(5)
    best_h = measure_text_height(best_font)
    for size in range(1, 25): 
        f = load_font(size)
        h_test = measure_text_height(f)
        if h_test == TARGET_GLYPH_HEIGHT:
            best_font = f
            best_h = h_test
            break
        if abs(h_test - TARGET_GLYPH_HEIGHT) < abs(best_h - TARGET_GLYPH_HEIGHT):
            best_font = f
            best_h = h_test

    font = best_font
    glyph_h = best_h 

    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    def text_size(text, font):
        dummy = Image.new("RGB", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    w1, _ = text_size(artist, font)
    w2, _ = text_size(title, font)

    draw = ImageDraw.Draw(canvas)

    y_band = TOP_MARGIN + COVER_SIZE + GAP_BETWEEN_COVER_AND_BAND
    y_title = y_band + glyph_h + GAP_BETWEEN_LINES

    def compute_x(w_text: int, tick: int) -> int:
        if w_text <= CANVAS_SIZE:
            return (CANVAS_SIZE - w_text) // 2
        else:
            scroll_range = w_text + CANVAS_SIZE 
            offset = tick % scroll_range
            return CANVAS_SIZE - offset

    x_band = compute_x(w1, tick)
    x_title = compute_x(w2, tick)

    draw.text((x_band,  y_band),  artist, font=font, fill=TEXT_COLOR)
    draw.text((x_title, y_title), title,  font=font, fill=TEXT_COLOR)

    return canvas

import colorsys

def dynamic_bg_color(cover_img: Image.Image, num_colors: int = 8):

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
