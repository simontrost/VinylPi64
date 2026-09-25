from __future__ import annotations

from copy import deepcopy
from typing import Any

CANVAS_SIZE = 64
MIN_COVER_SIZE = 12
MAX_COVER_SIZE = 64
MIN_TEXT_HEIGHT = 3
MAX_TEXT_HEIGHT = 12
MAX_TOP_MARGIN = 16
MAX_SPACING = 8

_LAYOUT_BOOL_DEFAULTS = {
    "show_cover": True,
    "show_artist": True,
    "show_title": True,
    "show_album": False,
}


def _as_int(value: Any, default: int) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return int(default)


def _clamp(value: Any, minimum: int, maximum: int, default: int) -> int:
    return max(minimum, min(maximum, _as_int(value, default)))


def visible_text_fields(image_cfg: dict) -> list[str]:
    return [
        field
        for field in ("artist", "title", "album")
        if bool(image_cfg.get(f"show_{field}", _LAYOUT_BOOL_DEFAULTS[f"show_{field}"]))
    ]


def layout_metrics(image_cfg: dict) -> dict[str, int | bool | list[str]]:
    """Return vertical layout usage for the fixed 64x64 Pixoo canvas.

    Horizontal text overflow is intentionally allowed because the display
    marquee handles it. The constraint that matters for the designer is the
    vertical footprint of the enabled elements.
    """
    canvas_size = CANVAS_SIZE
    show_cover = bool(image_cfg.get("show_cover", True))
    text_fields = visible_text_fields(image_cfg)
    text_count = len(text_fields)

    top_margin = _clamp(image_cfg.get("top_margin"), 0, MAX_TOP_MARGIN, 1)
    cover_size = _clamp(image_cfg.get("cover_size"), MIN_COVER_SIZE, MAX_COVER_SIZE, 46)
    font_size = _clamp(image_cfg.get("font_size"), MIN_TEXT_HEIGHT, MAX_TEXT_HEIGHT, 5)
    cover_gap = _clamp(image_cfg.get("margin_image_text"), 0, MAX_SPACING, 3)
    line_gap = _clamp(image_cfg.get("line_spacing_margin"), 0, MAX_SPACING, 3)

    used_height = top_margin
    if show_cover:
        used_height += cover_size
    if show_cover and text_count:
        used_height += cover_gap
    if text_count:
        used_height += text_count * font_size
        used_height += max(0, text_count - 1) * line_gap

    return {
        "canvas_size": canvas_size,
        "used_height": used_height,
        "free_height": canvas_size - used_height,
        "fits": used_height <= canvas_size,
        "show_cover": show_cover,
        "text_count": text_count,
        "text_fields": text_fields,
    }


def normalize_image_config(image_cfg: dict | None) -> dict:
    """Clamp display-layout settings to a valid 64x64 composition.

    Existing installations keep their classic layout because all new visibility
    flags default to cover + artist + title. When a combination would overflow
    vertically, the cover is reduced first, followed by decorative spacing and
    finally text height. This makes increasing text size naturally trade cover
    area for typography instead of producing clipped frames.
    """
    cfg = deepcopy(image_cfg or {})
    cfg["canvas_size"] = CANVAS_SIZE

    for key, default in _LAYOUT_BOOL_DEFAULTS.items():
        cfg[key] = bool(cfg.get(key, default))

    # Never persist a completely empty display. Title is the least surprising
    # recovery because it still communicates what is playing.
    if not any(cfg[key] for key in _LAYOUT_BOOL_DEFAULTS):
        cfg["show_title"] = True

    cfg["top_margin"] = _clamp(cfg.get("top_margin"), 0, MAX_TOP_MARGIN, 1)
    cfg["cover_size"] = _clamp(cfg.get("cover_size"), MIN_COVER_SIZE, MAX_COVER_SIZE, 46)
    cfg["font_size"] = _clamp(cfg.get("font_size"), MIN_TEXT_HEIGHT, MAX_TEXT_HEIGHT, 5)
    cfg["margin_image_text"] = _clamp(cfg.get("margin_image_text"), 0, MAX_SPACING, 3)
    cfg["line_spacing_margin"] = _clamp(cfg.get("line_spacing_margin"), 0, MAX_SPACING, 3)

    def overflow() -> int:
        return max(0, int(layout_metrics(cfg)["used_height"]) - CANVAS_SIZE)

    # Prefer shrinking the cover when typography needs more room.
    extra = overflow()
    if extra and cfg["show_cover"]:
        reducible = max(0, cfg["cover_size"] - MIN_COVER_SIZE)
        change = min(extra, reducible)
        cfg["cover_size"] -= change

    # Decorative whitespace is the next cheapest thing to sacrifice.
    for key in ("top_margin", "margin_image_text", "line_spacing_margin"):
        extra = overflow()
        if not extra:
            break
        reducible = int(cfg[key])
        change = min(extra, reducible)
        cfg[key] -= change

    # Text only shrinks if the requested combination still cannot fit.
    extra = overflow()
    if extra:
        text_count = int(layout_metrics(cfg)["text_count"])
        while extra > 0 and cfg["font_size"] > MIN_TEXT_HEIGHT and text_count > 0:
            cfg["font_size"] -= 1
            extra = overflow()

    # Defensive final guard. It is only reachable with very unusual future
    # combinations, but guarantees the renderer can never exceed 64 rows.
    extra = overflow()
    if extra and cfg["show_cover"]:
        cfg["cover_size"] = max(1, cfg["cover_size"] - extra)

    return cfg
