import requests
from bs4 import BeautifulSoup
from urllib.parse import quote_plus

HEADERS = {
    "User-Agent": "VinylPi/1.0 (non-commercial hobby project)"
}

def search_genius(artist: str, title: str) -> str | None:
    query = quote_plus(f"{artist} {title}")
    url = f"https://genius.com/search?q={query}"

    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a[href]"):
        href = a["href"]
        if href.startswith("https://genius.com/") and href.endswith("-lyrics"):
            return href

    return None


def fetch_lyrics(genius_url: str) -> str | None:
    r = requests.get(genius_url, headers=HEADERS, timeout=10)
    r.raise_for_status()

    soup = BeautifulSoup(r.text, "html.parser")

    parts = soup.select('div[data-lyrics-container="true"]')
    if not parts:
        return None

    lines = []
    for div in parts:
        for br in div.find_all("br"):
            br.replace_with("\n")
        text = div.get_text(strip=False)
        lines.append(text.strip())

    lyrics = "\n\n".join(lines)
    return lyrics.strip() if lyrics else None


def get_lyrics(artist: str, title: str) -> dict:
    url = search_genius(artist, title)
    if not url:
        return {"ok": False, "error": "not_found"}

    lyrics = fetch_lyrics(url)
    if not lyrics:
        return {"ok": False, "error": "no_lyrics"}

    return {
        "ok": True,
        "source": "genius",
        "url": url,
        "lyrics": lyrics
    }
