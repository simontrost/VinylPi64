import time
from collections import Counter

import requests

from vinylpi.core.stats_db import get_stats_snapshot, upsert_album_cover

MB_RELEASE_GROUP_URL = "https://musicbrainz.org/ws/2/release-group"
USER_AGENT = "VinylPi64/1.0 (https://github.com/simontrost/VinylPi64)"


def best_artist_for_album(songs, album_name):
    counter = Counter()
    for song in songs:
        if song.get("album") == album_name and song.get("artist"):
            counter[song["artist"]] += int(song.get("count", 0) or 0)
    return counter.most_common(1)[0][0] if counter else None


def find_release_group_mbid(artist, album):
    response = requests.get(
        MB_RELEASE_GROUP_URL,
        params={
            "query": f'releasegroup:"{album}" AND artist:"{artist}"',
            "fmt": "json",
            "limit": 5,
        },
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    response.raise_for_status()
    groups = response.json().get("release-groups") or []

    album_cf = album.casefold()
    artist_cf = artist.casefold()
    best = None
    best_score = -999

    for group in groups:
        title = (group.get("title") or "").casefold()
        primary_type = (group.get("primary-type") or "").casefold()
        score = 50 if title == album_cf else 25 if album_cf in title or title in album_cf else 0
        if primary_type == "album":
            score += 20
        credits = group.get("artist-credit") or []
        credit_text = " ".join(
            (credit.get("artist") or {}).get("name", "")
            for credit in credits
            if isinstance(credit, dict)
        ).casefold()
        if artist_cf in credit_text:
            score += 30
        if score > best_score:
            best_score = score
            best = group

    return best.get("id") if best else None


def cover_url_for_release_group(mbid):
    try:
        response = requests.get(
            f"https://coverartarchive.org/release-group/{mbid}/front-500",
            headers={"User-Agent": USER_AGENT},
            timeout=15,
            allow_redirects=True,
            stream=True,
        )
        return response.url if response.status_code == 200 else None
    except Exception:
        return None


def main():
    stats = get_stats_snapshot()
    songs = list((stats.get("songs") or {}).values())
    albums_sorted = sorted(
        (stats.get("albums") or {}).items(), key=lambda item: item[1], reverse=True
    )[:10]
    existing = stats.get("album_covers") or {}
    changed = False

    for album_name, count in albums_sorted:
        if (existing.get(album_name) or {}).get("cover_url"):
            print(f"SKIP: {album_name}")
            continue

        artist = best_artist_for_album(songs, album_name)
        if not artist:
            print(f"NO ARTIST: {album_name}")
            continue

        print(f"Searching cover: {artist} - {album_name}")
        try:
            mbid = find_release_group_mbid(artist, album_name)
            time.sleep(1.1)
            if not mbid:
                print("  no MusicBrainz release-group found")
                continue
            cover_url = cover_url_for_release_group(mbid)
            time.sleep(1.1)
            if not cover_url:
                print("  no cover found")
                continue
            upsert_album_cover(album_name, artist, count, mbid, cover_url)
            changed = True
            print(f"  OK: {cover_url}")
        except Exception as exc:
            print(f"  ERROR: {exc}")

    print("\nSaved to SQLite." if changed else "\nNo changes.")


if __name__ == "__main__":
    main()
