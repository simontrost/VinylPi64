import time
import json
from pathlib import Path
from audio_capture import record_sample
from recognition import recognize_song, start_scrolling_display, show_fallback_image
from config_loader import CONFIG, reload_config
from statistics import _load_stats, _save_stats, _update_stats

STATUS_PATH = Path("/tmp/vinylpi_status.json")
BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG_PATH = BASE_DIR / "config.json"
STATS_PATH = BASE_DIR / "stats.json"

STATUS_PATH = Path("/tmp/vinylpi_status.json")
_last_cfg_mtime = CONFIG_PATH.stat().st_mtime

def _maybe_reload_config() -> bool:
    global _last_cfg_mtime
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        return False

    if mtime != _last_cfg_mtime:
        reload_config()
        _last_cfg_mtime = mtime
        if CONFIG["debug"]["logs"]:
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


def main_loop():
    delay = CONFIG["behavior"].get("loop_delay_seconds", 10)
    debug_log = CONFIG["debug"]["logs"]
    fallback = CONFIG["fallback"]

    if debug_log:
        print(f"\nStarting to loop VinylPi64 (every {delay}s)\n")

    last_song_id = None              
    last_display_was_fallback = False
    consecutive_failures = 0        

    while True:
        try:
            cfg_reloaded = _maybe_reload_config()

            delay = CONFIG["behavior"].get("loop_delay_seconds", 10)
            debug_log = CONFIG["debug"]["logs"]
            fallback = CONFIG["fallback"]

            if debug_log:
                print("Recording sample...")

            wav_bytes = record_sample()
            if not wav_bytes:
                print("No recording possible, trying again in 5s...")
                time.sleep(5)
                continue

            result = recognize_song(wav_bytes)

            if result is None:
                consecutive_failures += 1
                if debug_log:
                    print(f"No song detected for (#{consecutive_failures} times in a row).")

                allowed = fallback["allowed_failures"]

                if consecutive_failures >= allowed and (not last_display_was_fallback or cfg_reloaded):
                    if debug_log:
                        if cfg_reloaded and last_display_was_fallback:
                            print("Config changed while in fallback, updating fallback image.")
                        elif not last_display_was_fallback:
                            print("Switching to fallback image.")
                    show_fallback_image()
                    last_display_was_fallback = True

            else:
                consecutive_failures = 0 

                artist, title, cover_img, album, cover_url = result

                if artist == "UNKNOWN" and title == "UNKNOWN":
                    if debug_log:
                        print("Shazam returned UNKNOWN/UNKNOWN, keeping last dashboard status.")
                    time.sleep(delay)
                    continue

                song_id = (
                    artist.strip().casefold(),
                    title.strip().casefold(),
                )

                is_same_song = (song_id == last_song_id)
                should_skip_pixoo = is_same_song and not last_display_was_fallback and not cfg_reloaded

                if should_skip_pixoo:
                    if debug_log:
                        print("Same song as before, skipping Pixoo update.")
                else:
                    if debug_log:
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

                    start_scrolling_display(cover_img, artist, title)
                    last_song_id = song_id
                    last_display_was_fallback = False

                    _write_status(artist, title, cover_url=cover_url, album=album)

                    if not is_same_song:
                        _update_stats(artist, title, album)


        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    main_loop()
