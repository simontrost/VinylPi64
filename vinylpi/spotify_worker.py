from __future__ import annotations

import os
import time

from dotenv import load_dotenv

from vinylpi.core.display import start_scrolling_display
from vinylpi.core.image_utils import dynamic_bg_color, load_image
from vinylpi.core.spotify_stats import add_spotify_listening_seconds, record_spotify_play
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

    # The normal VinylPi status schema is reused deliberately. Discogs fields
    # stay empty, while the track/artist IDs contain Spotify IDs in this mode.
    write_status(
        track.artist,
        track.title,
        cover_url=track.cover_url,
        album=track.album,
        genre=track.genre,
        bg_color=bg_color,
        track_id=track.track_id,
        artist_id=track.artist_id,
        duration_ms=track.duration_ms,
    )


def main() -> None:
    load_dotenv(BASE_DIR / "vinylpi.env", override=False)
    load_dotenv(BASE_DIR / ".env", override=True)
    poll_seconds = max(1.0, float(os.getenv("SPOTIFY_POLL_SECONDS") or 2.0))

    client = SpotifyClient()
    last_track_id: str | None = None
    last_progress_ms: int | None = None
    last_db_path: str | None = None

    print(f"Spotify worker started (polling every {poll_seconds:g}s).")

    while True:
        try:
            active_db_path = str(get_active_db_path())
            if active_db_path != last_db_path:
                # A profile switch should start a fresh listening context so the
                # new profile receives its own play count for the current song.
                last_db_path = active_db_path
                last_track_id = None
                last_progress_ms = None

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
