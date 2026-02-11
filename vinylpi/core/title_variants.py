import re

_LIVE_MARKERS = (
    "live",
    "unplugged",
    "acoustic",
    "session",
    "mtv unplugged",
    "radio",
    "bbc",
    "kexp",
    "music bank",
)


_REMOVED_SUFFIXES = [
    r"\(.*?remaster.*?\)",
    r"\(.*?remastered.*?\)",
    r"\(.*?remix.*?\)",
    r"\(.*?version.*?\)",
    r"\(.*?edit.*?\)",
    r"\(.*?deluxe.*?\)",
    r"\(.*?mono.*?\)",
    r"\(.*?stereo.*?\)",
    r"\(.*?reissue.*?\)",
    r"\(.*?\d{4}.*?\)",
    r"\[.*?remaster.*?\]",
    r"\[.*?remastered.*?\]",
    r"\[.*?remix.*?\]",
    r"\[.*?version.*?\]",
    r"\[.*?edit.*?\]",
    r"\[.*?deluxe.*?\]",
    r"\[.*?mono.*?\]",
    r"\[.*?stereo.*?\]",
    r"\[.*?reissue.*?\]",
    r"\[.*?\d{4}.*?\]",
]

_REMOVED_KEYWORDS = [
    "remaster",
    "remix",
    "remastered",
    "version",
    "edit",
    "deluxe",
    "mono",
    "stereo",
    "reissue",
]

def variant_score(title: str, album: str | None) -> int:
    t = (title or "").lower()
    a = (album or "").lower()

    score = 0

    live_markers = ("live", "unplugged", "session", "acoustic", "mtv unplugged", "radio", "bbc", "kexp")
    is_live = any(m in t for m in live_markers) or any(m in a for m in live_markers)

    remix_markers = ("remix",)
    is_remix = any(m in t for m in remix_markers) or any(m in a for m in remix_markers)

    is_cover = "cover" in t or "cover" in a
    is_instrumental = "instrumental" in t or "instrumental" in a
    is_remaster = "remaster" in t or "remaster" in a

    if is_cover:
        score -= 100
    elif is_remix:
        score -= 60
    elif is_instrumental:
        score -= 40
    elif is_live:
        score -= 60
    elif is_remaster:
        score -= 10

    if album:
        if "greatest hits" in a or "compilation" in a:
            score -= 20

        if not is_live:
            score += 20
        else:
            score += 0

    return score

def is_live_variant(title: str, album: str | None) -> bool:
    t = (title or "").lower()
    a = (album or "").lower()
    return any(m in t for m in _LIVE_MARKERS) or any(m in a for m in _LIVE_MARKERS)


def canonicalize_title(title: str) -> str:
    t = (title or "").lower()

    t = t.replace("–", "-").replace("—", "-")

    for pat in _REMOVED_SUFFIXES:
        t = re.sub(pat, "", t, flags=re.IGNORECASE)

    t = re.split(r"\s+-\s+", t)[0]

    for kw in _REMOVED_KEYWORDS:
        t = re.sub(rf"\b{re.escape(kw)}\b", "", t, flags=re.IGNORECASE)

    t = re.sub(r"\s+", " ", t).strip()
    return t
