import re

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

    is_live = "live" in t or "unplugged" in t
    is_remix = "remix" in t
    is_cover = "cover" in t
    is_instrumental = "instrumental" in t
    is_remaster = "remaster" in t

    if is_cover:
        score -= 100
    elif is_remix:
        score -= 60
    elif is_instrumental:
        score -= 40
    elif is_remaster:
        score -= 10
    elif is_live:
        score -= 20

    if album:
        if "greatest hits" in a or "compilation" in a:
            score -= 20
        elif not is_live:
            score += 20
        else:
            score += 10

    return score


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
