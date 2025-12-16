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
    q = f"{artist} {title}"
    api = f"https://genius.com/api/search/multi?q={quote_plus(q)}"

    r = requests.get(api, headers=HEADERS, timeout=10)
    r.raise_for_status()
    data = r.json()

    want_artist = _tokens(artist)
    want_title  = _tokens(title)

    best_url = None
    best_score = -10_000

    for sec in data.get("response", {}).get("sections", []):
        if sec.get("type") not in {"song", "top_hit"}:
            continue

        for hit in sec.get("hits", []):
            res = hit.get("result") or {}
            url = res.get("url")
            if not url or not url.startswith("https://genius.com/") or not url.endswith("-lyrics"):
                continue

            have_title = _tokens(res.get("title", ""))
            have_artist = _tokens((res.get("primary_artist") or {}).get("name", ""))

            overlap = len(want_title & have_title) + len(want_artist & have_artist)
            extras  = len((have_title | have_artist) - (want_title | want_artist))
            score = overlap * 3 - extras 

            if score > best_score:
                best_score = score
                best_url = url

    if best_score < 3:
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
