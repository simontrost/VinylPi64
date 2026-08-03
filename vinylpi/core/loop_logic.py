from __future__ import annotations

import time
from typing import Any

from vinylpi.core.display import show_fallback_image, show_side_flip_prompt, start_scrolling_display
from vinylpi.core.image_utils import dynamic_bg_color
from vinylpi.core.loop_state import AlbumState, DisplayState, LoopConfig, StatsSwitchState
from vinylpi.core.models import RecognizedTrack
from vinylpi.core.statistics import (
    _increment_album_session,
    _update_stats,
    add_listen_time_minutes_for_confirmed_song,
    add_measured_listen_time_seconds,
)
from vinylpi.core.status import clear_side_flip_prompt, write_side_flip_prompt, write_status
from vinylpi.core.title_variants import canonicalize_title, variant_score
from vinylpi.integrations.home_assistant import send_rgb


def log_pixoo_update_reason(
    *,
    debug_log: bool,
    last_display_was_fallback: bool,
    cfg_reloaded: bool,
    is_same_song: bool,
) -> None:
    if not debug_log:
        return

    if last_display_was_fallback and is_same_song:
        print("Same song as before after fallback, updating Pixoo.")
    elif last_display_was_fallback:
        print("New song detected after fallback, updating Pixoo.")
    elif cfg_reloaded and is_same_song:
        print("Config changed, updating Pixoo for the same song.")
    elif cfg_reloaded:
        print("Config changed and a new song was detected, updating Pixoo.")
    else:
        print("New song detected, updating Pixoo.")


def handle_no_result(
    cfg: LoopConfig,
    disp: DisplayState,
    cfg_reloaded: bool,
    *,
    side_flip_prompt: dict[str, Any] | None = None,
) -> bool:
    disp.consecutive_failures += 1
    if cfg.debug_log:
        print(f"No song detected (#{disp.consecutive_failures} in a row).")

    fallback_due = (
        disp.consecutive_failures >= cfg.fallback_allowed_failures
        and (not disp.last_display_was_fallback or cfg_reloaded)
    )
    if fallback_due:
        use_side_flip = bool(side_flip_prompt and cfg.side_flip_enabled)
        use_normal_fallback = bool(cfg.fallback_enabled)

        if cfg.debug_log:
            if cfg_reloaded and disp.last_display_was_fallback:
                print("Config changed while in fallback, refreshing fallback display.")
            elif use_side_flip:
                print("Switching to side-flip prompt image.")
            elif use_normal_fallback:
                print("Switching to fallback image.")
            else:
                print("Fallback displays are disabled; keeping the current Pixoo image.")

        display_shown = False
        if use_side_flip:
            display_shown = show_side_flip_prompt(
                side_flip_prompt.get("to_side"),
                next_position=side_flip_prompt.get("next_position"),
            )
            if display_shown is not False:
                write_side_flip_prompt(
                    from_side=side_flip_prompt.get("from_side"),
                    to_side=side_flip_prompt.get("to_side"),
                    next_title=side_flip_prompt.get("next_title"),
                    next_position=side_flip_prompt.get("next_position"),
                )
        elif use_normal_fallback:
            clear_side_flip_prompt()
            display_shown = show_fallback_image()
        else:
            clear_side_flip_prompt()

        # Mocked display functions in unit tests return a MagicMock; only an
        # explicit False means that no frame reached the Pixoo.
        disp.last_display_was_fallback = display_shown is not False
        disp.last_display_was_inferred = False

    if cfg.auto_sleep > 0 and disp.consecutive_failures >= cfg.auto_sleep:
        print("No song detected for a while, entering sleep mode.")
        return True
    return False


def should_update_display(
    *,
    disp: DisplayState,
    song_id: tuple[str, str],
    score: int,
) -> tuple[bool, bool]:
    is_same_song = song_id == disp.last_song_id
    if is_same_song and (disp.last_display_was_fallback or disp.last_display_was_inferred):
        return True, False
    if not is_same_song:
        return True, False

    if disp.last_song_variant_score is not None and score <= disp.last_song_variant_score:
        return False, False
    return True, disp.last_song_variant_score is not None


