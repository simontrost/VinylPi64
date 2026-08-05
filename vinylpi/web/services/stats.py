from __future__ import annotations

import io
from typing import Any
import time

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from vinylpi.core.stats_db import get_ranked_stats
from vinylpi.paths import FONTS_DIR
from vinylpi.profiles import get_active_profile

_SHARE_CARD_SIZE = (1080, 1920)
_SHARE_CARD_MARGIN = 74
_SHARE_CARD_PANEL_RADIUS = 34
_SHARE_CARD_MAX_COVERS = 3
_FONT_CACHE: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}



def _empty_stats_payload() -> dict[str, Any]:
    return {
        "top_songs": [],
        "top_artists": [],
        "top_albums": [],
        "top_album_covers": [],
        "top_genres": [],
        "radar_genres": [],
        "total_minutes_listened": 0,
        "metadata_coverage": {
            "songs_total": 0,
            "songs_with_genre": 0,
            "songs_with_shazam_id": 0,
        },
    }



def get_top_stats(limit: int = 10) -> dict:
    try:
        return get_ranked_stats(limit=limit)
    except Exception as exc:
        print(f"Could not load stats from SQLite: {exc}")
        return _empty_stats_payload()



def get_share_card_payload(limit: int = 5) -> dict[str, Any]:
    stats = get_top_stats(limit=max(5, int(limit)))
    active_profile = get_active_profile()
    top_genres = stats.get("top_genres") or []
    top_genre = (top_genres[0] or {}).get("name") if top_genres else None

    return {
        "profile_name": (active_profile or {}).get("name") or "Guest",
        "is_guest": bool((active_profile or {}).get("is_guest")),
        "year": int(time.localtime().tm_year),
        "total_minutes_listened": int(stats.get("total_minutes_listened") or 0),
        "top_genre": top_genre or "Unknown",
        "top_artists": list(stats.get("top_artists") or [])[:5],
        "top_albums": list(stats.get("top_albums") or [])[:5],
        "top_album_covers": list(stats.get("top_album_covers") or [])[:_SHARE_CARD_MAX_COVERS],
    }



def build_share_card_image(payload: dict[str, Any] | None = None) -> bytes:
    data = payload or get_share_card_payload(limit=5)
    image = _create_share_card(data)
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()



def _font(size: int, *, bold: bool = False, pixel: bool = False) -> ImageFont.FreeTypeFont:
    if pixel:
        filename = "Pixel5.ttf"
    elif bold:
        filename = "DejaVuSans-Bold.ttf"
    else:
        filename = "DejaVuSans.ttf"

    cache_key = (filename, size)
    if cache_key in _FONT_CACHE:
        return _FONT_CACHE[cache_key]

    try:
        if pixel:
            font = ImageFont.truetype(str(FONTS_DIR / filename), size)
        else:
            font = ImageFont.truetype(filename, size)
    except Exception:
        fallback_path = FONTS_DIR / ("Pixel5.ttf" if pixel else "vinylpixel.ttf")
        try:
            font = ImageFont.truetype(str(fallback_path), size)
        except Exception:
            font = ImageFont.load_default()

    _FONT_CACHE[cache_key] = font
    return font



def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]



def _fit_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> str:
    value = str(text or "").strip() or "—"
    if _text_size(draw, value, font)[0] <= max_width:
        return value

    ellipsis = "…"
    trimmed = value
    while trimmed:
        trimmed = trimmed[:-1].rstrip()
        candidate = (trimmed + ellipsis).strip()
        if candidate and _text_size(draw, candidate, font)[0] <= max_width:
            return candidate
    return ellipsis



def _draw_gradient_background(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size, (18, 18, 28, 255))
    draw = ImageDraw.Draw(image)

    top = (141, 130, 255)
    middle = (88, 62, 178)
    bottom = (18, 17, 26)
    for y in range(height):
        t = y / max(height - 1, 1)
        if t < 0.58:
            local = t / 0.58
            color = tuple(int(top[i] + (middle[i] - top[i]) * local) for i in range(3))
        else:
            local = (t - 0.58) / 0.42
            color = tuple(int(middle[i] + (bottom[i] - middle[i]) * local) for i in range(3))
        draw.line((0, y, width, y), fill=color + (255,))

    glow = Image.new("RGBA", size, (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow)
    glow_draw.ellipse((-120, -60, 520, 520), fill=(252, 218, 116, 110))
    glow_draw.ellipse((690, 40, 1180, 520), fill=(239, 45, 143, 110))
    glow_draw.ellipse((700, 1180, 1240, 1760), fill=(124, 58, 237, 130))
    glow_draw.ellipse((-160, 1220, 420, 1820), fill=(245, 197, 66, 90))
    glow = glow.filter(ImageFilter.GaussianBlur(120))
    return Image.alpha_composite(image, glow)



def _panel(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], *, fill=(21, 21, 30, 188), outline=(255, 255, 255, 38)) -> None:
    draw.rounded_rectangle(box, radius=_SHARE_CARD_PANEL_RADIUS, fill=fill, outline=outline, width=2)



