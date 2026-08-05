from __future__ import annotations

import io
from typing import Any

import requests
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from vinylpi.core.stats_db import get_ranked_stats
from vinylpi.paths import FONTS_DIR
from vinylpi.profiles import get_active_profile

_SHARE_CARD_SIZE = (1080, 1920)
_SHARE_CARD_MARGIN = 74
_SHARE_CARD_PANEL_RADIUS = 34
_SHARE_CARD_MAX_COVERS = 3
_FONT_CACHE: dict[tuple[str, int, bool, bool], ImageFont.FreeTypeFont] = {}


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

    cache_key = (filename, size, bold, pixel)
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


def _wrap_text_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    *,
    max_lines: int = 2,
) -> list[str]:
    value = str(text or "").strip() or "—"
    words = value.split()
    if not words:
        return ["—"]

    lines: list[str] = []
    current = words[0]
    for word in words[1:]:
        candidate = f"{current} {word}"
        if _text_size(draw, candidate, font)[0] <= max_width:
            current = candidate
            continue

        lines.append(current)
        current = word
        if len(lines) == max_lines - 1:
            break

    remaining_words = words[len(" ".join(lines + [current]).split()):]
    remainder = " ".join([current] + remaining_words).strip()
    if remainder:
        lines.append(_fit_text(draw, remainder, font, max_width))

    if len(lines) > max_lines:
        lines = lines[:max_lines]

    if len(lines) == 1 and _text_size(draw, lines[0], font)[0] > max_width:
        lines[0] = _fit_text(draw, lines[0], font, max_width)

    return lines[:max_lines]


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


def _panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    *,
    fill: tuple[int, int, int, int] = (21, 21, 30, 188),
    outline: tuple[int, int, int, int] = (255, 255, 255, 38),
) -> None:
    draw.rounded_rectangle(box, radius=_SHARE_CARD_PANEL_RADIUS, fill=fill, outline=outline, width=2)


def _fetch_cover(url: str | None, size: tuple[int, int]) -> Image.Image | None:
    if not url:
        return None
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image = ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            image.load()
        return image
    except Exception:
        return None


def _make_cover_tile(cover: Image.Image, *, radius: int = 28, border: int = 10) -> Image.Image:
    size = cover.size[0]
    canvas = Image.new("RGBA", (size + border * 2, size + border * 2), (0, 0, 0, 0))
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (border - 2, border + 10, border + size + 2, border + size + 14),
        radius=radius + 4,
        fill=(0, 0, 0, 92),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(18))
    canvas.alpha_composite(shadow)

    frame = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    frame_draw = ImageDraw.Draw(frame)
    frame_draw.rounded_rectangle(
        (border - 1, border - 1, border + size + 1, border + size + 1),
        radius=radius + 2,
        fill=(248, 248, 252, 255),
    )

    mask = Image.new("L", (size, size), 0)
    mask_draw = ImageDraw.Draw(mask)
    mask_draw.rounded_rectangle((0, 0, size, size), radius=radius, fill=255)

    cover_rgba = cover.convert("RGBA")
    clipped = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    clipped.paste(cover_rgba, (0, 0), mask)

    frame.alpha_composite(clipped, (border, border))
    canvas.alpha_composite(frame)
    return canvas


