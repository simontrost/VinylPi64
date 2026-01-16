from vinylpi.core.recognition import start_scrolling_display, show_fallback_image
from vinylpi.core.title_variants import canonicalize_title, variant_score
from vinylpi.core.status import write_status

from vinylpi.core.statistics import (
    _update_stats,
    _increment_album_session,
    add_listen_time_minutes_for_confirmed_song,
)

from vinylpi.core.loop_state import LoopConfig, DisplayState, AlbumState, StatsSwitchState


def log_pixoo_update_reason(*, debug_log: bool, last_display_was_fallback: bool, cfg_reloaded: bool, is_same_song: bool) -> None:
    if not debug_log:
        return

    if last_display_was_fallback and is_same_song:
        print("Same song as before after Fallback, updating Pixoo.")
    elif last_display_was_fallback and not is_same_song:
        print("New song detected after Fallback, updating Pixoo.")
    elif cfg_reloaded and is_same_song:
        print("Config changed, updating Pixoo for same song.")
    elif cfg_reloaded and not is_same_song:
        print("Config changed and new song detected, updating Pixoo.")
    else:
        print("New song detected, updating Pixoo.")


def handle_no_result(cfg: LoopConfig, disp: DisplayState, cfg_reloaded: bool) -> bool:
    disp.consecutive_failures += 1
    if cfg.debug_log:
        print(f"No song detected for (#{disp.consecutive_failures} times in a row).")

    fallback_due = (
        disp.consecutive_failures >= cfg.fallback_allowed_failures
        and (not disp.last_display_was_fallback or cfg_reloaded)
    )

    if fallback_due:
        if cfg.debug_log:
            if cfg_reloaded and disp.last_display_was_fallback:
                print("Config changed while in fallback, updating fallback image.")
            elif not disp.last_display_was_fallback:
                print("Switching to fallback image.")
        show_fallback_image()
        disp.last_display_was_fallback = True

    if cfg.auto_sleep > 0 and disp.consecutive_failures >= cfg.auto_sleep:
        print("No song detected for a while, entering sleep mode.")
        return True

    return False


def should_update_display(*, disp: DisplayState, song_id: tuple[str, str], score: int) -> tuple[bool, bool]:
    is_same_song = (song_id == disp.last_song_id)
    better_variant = False

    if is_same_song:
        if disp.last_song_variant_score is not None and score <= disp.last_song_variant_score:
            return (False, False)
        if disp.last_song_variant_score is not None and score > disp.last_song_variant_score:
            better_variant = True
        return (True, better_variant)

    return (True, False)


def handle_song_result(cfg: LoopConfig, disp: DisplayState, cfg_reloaded: bool, result):
    disp.consecutive_failures = 0

    artist, title, cover_img, album, cover_url = result

    if artist == "UNKNOWN" and title == "UNKNOWN":
        if cfg.debug_log:
            print("Shazam returned UNKNOWN/UNKNOWN, keeping last dashboard status.")
        return None

    canonical_title = canonicalize_title(title)
    song_id = (artist.strip().casefold(), canonical_title)
    score = variant_score(title, album)

    should_update, better_variant = should_update_display(disp=disp, song_id=song_id, score=score)
    is_same_song = (song_id == disp.last_song_id)

    should_skip_pixoo = (
        not should_update
        or (
            is_same_song
            and not disp.last_display_was_fallback
            and not cfg_reloaded
            and not better_variant
        )
    )

    if should_skip_pixoo:
        if cfg.debug_log:
            print("Same song as before, skipping Pixoo update.")
        return {
            "artist": artist,
            "title": canonical_title,
            "album": album,
            "song_id": song_id,
            "score": score,
            "did_update_display": False,
        }

    log_pixoo_update_reason(
        debug_log=cfg.debug_log,
        last_display_was_fallback=disp.last_display_was_fallback,
        cfg_reloaded=cfg_reloaded,
        is_same_song=is_same_song,
    )

    start_scrolling_display(cover_img, artist, canonical_title)

    disp.last_song_id = song_id
    disp.last_song_variant_score = score
    disp.last_display_was_fallback = False

    write_status(artist, canonical_title, cover_url=cover_url, album=album)

    return {
        "artist": artist,
        "title": canonical_title,
        "album": album,
        "song_id": song_id,
        "score": score,
        "did_update_display": True,
    }


def update_song_stats_on_switch(*, st: StatsSwitchState, song_id, artist: str, title: str, album: str | None, min_consecutive: int) -> bool:
    did_confirm_switch = False

    if st.current_song_id is None:
        if st.candidate_song_id == song_id:
            st.candidate_streak += 1
        else:
            st.candidate_song_id = song_id
            st.candidate_streak = 1

        if st.candidate_streak >= min_consecutive:
            st.current_song_id = song_id
            st.candidate_song_id = None
            st.candidate_streak = 0
            _update_stats(artist, title, album)
            did_confirm_switch = True

        return did_confirm_switch

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
        st.current_song_id = song_id
        st.candidate_song_id = None
        st.candidate_streak = 0
        _update_stats(artist, title, album)
        did_confirm_switch = True

    return did_confirm_switch


def update_album_session_on_switch(*, st: AlbumState, album: str | None, title: str, min_tracks: int, min_consecutive: int) -> None:
    album_key = (album or "").strip()
    if not album_key:
        return

    if st.current_album is None:
        st.current_album = album_key
        st.current_album_unique_tracks = {title}
        st.current_album_session_counted = False
        st.candidate_album = None
        st.candidate_streak = 0
    else:
        if album_key == st.current_album:
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
                if (not st.current_album_session_counted) and (len(st.current_album_unique_tracks) >= min_tracks):
                    _increment_album_session(st.current_album)

                st.current_album = album_key
                st.current_album_unique_tracks = {title}
                st.current_album_session_counted = False
                st.candidate_album = None
                st.candidate_streak = 0

    if (st.current_album == album_key) and (not st.current_album_session_counted) and (len(st.current_album_unique_tracks) >= min_tracks):
        _increment_album_session(st.current_album)
        st.current_album_session_counted = True


def maybe_add_listen_time(cfg: LoopConfig, did_confirm_switch: bool, artist: str, title: str, album: str | None) -> None:
    if not did_confirm_switch:
        return

    res = add_listen_time_minutes_for_confirmed_song(artist, title, album)
    if cfg.debug_log:
        if res.get("ok"):
            print(
                f"Added listen time: +{res['minutes']} min "
                f"(cached={res['cached']}), total={res['total_minutes']} min"
            )
        else:
            print(f"Listen time not added: {res.get('error')}")