def _fetch_cover(url: str | None, size: tuple[int, int]) -> Image.Image:
    placeholder = Image.new("RGB", size, (42, 42, 58))
    if not url:
        return placeholder
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as source:
            cover = source.convert("RGB")
            return cover.resize(size, Image.Resampling.LANCZOS)
    except Exception:
        return placeholder



def _draw_cover_stack(base: Image.Image, payload: dict[str, Any], box: tuple[int, int, int, int]) -> None:
    covers = list(payload.get("top_album_covers") or [])[:_SHARE_CARD_MAX_COVERS]
    if not covers:
        return

    left, top, right, bottom = box
    size = min(right - left, bottom - top, 240)
    positions = [
        (left + 20, top + 68, -8),
        (left + 132, top + 8, 7),
        (left + 236, top + 86, 15),
    ]

    for index, item in enumerate(covers):
        cover = _fetch_cover(item.get("cover_url"), (size, size))
        tile = Image.new("RGBA", (size + 28, size + 28), (0, 0, 0, 0))
        tile_draw = ImageDraw.Draw(tile)
        tile_draw.rounded_rectangle((10, 10, size + 18, size + 18), radius=24, fill=(255, 255, 255, 255))
        cover_rgba = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        cover_rgba.paste(cover, (0, 0))
        tile.alpha_composite(cover_rgba, (14, 14))
        rotated = tile.rotate(positions[index][2], resample=Image.Resampling.BICUBIC, expand=True)
        base.alpha_composite(rotated, (positions[index][0], positions[index][1]))



def _draw_list_card(
    draw: ImageDraw.ImageDraw,
    title: str,
    items: list[dict[str, Any]],
    box: tuple[int, int, int, int],
    *,
    count_label: str,
    accent: tuple[int, int, int],
) -> None:
    _panel(draw, box)
    left, top, right, bottom = box
    padding_x = 30
    padding_y = 24

    title_font = _font(30, bold=True)
    item_font = _font(25, bold=True)
    count_font = _font(21, bold=True)
    meta_font = _font(16, pixel=True)

    draw.text((left + padding_x, top + padding_y), title, font=title_font, fill=(255, 255, 255, 245))
    label_w, _ = _text_size(draw, count_label.upper(), meta_font)
    draw.text((right - padding_x - label_w, top + padding_y + 10), count_label.upper(), font=meta_font, fill=accent)

    if not items:
        empty_font = _font(26)
        draw.text((left + padding_x, top + 96), "No listening data yet.", font=empty_font, fill=(220, 220, 230, 210))
        return

    start_y = top + 98
    line_h = 84
    for index, item in enumerate(items[:5], start=1):
        y = start_y + (index - 1) * line_h
        draw.rounded_rectangle((left + 18, y - 10, right - 18, y + 52), radius=24, fill=(11, 11, 16, 205), outline=(255, 255, 255, 36), width=2)
        draw.text((left + padding_x, y), f"{index}", font=item_font, fill=accent)

        name = item.get("name") or item.get("title") or "Unknown"
        name = _fit_text(draw, name, item_font, max_width=max(80, right - left - 200))
        draw.text((left + padding_x + 38, y), name, font=item_font, fill=(255, 255, 255, 245))

        count_raw = int(item.get("count") or 0)
        count_text = f"{count_raw:,}"
        count_w, _ = _text_size(draw, count_text, count_font)
        draw.text((right - padding_x - count_w, y + 4), count_text, font=count_font, fill=(235, 235, 243, 235))



