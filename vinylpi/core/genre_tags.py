from __future__ import annotations

import re


_GENRE_ALIASES = {
    "hip hop/rap": "Hip-Hop/Rap",
    "hip-hop/rap": "Hip-Hop/Rap",
    "hip hop": "Hip-Hop/Rap",
    "r&b/soul": "R&B/Soul",
    "rb/soul": "R&B/Soul",
    "alternative": "Alternative",
    "alternative rock": "Alternative",
    "electronica": "Electronic",
    "electronic": "Electronic",
    "dance": "Dance",
    "dance/electronic": "Dance",
    "singer/songwriter": "Singer/Songwriter",
    "soundtrack": "Soundtrack",
}


def normalize_genre(value: object) -> str | None:
    """Normalize Shazam's primary genre into a stable display value."""
    if isinstance(value, (list, tuple)):
        value = next((item for item in value if str(item).strip()), None)

    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return None

    alias = _GENRE_ALIASES.get(text.casefold())
    if alias:
        return alias

    return text[:80]
