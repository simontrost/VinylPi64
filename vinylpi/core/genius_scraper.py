from __future__ import annotations

import copy
import html
import re
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

HEADERS = {"User-Agent": "VinylPi/1.0 (non-commercial hobby project)"}

# Genius transcriptions sometimes use semantic emphasis tags (most notably
# italics) to distinguish lines sung by another performer inside a section.
# Only a tiny, formatting-only subset is allowed through to the browser. This
# keeps the API safe even though the source HTML comes from a third-party page.
_ALLOWED_FORMAT_TAGS = {
    "i": "em",
    "em": "em",
    "b": "strong",
    "strong": "strong",
}


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
    want_title = _tokens(title)

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
            extras = len((have_title | have_artist) - (want_title | want_artist))
            score = overlap * 3 - extras

            if score > best_score:
                best_score = score
                best_url = url

    if best_score < 3:
        return None

    return best_url


def _container_text(container: Tag) -> str:
    """Return the plain-text form used by existing clients/tests."""
    c = copy.copy(container)

    for bad in c.select('[data-exclude-from-selection="true"]'):
        bad.decompose()

    for br in c.find_all("br"):
        br.replace_with("\n")

    text = c.get_text(separator="", strip=False)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    text = "\n".join(line for line in text.splitlines() if line.strip() != "")
    return text.strip()


def _node_to_safe_html(node) -> str:
    """Serialize lyric DOM while preserving only harmless emphasis markup."""
    if isinstance(node, NavigableString):
        return html.escape(str(node), quote=False)

    if not isinstance(node, Tag):
        return ""

    name = (node.name or "").lower()
    if name == "br":
        return "<br>"
    if name in {"script", "style", "noscript"}:
        return ""

    content = "".join(_node_to_safe_html(child) for child in node.children)

    mapped = _ALLOWED_FORMAT_TAGS.get(name)
    if mapped:
        return f"<{mapped}>{content}</{mapped}>"

    # Some pages use a span with an inline italic style rather than <i>/<em>.
    # We intentionally inspect only font-style; no source attributes or CSS are
    # forwarded to the dashboard.
    style = str(node.attrs.get("style") or "").casefold()
    if "font-style" in style and "italic" in style:
        return f"<em>{content}</em>"

    # Links/spans/etc. are unwrapped so their text remains, but their attributes
    # can never reach the browser.
    return content


def _container_safe_html(container: Tag) -> str:
    c = copy.copy(container)

    for bad in c.select('[data-exclude-from-selection="true"]'):
        bad.decompose()

    rendered = "".join(_node_to_safe_html(child) for child in c.children)

    # HTML source indentation is not part of the transcription. Genius uses
    # <br> for visible lyric line breaks, so source newlines can safely be
    # stripped while retaining spaces that actually belong to text nodes.
    rendered = re.sub(r"[\t\r\n]+", " ", rendered)
    rendered = re.sub(r"\s*<br>\s*", "<br>", rendered)
    return rendered.strip()


def _fetch_lyrics_payload(genius_url: str) -> dict | None:
    """Fetch Genius once and return both plain text and safe formatted HTML."""
    r = requests.get(genius_url, headers=HEADERS, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    containers = soup.select('div[data-lyrics-container="true"]')
    if not containers:
        return None

    text_parts: list[str] = []
    html_parts: list[str] = []

    for container in containers:
        text = _container_text(container)
        safe_html = _container_safe_html(container)
        if text:
            text_parts.append(text)
            html_parts.append(safe_html or html.escape(text, quote=False).replace("\n", "<br>"))

    lyrics = "\n\n".join(text_parts).strip()
    if not lyrics:
        return None

    lyrics_html = "<br><br>".join(part for part in html_parts if part).strip()
    return {
        "lyrics": lyrics,
        "lyrics_html": lyrics_html,
    }


def fetch_lyrics(genius_url: str) -> str | None:
    """Backward-compatible plain-text lyrics helper."""
    payload = _fetch_lyrics_payload(genius_url)
    return payload["lyrics"] if payload else None


def get_lyrics(artist: str, title: str) -> dict:
    url = search_genius(artist, title)
    if not url:
        return {"ok": False, "error": "not_found"}

    payload = _fetch_lyrics_payload(url)
    if not payload:
        return {"ok": False, "error": "no_lyrics", "url": url}

    return {
        "ok": True,
        "source": "genius",
        "url": url,
        **payload,
    }