def _create_share_card(payload: dict[str, Any]) -> Image.Image:
    width, height = _SHARE_CARD_SIZE
    image = _draw_gradient_background(_SHARE_CARD_SIZE)
    draw = ImageDraw.Draw(image)

    title_font = _font(28, pixel=True)
    heading_font = _font(78, bold=True)
    profile_font = _font(28, bold=True)
    eyebrow_font = _font(22, pixel=True)
    metric_font = _font(112, bold=True)
    metric_sub_font = _font(28, bold=True)
    paragraph_font = _font(26)
    pill_font = _font(20, bold=True)
    footer_font = _font(17, bold=True)

    left = _SHARE_CARD_MARGIN
    right = width - _SHARE_CARD_MARGIN

    draw.rounded_rectangle((left, 64, left + 286, 116), radius=26, fill=(25, 25, 34, 170), outline=(255, 255, 255, 42), width=2)
    draw.text((left + 18, 80), "VINYL WRAPPED", font=title_font, fill=(255, 255, 255, 245))

    year_label = str(payload.get("year") or "2026")
    year_w, _ = _text_size(draw, year_label, title_font)
    draw.text((right - year_w, 80), year_label, font=title_font, fill=(18, 18, 26, 180))

    draw.text((left, 160), "Your Vinyl Year", font=heading_font, fill=(255, 255, 255, 248))

    profile_name = str(payload.get("profile_name") or "Guest")
    profile_text = f"Profile · {profile_name}"
    profile_w, profile_h = _text_size(draw, profile_text, profile_font)
    draw.rounded_rectangle((left, 264, left + profile_w + 34, 264 + profile_h + 22), radius=24, fill=(17, 17, 24, 150), outline=(255, 255, 255, 38), width=2)
    draw.text((left + 17, 276), profile_text, font=profile_font, fill=(248, 248, 252, 235))
    draw.text((left, 334), "A shareable snapshot of your turntable listening habits.", font=paragraph_font, fill=(245, 245, 252, 210))

    hero_box = (left, 400, right, 860)
    _panel(draw, hero_box, fill=(17, 17, 24, 176), outline=(255, 255, 255, 44))

    draw.text((left + 42, 444), "MINUTES LISTENED", font=eyebrow_font, fill=(245, 197, 66, 255))
    minutes = int(payload.get("total_minutes_listened") or 0)
    minutes_text = f"{minutes:,}"
    draw.text((left + 38, 510), minutes_text, font=metric_font, fill=(255, 255, 255, 250))
    draw.text((left + 42, 650), "minutes listened this year", font=metric_sub_font, fill=(245, 245, 248, 225))

    top_genre = str(payload.get("top_genre") or "Unknown")
    pill_text = f"Top genre · {top_genre}"
    pill_w, pill_h = _text_size(draw, pill_text, pill_font)
    pill_left = left + 42
    pill_top = 714
    draw.rounded_rectangle((pill_left, pill_top, pill_left + pill_w + 34, pill_top + pill_h + 18), radius=22, fill=(15, 15, 22, 200), outline=(255, 255, 255, 32), width=2)
    draw.text((pill_left + 17, pill_top + 9), pill_text, font=pill_font, fill=(255, 226, 122, 255))

    draw.text((left + 42, 790), "Top 5 artists and albums, ready for your story or post.", font=paragraph_font, fill=(240, 240, 246, 220))

    _draw_cover_stack(image, payload, (right - 410, 430, right - 24, 818))

    artists_box = (left, 920, left + (right - left) // 2 - 10, 1548)
    albums_box = (left + (right - left) // 2 + 10, 920, right, 1548)
    _draw_list_card(
        draw,
        "Top 5 Artists",
        list(payload.get("top_artists") or []),
        artists_box,
        count_label="plays",
        accent=(245, 197, 66),
    )
    _draw_list_card(
        draw,
        "Top 5 Albums",
        list(payload.get("top_albums") or []),
        albums_box,
        count_label="sessions",
        accent=(239, 157, 217),
    )

    footer_box = (left, 1600, right, 1816)
    _panel(draw, footer_box, fill=(16, 16, 22, 172), outline=(255, 255, 255, 34))
    draw.text((left + 34, 1642), "VINYLPI64", font=title_font, fill=(255, 255, 255, 240))
    footer_text = "Built from your local listening statistics. Share it wherever you like."
    draw.text((left + 34, 1710), footer_text, font=paragraph_font, fill=(240, 240, 246, 212))
    footer_tag = "wrapped-style recap"
    tag_w, _ = _text_size(draw, footer_tag, footer_font)
    draw.text((right - 34 - tag_w, 1760), footer_tag, font=footer_font, fill=(255, 255, 255, 180))

    return image.convert("RGB")