def _song_info(track: RecognizedTrack, canonical_title: str, score: int) -> dict[str, Any]:
    return {
        "artist": track.artist,
        "title": canonical_title,
        "album": track.album,
        "cover_url": track.cover_url,
        "genre": track.genre,
        "track_id": track.shazam_track_id,
        "artist_id": track.shazam_artist_id,
        "duration_ms": track.duration_ms,
        "discogs_release_id": track.discogs_release_id,
        "discogs_position": track.discogs_position,
        "discogs_side": track.discogs_side,
        "discogs_track_index": track.discogs_track_index,
        "discogs_track_count": track.discogs_track_count,
        "discogs_side_track_number": track.discogs_side_track_number,
        "discogs_side_track_count": track.discogs_side_track_count,
        "discogs_match_source": track.discogs_match_source,
        "discogs_confidence": track.discogs_confidence,
        "discogs_cover_url": track.discogs_cover_url,
        "discogs_year": track.discogs_year,
        "discogs_label": track.discogs_label,
        "discogs_catalog_number": track.discogs_catalog_number,
        "discogs_expected_next_title": track.discogs_expected_next_title,
        "discogs_expected_next_artist": track.discogs_expected_next_artist,
        "discogs_expected_next_position": track.discogs_expected_next_position,
        "discogs_expected_next_side": track.discogs_expected_next_side,
        "song_id": (track.artist.strip().casefold(), canonical_title.casefold()),
        "score": score,
    }


def handle_song_result(
    cfg: LoopConfig,
    disp: DisplayState,
    cfg_reloaded: bool,
    track: RecognizedTrack,
) -> dict[str, Any] | None:
    disp.consecutive_failures = 0

    if track.artist == "UNKNOWN" and track.title == "UNKNOWN":
        if cfg.debug_log:
            print("Shazam returned UNKNOWN/UNKNOWN, keeping the previous status.")
        return None

    canonical_title = canonicalize_title(track.title)
    score = variant_score(track.title, track.album)
    info = _song_info(track, canonical_title, score)
    song_id = info["song_id"]

    should_update, better_variant = should_update_display(
        disp=disp,
        song_id=song_id,
        score=score,
    )
    is_same_song = song_id == disp.last_song_id
    should_skip_pixoo = not should_update or (
        is_same_song
        and not disp.last_display_was_fallback
        and not disp.last_display_was_inferred
        and not cfg_reloaded
        and not better_variant
    )

    if should_skip_pixoo:
        if cfg.debug_log:
            print("Same song as before, skipping Pixoo update.")
        info["did_update_display"] = False
        return info

    log_pixoo_update_reason(
        debug_log=cfg.debug_log,
        last_display_was_fallback=disp.last_display_was_fallback,
        cfg_reloaded=cfg_reloaded,
        is_same_song=is_same_song,
    )

    start_scrolling_display(track.cover_image, track.artist, canonical_title)
    bg_color = None
    try:
        rgb = dynamic_bg_color(track.cover_image)
        bg_color = f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
        send_rgb(rgb)
    except Exception as exc:
        if cfg.debug_log:
            print(f"[HA] Could not compute/send RGB: {exc}")

    disp.last_song_id = song_id
    disp.last_song_variant_score = score
    disp.last_display_was_fallback = False
    disp.last_display_was_inferred = track.discogs_match_source == "sequence_inferred"
    write_status(
        track.artist,
        canonical_title,
        cover_url=track.cover_url,
        album=track.album,
        genre=track.genre,
        bg_color=bg_color,
        track_id=track.shazam_track_id,
        artist_id=track.shazam_artist_id,
        duration_ms=track.duration_ms,
        discogs_release_id=track.discogs_release_id,
        discogs_position=track.discogs_position,
        discogs_side=track.discogs_side,
        discogs_track_index=track.discogs_track_index,
        discogs_track_count=track.discogs_track_count,
        discogs_side_track_number=track.discogs_side_track_number,
        discogs_side_track_count=track.discogs_side_track_count,
        discogs_match_source=track.discogs_match_source,
        discogs_confidence=track.discogs_confidence,
        discogs_cover_url=track.discogs_cover_url,
        discogs_year=track.discogs_year,
        discogs_label=track.discogs_label,
        discogs_catalog_number=track.discogs_catalog_number,
        discogs_expected_next_title=track.discogs_expected_next_title,
        discogs_expected_next_artist=track.discogs_expected_next_artist,
        discogs_expected_next_position=track.discogs_expected_next_position,
        discogs_expected_next_side=track.discogs_expected_next_side,
    )

    info["did_update_display"] = True
    return info


