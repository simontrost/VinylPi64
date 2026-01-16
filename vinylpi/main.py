import time
import json
from vinylpi.core.audio_capture import record_sample
from vinylpi.core.recognition import recognize_song, start_scrolling_display, show_fallback_image
from vinylpi.web.services.config import read_config
from vinylpi.core.statistics import _update_stats, _increment_album_session, add_listen_time_minutes_for_confirmed_song
from vinylpi.paths import STATUS_PATH, CONFIG_PATH

_last_cfg_mtime: float | None = None


import re

_REMOVED_SUFFIXES = [
    r"\(.*?remaster.*?\)",
    r"\(.*?remastered.*?\)",
    r"\(.*?remix.*?\)", 
    r"\(.*?version.*?\)",
    r"\(.*?edit.*?\)",
    r"\(.*?deluxe.*?\)",
    r"\(.*?mono.*?\)",
    r"\(.*?stereo.*?\)",
    r"\(.*?reissue.*?\)",
    r"\(.*?\d{4}.*?\)",
]

_REMOVED_KEYWORDS = [
    "remaster",
    "remix",
    "remastered",
    "version",
    "edit",
    "deluxe",
    "mono",
    "stereo",
    "reissue",
]

def variant_score(title: str, album: str | None) -> int:
    t = title.lower()
    a = (album or "").lower()

    score = 0

    if "live" in t:
        score -= 100
    if "acoustic" in t:
        score -= 80
    if "cover" in t:
        score -= 80
    if "remix" in t:
        score -= 60
    if "instrumental" in t:
        score -= 40
    if "remaster" in t:
        score -= 20
    if "greatest hits" in a:
        score -= 30
    if "compilation" in a:
        score -= 30

    if album and not any(x in a for x in ["live", "hits", "best of"]):
        score += 20

    return score


def canonicalize_title(title: str) -> str:
    t = title.lower()

    for pat in _REMOVED_SUFFIXES:
        t = re.sub(pat, "", t)

    t = re.split(r"\s+-\s+", t)[0]

    for kw in _REMOVED_KEYWORDS:
        t = re.sub(rf"\b{re.escape(kw)}\b", "", t)

    t = re.sub(r"\s+", " ", t).strip()

    return t


def maybe_log_config_reload() -> bool:
    global _last_cfg_mtime

    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        return False

    if _last_cfg_mtime is None:
        _last_cfg_mtime = mtime
        return False

    if mtime != _last_cfg_mtime:
        _last_cfg_mtime = mtime
        cfg = read_config(force=True)
        if cfg.get("debug", {}).get("logs"):
            print("Config reloaded from disk.")
        return True

    return False

def _write_status(artist, title, cover_url=None, album=None):
    data = {
        "artist": artist,
        "title": title,
        "cover_url": cover_url,
        "album": album,
    }
    try:
        STATUS_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATUS_PATH.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:
        print(f"Could not write status file: {e}")


def _log_pixoo_update_reason(
    *,
    debug_log: bool,
    last_display_was_fallback: bool,
    cfg_reloaded: bool,
    is_same_song: bool,
) -> None:
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


def _update_song_stats_on_switch(
    *,
    song_id,
    artist: str,
    title: str,
    album: str | None,
    stats_current_song_id,
    stats_candidate_song_id,
    stats_candidate_streak: int,
    min_consecutive_for_switch: int,
):
    did_confirm_switch = False

    if stats_current_song_id is None:
        if stats_candidate_song_id == song_id:
            stats_candidate_streak += 1
        else:
            stats_candidate_song_id = song_id
            stats_candidate_streak = 1

        if stats_candidate_streak >= min_consecutive_for_switch:
            stats_current_song_id = song_id
            stats_candidate_song_id = None
            stats_candidate_streak = 0
            _update_stats(artist, title, album)
            did_confirm_switch = True

        return (
            stats_current_song_id,
            stats_candidate_song_id,
            stats_candidate_streak,
            did_confirm_switch,
        )

    if song_id == stats_current_song_id:
        stats_candidate_song_id = None
        stats_candidate_streak = 0
        return (
            stats_current_song_id,
            stats_candidate_song_id,
            stats_candidate_streak,
            False,
        )

    if stats_candidate_song_id == song_id:
        stats_candidate_streak += 1
    else:
        stats_candidate_song_id = song_id
        stats_candidate_streak = 1

    if stats_candidate_streak >= min_consecutive_for_switch:
        stats_current_song_id = song_id
        stats_candidate_song_id = None
        stats_candidate_streak = 0
        _update_stats(artist, title, album)
        did_confirm_switch = True

    return (
        stats_current_song_id,
        stats_candidate_song_id,
        stats_candidate_streak,
        did_confirm_switch,
    )



