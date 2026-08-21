from __future__ import annotations

import os
import time

from dotenv import load_dotenv

from vinylpi.core.display import start_scrolling_display
from vinylpi.core.image_utils import dynamic_bg_color, load_image
from vinylpi.core.spotify_stats import (
    add_spotify_listening_seconds,
    get_spotify_songs_missing_genre,
    record_spotify_play,
    update_spotify_genre,
)
from vinylpi.core.status import write_status
from vinylpi.integrations.home_assistant import send_rgb
from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    SpotifyNotAuthorized,
    SpotifyNotConfigured,
)
from vinylpi.paths import BASE_DIR, get_active_db_path


def _display_track(track) -> None:
    if not track.cover_url:
        write_status(
            track.artist,
            track.title,
            album=track.album,
            genre=track.genre,
            source="spotify",
            spotify_url=track.spotify_url,
            track_id=track.track_id,
            artist_id=track.artist_id,
            duration_ms=track.duration_ms,
        )
        return

    cover = load_image(track.cover_url)
    start_scrolling_display(cover, track.artist, track.title)

    bg_color = None
    try:
        rgb = dynamic_bg_color(cover)
        bg_color = f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
        send_rgb(rgb)
    except Exception as exc:
        print(f"[Spotify/HA] Could not compute/send RGB: {exc}")

    write_status(
        track.artist,
        track.title,
        cover_url=track.cover_url,
        album=track.album,
        genre=track.genre,
        bg_color=bg_color,
        source="spotify",
        spotify_url=track.spotify_url,
        track_id=track.track_id,
        artist_id=track.artist_id,
        duration_ms=track.duration_ms,
    )


def _backfill_missing_genres(client: SpotifyClient, *, limit: int = 30) -> None:
    """Fill older Spotify rows that were recorded while Spotify returned no genre."""
    for row in get_spotify_songs_missing_genre(limit=limit):
        genre = client.get_artist_genre(
            row.get("artist_id"),
            artist=str(row.get("artist") or ""),
            title=str(row.get("title") or ""),
        )
        if genre:
            update_spotify_genre(str(row.get("track_id") or ""), genre)


def main() -> None:
    load_dotenv(BASE_DIR / "vinylpi.env", override=False)
    load_dotenv(BASE_DIR / ".env", override=True)
    poll_seconds = max(1.0, float(os.getenv("SPOTIFY_POLL_SECONDS") or 2.0))

    client: SpotifyClient | None = None
    last_track_id: str | None = None
    last_progress_ms: int | None = None
    last_db_path: str | None = None

    print(f"Spotify worker started (polling every {poll_seconds:g}s).")

    while True:
        try:
            active_db_path = str(get_active_db_path())
            if active_db_path != last_db_path or client is None:
                # Spotify accounts are profile-specific. A profile switch gets a
                # fresh client bound to that profile's refresh token/database.
                last_db_path = active_db_path
                client = SpotifyClient(profile_db_path=active_db_path)
                last_track_id = None
                last_progress_ms = None
                _backfill_missing_genres(client)

            track = client.get_currently_playing()
            if track is None:
                last_track_id = None
                last_progress_ms = None
                time.sleep(poll_seconds)
                continue

            new_play = track.track_id != last_track_id
            restarted = False
            if (
                track.track_id == last_track_id
                and track.is_playing
                and track.progress_ms is not None
                and last_progress_ms is not None
                and track.progress_ms + 5000 < last_progress_ms
            ):
                restarted = True

            if new_play or restarted:
                record_spotify_play(
                    track_id=track.track_id,
                    artist=track.artist,
                    title=track.title,
                    artist_id=track.artist_id,
                    album=track.album,
                    cover_url=track.cover_url,
                    genre=track.genre,
                    duration_ms=track.duration_ms,
                )
                _display_track(track)

            if (
                track.is_playing
                and track.track_id == last_track_id
                and track.progress_ms is not None
                and last_progress_ms is not None
            ):
                delta_ms = track.progress_ms - last_progress_ms
                max_reasonable_ms = int((poll_seconds + 5.0) * 1000)
                if 0 < delta_ms <= max_reasonable_ms:
                    add_spotify_listening_seconds(track.track_id, delta_ms / 1000.0)

            last_track_id = track.track_id
            last_progress_ms = track.progress_ms

        except (SpotifyNotConfigured, SpotifyNotAuthorized) as exc:
            print(f"Spotify worker stopped: {exc}")
            return
        except SpotifyError as exc:
            print(f"Spotify API error: {exc}")
            time.sleep(max(5.0, poll_seconds))
        except Exception as exc:
            print(f"Spotify worker error: {exc}")
            time.sleep(max(5.0, poll_seconds))

        time.sleep(poll_seconds)


if __name__ == "__main__":
    main()
