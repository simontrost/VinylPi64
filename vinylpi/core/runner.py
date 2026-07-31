from __future__ import annotations

import time

from vinylpi.config.config_watcher import maybe_log_config_reload
from vinylpi.core.audio_capture import record_sample
from vinylpi.core.loop_logic import (
    flush_timed_listen_if_needed,
    handle_no_result,
    handle_song_result,
    maybe_add_listen_time,
    start_or_replace_timed_listen,
    update_album_session_on_switch,
    update_song_stats_on_switch,
)
from vinylpi.core.loop_state import (
    AlbumState,
    DisplayState,
    LoopConfig,
    StatsSwitchState,
    TimedListenState,
)
from vinylpi.core.recognition import recognize_song
from vinylpi.core.storage import initialize_storage
from vinylpi.core.title_variants import is_live_variant
from vinylpi.config.runtime import read_config

MIN_TRACKS_FOR_ALBUM_SESSION = 2
MIN_CONSECUTIVE_FOR_SWITCH = 2


def main_loop() -> None:
    initialize_storage()
    cfg = LoopConfig.from_config(read_config())
    if cfg.debug_log:
        print(f"\nStarting VinylPi64 recognition loop (every {cfg.delay}s)\n")

    display_state = DisplayState()
    album_state = AlbumState()
    stats_state = StatsSwitchState()
    timed_listen_state = TimedListenState()

    while True:
        try:
            cfg_reloaded = maybe_log_config_reload()
            cfg = LoopConfig.from_config(read_config())

            if cfg.debug_log:
                print("Recording sample ...")

            wav_bytes = record_sample()
            if not wav_bytes:
                print("No recording possible, trying again in 5s ...")
                time.sleep(5)
                continue

            track = recognize_song(wav_bytes)
            if track is None:
                flush_timed_listen_if_needed(cfg, timed_listen_state)
                timed_listen_state = TimedListenState()
                if handle_no_result(cfg, display_state, cfg_reloaded):
                    break
                time.sleep(cfg.delay)
                continue

            album_locked = bool(
                album_state.current_album_session_counted
                and album_state.current_album
            )
            if album_locked and track.album:
                locked_album = album_state.current_album or ""
                if (
                    track.album.strip() != locked_album.strip()
                    and is_live_variant(track.title, track.album)
                ):
                    if cfg.debug_log:
                        print(
                            "Ignoring live/unplugged mismatch: "
                            f"detected album='{track.album}', "
                            f"locked album='{locked_album}', title='{track.title}'"
                        )
                    if handle_no_result(cfg, display_state, cfg_reloaded):
                        break
                    time.sleep(cfg.delay)
                    continue

            info = handle_song_result(cfg, display_state, cfg_reloaded, track)
            if info is None:
                time.sleep(cfg.delay)
                continue

            did_confirm = update_song_stats_on_switch(
                st=stats_state,
                song_id=info["song_id"],
                artist=info["artist"],
                title=info["title"],
                album=info["album"],
                cover_url=info.get("cover_url"),
                genre=info.get("genre"),
                track_id=info.get("track_id"),
                artist_id=info.get("artist_id"),
                duration_ms=info.get("duration_ms"),
                min_consecutive=MIN_CONSECUTIVE_FOR_SWITCH,
            )
            listen_result = maybe_add_listen_time(
                cfg,
                did_confirm,
                info["artist"],
                info["title"],
                info["album"],
                info.get("duration_ms"),
            )

            if did_confirm:
                start_or_replace_timed_listen(
                    cfg=cfg,
                    st=timed_listen_state,
                    song_id=info["song_id"],
                    artist=info["artist"],
                    title=info["title"],
                    album=info["album"],
                    needs_timer_fallback=not bool(listen_result.get("ok")),
                )

            update_album_session_on_switch(
                st=album_state,
                album=info["album"],
                title=info["title"],
                min_tracks=MIN_TRACKS_FOR_ALBUM_SESSION,
                min_consecutive=MIN_CONSECUTIVE_FOR_SWITCH,
            )

        except Exception as exc:
            print(f"Error in loop: {exc}")

        time.sleep(cfg.delay)