def _update_album_session_on_switch(
    *,
    album: str | None,
    title: str,
    current_album,
    current_album_unique_tracks: set[str],
    current_album_session_counted: bool,
    candidate_album,
    candidate_streak: int,
    min_tracks_for_album_session: int,
    min_consecutive_for_switch: int,
):
    album_key = (album or "").strip()
    if not album_key:
        return (
            current_album,
            current_album_unique_tracks,
            current_album_session_counted,
            candidate_album,
            candidate_streak,
        )

    if current_album is None:
        current_album = album_key
        current_album_unique_tracks = {title}
        current_album_session_counted = False
        candidate_album = None
        candidate_streak = 0
    else:
        if album_key == current_album:
            current_album_unique_tracks.add(title)
            candidate_album = None
            candidate_streak = 0
        else:
            if candidate_album == album_key:
                candidate_streak += 1
            else:
                candidate_album = album_key
                candidate_streak = 1

            if candidate_streak >= min_consecutive_for_switch:
                if (
                    not current_album_session_counted
                    and len(current_album_unique_tracks) >= min_tracks_for_album_session
                ):
                    _increment_album_session(current_album)

                current_album = album_key
                current_album_unique_tracks = {title}
                current_album_session_counted = False
                candidate_album = None
                candidate_streak = 0

    if (
        current_album == album_key
        and not current_album_session_counted
        and len(current_album_unique_tracks) >= min_tracks_for_album_session
    ):
        _increment_album_session(current_album)
        current_album_session_counted = True

    return (
        current_album,
        current_album_unique_tracks,
        current_album_session_counted,
        candidate_album,
        candidate_streak,
    )

