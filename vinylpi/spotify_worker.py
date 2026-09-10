from __future__ import annotations

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
from vinylpi.core.status import get_last_source_status, write_status
from vinylpi.integrations.home_assistant import send_rgb
from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    SpotifyNotAuthorized,
    SpotifyNotConfigured,
)
from vinylpi.paths import BASE_DIR, get_active_db_path
from vinylpi.config.runtime import read_config


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


def _poll_seconds() -> float:
    """Return the live Spotify polling interval from the active profile config."""
    try:
        value = (read_config().get("spotify") or {}).get("poll_seconds", 2.0)
        return max(1.0, float(value))
    except (TypeError, ValueError):
        return 2.0


def _last_recognized_spotify_track_id() -> str | None:
    """Restore the last Spotify track across pause/off/worker restarts."""
    status = get_last_source_status("spotify") or {}
    track_id = str(status.get("track_id") or "").strip()
    return track_id or None


def main() -> None:
    load_dotenv(BASE_DIR / "vinylpi.env", override=False)
    load_dotenv(BASE_DIR / ".env", override=True)

    client: SpotifyClient | None = None
    last_track_id: str | None = None
    last_progress_ms: int | None = None
    last_db_path: str | None = None
    displayed_in_session = False

    print(f"Spotify worker started (polling every {_poll_seconds():g}s).")

    while True:
        poll_seconds = _poll_seconds()
        try:
            active_db_path = str(get_active_db_path())
            if active_db_path != last_db_path or client is None:
                # Spotify accounts and last-source status are profile-specific.
                # Restore the previous track so Off -> Spotify cannot count the
                # exact same song again merely because the worker restarted.
                last_db_path = active_db_path
                client = SpotifyClient(profile_db_path=active_db_path)
                last_track_id = _last_recognized_spotify_track_id()
                last_progress_ms = None
                displayed_in_session = False
                _backfill_missing_genres(client)

            track = client.get_currently_playing()
            if track is None:
                # Losing the playback response (including a pause on clients that
                # return no item) must not forget which song was last recognized.
                # Only the progress baseline is discarded to avoid adding paused
                # time when playback becomes available again.
                last_progress_ms = None
                time.sleep(poll_seconds)
                continue

            new_play = track.track_id != last_track_id

            if new_play:
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

            # A worker restart leaves the Pixoo on the fallback image. Even when
            # the current track equals the persisted last track (and therefore
            # must NOT be counted again), it still needs to be displayed once.
            if new_play or not displayed_in_session:
                _display_track(track)
                displayed_in_session = True

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