def _draw_cover_stack(base: Image.Image, payload: dict[str, Any], box: tuple[int, int, int, int]) -> None:
    source_items = list(payload.get("top_album_covers") or [])[:_SHARE_CARD_MAX_COVERS]
    if not source_items:
        return

    left, top, right, bottom = box
    available_w = right - left
    available_h = bottom - top
    cover_size = min(available_w // 2, available_h - 20, 228)

    covers = []
    for item in source_items:
        cover = _fetch_cover(item.get("cover_url"), (cover_size, cover_size))
        if cover is not None:
            covers.append(_make_cover_tile(cover))

    if not covers:
        return

    placements = [
        (left + 12, top + 118, -11),
        (left + 128, top + 36, 6),
        (left + 252, top + 114, 13),
    ]
    placements = placements[: len(covers)]

    for tile, placement in zip(covers, placements, strict=False):
        x, y, angle = placement
        rotated = tile.rotate(angle, resample=Image.Resampling.BICUBIC, expand=True)
        base.alpha_composite(rotated, (x, y))


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
    item_font = _font(23, bold=True)
    count_font = _font(21, bold=True)
    meta_font = _font(16, pixel=True)

    draw.text((left + padding_x, top + padding_y), title, font=title_font, fill=(255, 255, 255, 245))
    label_text = count_label.upper()
    label_w, _ = _text_size(draw, label_text, meta_font)
    draw.text((right - padding_x - label_w, top + padding_y + 10), label_text, font=meta_font, fill=accent)

    if not items:
        empty_font = _font(26)
        draw.text((left + padding_x, top + 96), "No listening data yet.", font=empty_font, fill=(220, 220, 230, 210))
        return

    start_y = top + 100
    row_h = 76
    line_h = 96
    line_gap = 4
    content_left = left + padding_x + 38
    content_right = right - padding_x - 74
    max_name_width = max(96, content_right - content_left)

    for index, item in enumerate(items[:5], start=1):
        y = start_y + (index - 1) * line_h
        draw.rounded_rectangle(
            (left + 18, y - 10, right - 18, y + row_h),
            radius=24,
            fill=(11, 11, 16, 205),
            outline=(255, 255, 255, 36),
            width=2,
        )
        draw.text((left + padding_x, y + 12), f"{index}", font=item_font, fill=accent)

        name = item.get("name") or item.get("title") or "Unknown"
        lines = _wrap_text_lines(draw, name, item_font, max_width=max_name_width, max_lines=2)
        text_y = y + (8 if len(lines) > 1 else 18)
        for line_index, line in enumerate(lines):
            draw.text(
                (content_left, text_y + line_index * (item_font.size + line_gap)),
                line,
                font=item_font,
                fill=(255, 255, 255, 245),
            )

        count_raw = int(item.get("count") or 0)
        count_text = f"{count_raw:,}"
        count_w, count_h = _text_size(draw, count_text, count_font)
        count_y = y + (row_h - count_h) / 2 - 4
        draw.text((right - padding_x - count_w, count_y), count_text, font=count_font, fill=(235, 235, 243, 235))


def _create_share_card(payload: dict[str, Any]) -> Image.Image:
    width, height = _SHARE_CARD_SIZE
    image = _draw_gradient_background(_SHARE_CARD_SIZE)
    draw = ImageDraw.Draw(image)

    badge_font = _font(26, pixel=True)
    heading_font = _font(72, bold=True)
    profile_font = _font(28, bold=True)
    eyebrow_font = _font(22, pixel=True)
    metric_font = _font(118, bold=True)
    metric_sub_font = _font(30, bold=True)
    genre_label_font = _font(22, pixel=True)
    genre_value_font = _font(52, bold=True)

    left = _SHARE_CARD_MARGIN
    right = width - _SHARE_CARD_MARGIN

    badge_text = "VINYL WRAPPED"
    badge_w, badge_h = _text_size(draw, badge_text, badge_font)
    badge_box = (left, 64, left + badge_w + 54, 64 + badge_h + 34)
    draw.rounded_rectangle(badge_box, radius=26, fill=(25, 25, 34, 170), outline=(255, 255, 255, 42), width=2)
    draw.text((left + 24, 86), badge_text, font=badge_font, fill=(255, 255, 255, 245))

    draw.text((left, 160), "Your Vinyl Statistics", font=heading_font, fill=(255, 255, 255, 248))

    profile_name = str(payload.get("profile_name") or "Guest")
    profile_text = _fit_text(draw, profile_name, profile_font, max_width=420)
    profile_w, profile_h = _text_size(draw, profile_text, profile_font)
    profile_box = (left, 272, left + profile_w + 52, 272 + profile_h + 30)
    draw.rounded_rectangle(profile_box, radius=24, fill=(17, 17, 24, 150), outline=(255, 255, 255, 38), width=2)
    profile_x = profile_box[0] + ((profile_box[2] - profile_box[0]) - profile_w) / 2
    profile_y = profile_box[1] + ((profile_box[3] - profile_box[1]) - profile_h) / 2 - 2
    draw.text((profile_x, profile_y), profile_text, font=profile_font, fill=(248, 248, 252, 235))

    hero_box = (left, 380, right, 860)
    _panel(draw, hero_box, fill=(17, 17, 24, 176), outline=(255, 255, 255, 44))

    draw.text((left + 42, 430), "MINUTES LISTENED", font=eyebrow_font, fill=(245, 197, 66, 255))
    minutes = int(payload.get("total_minutes_listened") or 0)
    minutes_text = f"{minutes:,}"
    draw.text((left + 38, 500), minutes_text, font=metric_font, fill=(255, 255, 255, 250))
    draw.text((left + 42, 650), "minutes listened", font=metric_sub_font, fill=(245, 245, 248, 225))

    _draw_cover_stack(image, payload, (right - 396, 422, right - 26, 816))

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

    genre_label = "TOP GENRE"
    genre_value = _fit_text(draw, str(payload.get("top_genre") or "Unknown"), genre_value_font, max_width=760)
    genre_label_w, genre_label_h = _text_size(draw, genre_label, genre_label_font)
    genre_value_w, genre_value_h = _text_size(draw, genre_value, genre_value_font)
    center_x = (left + right) // 2
    draw.text((center_x - genre_label_w // 2, 1650), genre_label, font=genre_label_font, fill=(245, 197, 66, 255))
    draw.text((center_x - genre_value_w // 2, 1706), genre_value, font=genre_value_font, fill=(255, 255, 255, 245))

    return image.convert("RGB")