def main_loop():
    # initial defaults (werden in der Loop überschrieben)
    delay = 10
    debug_log = False
    fallback = {"allowed_failures": 3}
    auto_sleep = 50

    cfg0 = read_config()
    delay = cfg0["behavior"].get("loop_delay_seconds", delay)
    debug_log = cfg0["debug"].get("logs", False)
    fallback = cfg0.get("fallback", fallback)
    auto_sleep = cfg0["behavior"].get("auto_sleep", auto_sleep)

    if debug_log:
        print(f"\nStarting to loop VinylPi64 (every {delay}s)\n")

    # Pixoo / display-status
    last_song_id = None
    last_song_variant_score = None
    last_display_was_fallback = False
    consecutive_failures = 0

    # Album-Session-Tracking
    current_album = None
    current_album_session_counted = False
    current_album_unique_tracks: set[str] = set()
    candidate_album = None
    candidate_streak = 0

    MIN_TRACKS_FOR_ALBUM_SESSION = 2
    MIN_CONSECUTIVE_FOR_SWITCH = 2

    # Song-/Artist-Stats-Tracking
    stats_current_song_id = None
    stats_candidate_song_id = None
    stats_candidate_streak = 0

    while True:
        try:
            cfg_reloaded = maybe_log_config_reload()

            cfg = read_config()

            delay = cfg["behavior"].get("loop_delay_seconds", 10)
            debug_log = cfg["debug"].get("logs", False)
            fallback = cfg.get("fallback", {})
            auto_sleep = cfg["behavior"].get("auto_sleep", 50)

            if debug_log:
                print("Recording sample...")

            wav_bytes = record_sample()
            if not wav_bytes:
                print("No recording possible, trying again in 5s...")
                time.sleep(5)
                continue

            result = recognize_song(wav_bytes)

            # --- case 1: no Track recognized ---
            if result is None:
                consecutive_failures += 1
                if debug_log:
                    print(f"No song detected for (#{consecutive_failures} times in a row).")

                allowed = int(fallback.get("allowed_failures", 3))
                fallback_due = (
                    consecutive_failures >= allowed
                    and (not last_display_was_fallback or cfg_reloaded)
                )

                if fallback_due:
                    if debug_log:
                        if cfg_reloaded and last_display_was_fallback:
                            print("Config changed while in fallback, updating fallback image.")
                        elif not last_display_was_fallback:
                            print("Switching to fallback image.")
                    show_fallback_image()
                    last_display_was_fallback = True

                if auto_sleep > 0 and consecutive_failures >= auto_sleep:
                    print("No song detected for a while, entering sleep mode.")
                    break

                time.sleep(delay)
                continue

            # --- case 2: Song detected ---
            consecutive_failures = 0
            artist, title, cover_img, album, cover_url = result

            if artist == "UNKNOWN" and title == "UNKNOWN":
                if debug_log:
                    print("Shazam returned UNKNOWN/UNKNOWN, keeping last dashboard status.")
                time.sleep(delay)
                continue

            canonical_title = canonicalize_title(title)

            song_id = (
                artist.strip().casefold(),
                canonical_title,
            )

            score = variant_score(title, album)

            is_same_canonical = song_id == last_song_id

            if is_same_canonical:
                if last_song_variant_score is not None and score <= last_song_variant_score:
                    # Schlechtere oder gleiche Variante → IGNORIEREN
                    if debug_log:
                        print("Same song, worse or equal variant – ignoring.")
                    time.sleep(delay)
                    continue
                else:
                    last_song_variant_score = score


            is_same_song = (song_id == last_song_id)
            should_skip_pixoo = (
                is_same_song and not last_display_was_fallback and not cfg_reloaded
            )

            if should_skip_pixoo:
                if debug_log:
                    print("Same song as before, skipping Pixoo update.")
            else:
                _log_pixoo_update_reason(
                    debug_log=debug_log,
                    last_display_was_fallback=last_display_was_fallback,
                    cfg_reloaded=cfg_reloaded,
                    is_same_song=is_same_song,
                )

                start_scrolling_display(cover_img, artist, title)
                last_song_id = song_id
                last_song_variant_score = score
                last_display_was_fallback = False
                _write_status(artist, title, cover_url=cover_url, album=album)

            (
                stats_current_song_id,
                stats_candidate_song_id,
                stats_candidate_streak,
                did_confirm_switch,
            ) = _update_song_stats_on_switch(
                song_id=song_id,
                artist=artist,
                title=canonical_title,
                album=album,
                stats_current_song_id=stats_current_song_id,
                stats_candidate_song_id=stats_candidate_song_id,
                stats_candidate_streak=stats_candidate_streak,
                min_consecutive_for_switch=MIN_CONSECUTIVE_FOR_SWITCH,
            )

            if did_confirm_switch:
                res = add_listen_time_minutes_for_confirmed_song(artist, canonical_title, album)
                if debug_log:
                    if res.get("ok"):
                        print(
                            f"Added listen time: +{res['minutes']} min "
                            f"(cached={res['cached']}), total={res['total_minutes']} min"
                        )
                    else:
                        print(f"Listen time not added: {res.get('error')}")
            else:
                if debug_log and stats_current_song_id is None:
                    print(
                        f"Song not confirmed yet (streak={stats_candidate_streak}/{MIN_CONSECUTIVE_FOR_SWITCH})"
                    )

            (
                current_album,
                current_album_unique_tracks,
                current_album_session_counted,
                candidate_album,
                candidate_streak,
            ) = _update_album_session_on_switch(
                album=album,
                title=title,
                current_album=current_album,
                current_album_unique_tracks=current_album_unique_tracks,
                current_album_session_counted=current_album_session_counted,
                candidate_album=candidate_album,
                candidate_streak=candidate_streak,
                min_tracks_for_album_session=MIN_TRACKS_FOR_ALBUM_SESSION,
                min_consecutive_for_switch=MIN_CONSECUTIVE_FOR_SWITCH,
            )

        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(delay)



if __name__ == "__main__":
    main_loop()
