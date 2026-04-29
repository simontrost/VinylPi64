
import json
import time
from collections import Counter, defaultdict

import requests

from vinylpi.paths import STATS_PATH

MB_RELEASE_GROUP_URL = "https://musicbrainz.org/ws/2/release-group"
USER_AGENT = "VinylPi64/1.0 (https://github.com/simontrost/VinylPi64)"


def load_stats():
    return json.loads(STATS_PATH.read_text(encoding="utf-8"))


def save_stats(stats):
    STATS_PATH.write_text(json.dumps(stats, indent=4), encoding="utf-8")


def best_artist_for_album(songs, album_name):
    counter = Counter()

    for song in songs:
        if song.get("album") == album_name and song.get("artist"):
            counter[song["artist"]] += int(song.get("count", 0) or 0)

    if not counter:
        return None

    return counter.most_common(1)[0][0]


def find_release_group_mbid(artist, album):
    query = f'releasegroup:"{album}" AND artist:"{artist}"'

    params = {
        "query": query,
        "fmt": "json",
        "limit": 5,
    }

    r = requests.get(
        MB_RELEASE_GROUP_URL,
        params=params,
        headers={"User-Agent": USER_AGENT},
        timeout=15,
    )
    r.raise_for_status()

    groups = r.json().get("release-groups") or []
    if not groups:
        return None

    album_cf = album.casefold()
    artist_cf = artist.casefold()

    best = None
    best_score = -999

    for group in groups:
        title = (group.get("title") or "").casefold()
        primary_type = (group.get("primary-type") or "").casefold()
        score = 0

        if title == album_cf:
            score += 50
        elif album_cf in title or title in album_cf:
            score += 25

        if primary_type == "album":
            score += 20

        credits = group.get("artist-credit") or []
        credit_text = " ".join(
            (c.get("artist") or {}).get("name", "")
            for c in credits
            if isinstance(c, dict)
        ).casefold()

        if artist_cf in credit_text:
            score += 30

        if score > best_score:
            best_score = score
            best = group

    if not best:
        return None

    return best.get("id")


def cover_url_for_release_group(mbid):
    url = f"https://coverartarchive.org/release-group/{mbid}/front-500"

    try:
        r = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=15,
            allow_redirects=True,
            stream=True,
        )

        if r.status_code == 200:
            return r.url
    except Exception:
        return None

    return None


def main():
    stats = load_stats()

    songs = list((stats.get("songs") or {}).values())
    albums_map = stats.get("albums") or {}

    albums_sorted = sorted(
        albums_map.items(),
        key=lambda x: x[1],
        reverse=True,
    )[:10]

    album_covers = stats.setdefault("album_covers", {})

    changed = False

    for album_name, count in albums_sorted:
        if album_name in album_covers and album_covers[album_name].get("cover_url"):
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
                print(f"  no MusicBrainz release-group found")
                continue

            cover_url = cover_url_for_release_group(mbid)
            time.sleep(1.1)

            if not cover_url:
                print(f"  no cover found")
                continue

            album_covers[album_name] = {
                "artist": artist,
                "album": album_name,
                "count": count,
                "mbid": mbid,
                "cover_url": cover_url,
            }

            for song in songs:
                if song.get("album") == album_name and not song.get("cover_url"):
                    song["cover_url"] = cover_url

            changed = True
            print(f"  OK: {cover_url}")

        except Exception as e:
            print(f"  ERROR: {e}")

    if changed:
        save_stats(stats)
        print(f"\nSaved: {STATS_PATH}")
    else:
        print("\nNo changes.")


if __name__ == "__main__":
    main()