def update_song_stats_on_switch(
    *,
    st: StatsSwitchState,
    song_id: tuple[str, str],
    artist: str,
    title: str,
    album: str | None,
    cover_url: str | None,
    genre: str | None,
    track_id: str | None,
    artist_id: str | None,
    duration_ms: int | None,
    min_consecutive: int,
    repeat_guard_seconds: float = 120.0,
    allow_confirmation: bool = True,
) -> bool:
    st.last_counted = False

    def confirm() -> None:
        now = time.monotonic()
        last_counted_at = st.last_counted_at_by_song.get(song_id)
        should_count = (
            last_counted_at is None
            or repeat_guard_seconds <= 0
            or (now - last_counted_at) >= repeat_guard_seconds
        )

        st.current_song_id = song_id
        st.candidate_song_id = None
        st.candidate_streak = 0
        st.last_counted = should_count

        if not should_count:
            return

        _update_stats(
            artist,
            title,
            album,
            cover_url,
            genre,
            track_id,
            artist_id,
            duration_ms,
        )
        st.last_counted_at_by_song[song_id] = now

    if st.current_song_id is None:
        if st.candidate_song_id == song_id:
            st.candidate_streak += 1
        else:
            st.candidate_song_id = song_id
            st.candidate_streak = 1

        if st.candidate_streak >= min_consecutive and allow_confirmation:
            confirm()
            return True
        return False

    if song_id == st.current_song_id:
        st.candidate_song_id = None
        st.candidate_streak = 0
        return False

    if st.candidate_song_id == song_id:
        st.candidate_streak += 1
    else:
        st.candidate_song_id = song_id
        st.candidate_streak = 1

    if st.candidate_streak >= min_consecutive:
        if not allow_confirmation:
            # Keep the candidate armed without allowing an early transition to
            # inflate statistics. It confirms on the first later safe sample.
            st.candidate_streak = min_consecutive
            return False
        confirm()
        return True
    return False


def update_album_session_on_switch(
    *,
    st: AlbumState,
    album: str | None,
    title: str,
    min_tracks: int,
    min_consecutive: int,
) -> None:
    album_key = (album or "").strip()
    if not album_key:
        return

    if st.current_album is None:
        st.current_album = album_key
        st.current_album_unique_tracks = {title}
        st.current_album_session_counted = False
        st.candidate_album = None
        st.candidate_streak = 0
    elif album_key == st.current_album:
        st.current_album_unique_tracks.add(title)
        st.candidate_album = None
        st.candidate_streak = 0
    else:
        if st.candidate_album == album_key:
            st.candidate_streak += 1
        else:
            st.candidate_album = album_key
            st.candidate_streak = 1

        if st.candidate_streak >= min_consecutive:
            if (
                not st.current_album_session_counted
                and len(st.current_album_unique_tracks) >= min_tracks
            ):
                _increment_album_session(st.current_album)

            st.current_album = album_key
            st.current_album_unique_tracks = {title}
            st.current_album_session_counted = False
            st.candidate_album = None
            st.candidate_streak = 0

    if (
        st.current_album == album_key
        and not st.current_album_session_counted
        and len(st.current_album_unique_tracks) >= min_tracks
    ):
        _increment_album_session(st.current_album)
        st.current_album_session_counted = True


def maybe_add_listen_time(
    cfg: LoopConfig,
    did_confirm_switch: bool,
    artist: str,
    title: str,
    album: str | None,
    shazam_duration_ms: int | None,
) -> dict:
    if not did_confirm_switch:
        return {"ok": None, "skipped": True}

    result = add_listen_time_minutes_for_confirmed_song(
        artist,
        title,
        album,
        shazam_duration_ms,
    )
    if cfg.debug_log:
        if result.get("ok"):
            print(
                f"Added listen time: +{result['minutes']} min "
                f"(source={result['source']}, cached={result['cached']}), "
                f"total={result['total_minutes']} min"
            )
        else:
            print(f"Listen time not added: {result.get('error')}")
    return result


def flush_timed_listen_if_needed(cfg: LoopConfig, st: Any) -> None:
    if (
        not st.active_song_id
        or not st.active_needs_timer_fallback
        or st.active_started_at is None
    ):
        return

    seconds = time.monotonic() - st.active_started_at
    result = add_measured_listen_time_seconds(
        st.active_artist or "",
        st.active_title or "",
        st.active_album,
        seconds,
    )
    if cfg.debug_log:
        if result.get("ok"):
            print(
                f"Added measured listen time: +{result['minutes']} min "
                f"(source=measured_timer), total={result['total_minutes']} min"
            )
        else:
            print(f"Measured listen time not added: {result.get('error')}")


def start_or_replace_timed_listen(
    *,
    cfg: LoopConfig,
    st: Any,
    song_id: tuple[str, str],
    artist: str,
    title: str,
    album: str | None,
    needs_timer_fallback: bool,
) -> None:
    if st.active_song_id == song_id:
        return

    flush_timed_listen_if_needed(cfg, st)
    st.active_song_id = song_id
    st.active_artist = artist
    st.active_title = title
    st.active_album = album
    st.active_started_at = time.monotonic()
    st.active_needs_timer_fallback = needs_timer_fallback
