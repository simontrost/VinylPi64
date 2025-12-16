import copy
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

HEADERS = {"User-Agent": "VinylPi/1.0 (non-commercial hobby project)"}


def _tokens(s: str) -> set[str]:
    s = (s or "").lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return {t for t in s.split() if t and t not in {"feat", "ft", "official", "video", "lyrics"}}


def search_genius(artist: str, title: str) -> str | None:
    query = quote_plus(f"{artist} {title}")
    url = f"https://genius.com/search?q={query}"

    r = requests.get(url, headers=HEADERS, timeout=10, allow_redirects=True)
    r.raise_for_status()

    if "/search" not in r.url or "q=" not in r.url:
        return None

    soup = BeautifulSoup(r.text, "html.parser")

    candidates = [a.get("href") for a in soup.select('a[href^="https://genius.com/"][href$="-lyrics"]')]
    candidates = [c for c in candidates if c]  # None raus

    if not candidates:
        return None

    want = _tokens(artist) | _tokens(title)

    best_url = None
    best_score = -1
    for href in candidates:
        slug = href.rsplit("/", 1)[-1].replace("-", " ")
        have = _tokens(slug)
        score = len(want & have)

        if score > best_score:
            best_score = score
            best_url = href

    if best_score <= 0:
        return None

    return best_url


def fetch_lyrics(genius_url: str) -> str | None:
    r = requests.get(genius_url, headers=HEADERS, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    containers = soup.select('div[data-lyrics-container="true"]')
    if not containers:
        return None

    out_parts: list[str] = []

    for c in containers:
        c = copy.copy(c)

        for bad in c.select('[data-exclude-from-selection="true"]'):
            bad.decompose()

        for br in c.find_all("br"):
            br.replace_with("\n")

        txt = c.get_text(separator="", strip=False)

        txt = "\n".join(line.rstrip() for line in txt.splitlines())
        txt = "\n".join(line for line in txt.splitlines() if line.strip() != "")

        if txt.strip():
            out_parts.append(txt.strip())

    lyrics = "\n\n".join(out_parts).strip()
    return lyrics if lyrics else None


def get_lyrics(artist: str, title: str) -> dict:
    url = search_genius(artist, title)
    if not url:
        return {"ok": False, "error": "not_found"}

    lyrics = fetch_lyrics(url)
    if not lyrics:
        return {"ok": False, "error": "no_lyrics", "url": url}

    return {"ok": True, "source": "genius", "url": url, "lyrics": lyrics}
