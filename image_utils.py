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


from PIL import Image, ImageDraw, ImageFont

from PIL import Image, ImageDraw, ImageFont

def build_static_frame(cover_img, artist: str, title: str, tick: int = 0) -> Image.Image:
    img_cfg = CONFIG["image"]

    CANVAS_SIZE = img_cfg["canvas_size"]   # z.B. 64
    COVER_SIZE = 46                        # fest: 46x46
    TOP_MARGIN = 1                         # 1 Pixel oben frei
    GAP_BETWEEN_COVER_AND_BAND = 3         # 3 Pixel
    GAP_BETWEEN_LINES = 3                  # 3 Pixel
    TARGET_GLYPH_HEIGHT = 5                # wir wollen 5 Pixel hohe Schrift

    bg_r, bg_g, bg_b = img_cfg["background_color"]
    canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), (bg_r, bg_g, bg_b))

    # Cover quadratisch zuschneiden und auf 46x46 skalieren
    w, h = cover_img.size
    side = min(w, h)
    left = (w - side) // 2
    top = (h - side) // 2
    cover_square = cover_img.crop((left, top, left + side, top + side))
    cover_resized = cover_square.resize((COVER_SIZE, COVER_SIZE), Image.Resampling.BILINEAR)

    # Textfarbe: einfacher Kontrast zum Hintergrund (Schwarz oder Weiß)
    bg_lum = relative_luminance((bg_r, bg_g, bg_b))
    text_color = (0, 0, 0) if bg_lum > 127 else (255, 255, 255)

    # Cover platzieren: 1 Pixel oben frei, horizontal zentriert
    x_cover = (CANVAS_SIZE - COVER_SIZE) // 2
    y_cover = TOP_MARGIN
    canvas.paste(cover_resized, (x_cover, y_cover))

    # Font laden
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

    # Fontgröße suchen, bei der glyph height ≈ 5 Pixel ist
    best_font = load_font(5)
    best_h = measure_text_height(best_font)
    for size in range(1, 25):  # 1..24 ausprobieren
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
    glyph_h = best_h  # idealerweise 5

    # Optional alles in Großbuchstaben
    if img_cfg.get("uppercase", False):
        artist = artist.upper()
        title = title.upper()

    def text_size(text, font):
        dummy = Image.new("RGB", (1, 1))
        d = ImageDraw.Draw(dummy)
        bbox = d.textbbox((0, 0), text, font=font)
        return bbox[2] - bbox[0], bbox[3] - bbox[1]

    # Breiten berechnen (kein Abschneiden/„…“ mehr!)
    w1, _ = text_size(artist, font)
    w2, _ = text_size(title, font)

    draw = ImageDraw.Draw(canvas)

    # Vertikale Positionen nach deinem festen Schema:
    y_band = TOP_MARGIN + COVER_SIZE + GAP_BETWEEN_COVER_AND_BAND
    y_title = y_band + glyph_h + GAP_BETWEEN_LINES

    # ---------- Marquee-Logik ----------
    def compute_x(w_text: int, tick: int) -> int:
        """Gibt die X-Position für statisch oder scrollend zurück."""
        if w_text <= CANVAS_SIZE:
            # passt → einfach zentrieren
            return (CANVAS_SIZE - w_text) // 2
        else:
            # zu lang → klassischer Marquee (von rechts rein, nach links raus)
            scroll_range = w_text + CANVAS_SIZE  # Strecke, bis kompletter Loop
            offset = tick % scroll_range
            # Text startet ganz rechts außerhalb und wandert nach links
            return CANVAS_SIZE - offset

    x_band = compute_x(w1, tick)
    x_title = compute_x(w2, tick)

    # Zeichnen – Pillow croppt automatisch an der Canvas-Grenze
    draw.text((x_band,  y_band),  artist, font=font, fill=text_color)
    draw.text((x_title, y_title), title,  font=font, fill=text_color)

    return canvas
