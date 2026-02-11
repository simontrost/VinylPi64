import time
from vinylpi.core.audio_capture import record_sample
from vinylpi.core.recognition import recognize_song
from vinylpi.web.services.config import read_config
from vinylpi.config.config_watcher import maybe_log_config_reload
from vinylpi.core.title_variants import is_live_variant
from vinylpi.core.loop_state import LoopConfig, DisplayState, AlbumState, StatsSwitchState
from vinylpi.core.loop_logic import (
    handle_no_result,
    handle_song_result,
    update_song_stats_on_switch,
    update_album_session_on_switch,
    maybe_add_listen_time,
)

def main_loop():
    cfg = LoopConfig.from_config(read_config())
    if cfg.debug_log:
        print(f"\nStarting to loop VinylPi64 (every {cfg.delay}s)\n")

    disp = DisplayState()
    album_state = AlbumState()
    stats_state = StatsSwitchState()

    MIN_TRACKS_FOR_ALBUM_SESSION = 2
    MIN_CONSECUTIVE_FOR_SWITCH = 2

    while True:
        try:
            cfg_reloaded = maybe_log_config_reload()
            cfg = LoopConfig.from_config(read_config())

            if cfg.debug_log:
                print("Recording sample...")

            wav_bytes = record_sample()
            if not wav_bytes:
                print("No recording possible, trying again in 5s...")
                time.sleep(5)
                continue

            result = recognize_song(wav_bytes)

            if result is not None:
                artist, title, cover_img, album, cover_url = result

                locked = bool(album_state.current_album_session_counted and album_state.current_album)
                if locked and album:
                    locked_album = album_state.current_album

                    if album.strip() != locked_album.strip() and is_live_variant(title, album):
                        if cfg.debug_log:
                            print(
                                f"Ignoring live/unplugged mismatch: detected album='{album}' "
                                f"but locked_album='{locked_album}' (title='{title}')"
                            )

                        if handle_no_result(cfg, disp, cfg_reloaded):
                            break
                        time.sleep(cfg.delay)
                        continue

            info = handle_song_result(cfg, disp, cfg_reloaded, result)
            if info is None:
                time.sleep(cfg.delay)
                continue

            did_confirm = update_song_stats_on_switch(
                st=stats_state,
                song_id=info["song_id"],
                artist=info["artist"],
                title=info["title"],
                album=info["album"],
                min_consecutive=MIN_CONSECUTIVE_FOR_SWITCH,
            )
            maybe_add_listen_time(cfg, did_confirm, info["artist"], info["title"], info["album"])

            update_album_session_on_switch(
                st=album_state,
                album=info["album"],
                title=info["title"],
                min_tracks=MIN_TRACKS_FOR_ALBUM_SESSION,
                min_consecutive=MIN_CONSECUTIVE_FOR_SWITCH,
            )

        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(cfg.delay)
