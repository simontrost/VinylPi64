import time
import json
from pathlib import Path
from audio_capture import record_sample
from recognition import recognize_song, start_scrolling_display, show_fallback_image
from config_loader import CONFIG

STATUS_PATH = Path("/tmp/vinylpi_status.json")

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

                if consecutive_failures >= fallback["allowed_failures"] and not last_display_was_fallback:
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

                if song_id == last_song_id and not last_display_was_fallback:
                    if debug_log:
                        print("Same song as before, skipping Pixoo update.")
                else:
                    if debug_log:
                        if last_display_was_fallback and song_id == last_song_id:
                            print("Same song as before after Fallback, updating Pixoo.")
                        elif last_display_was_fallback:
                            print("New song detected after Fallback, updating Pixoo.")
                        else:
                            print("New song detected, updating Pixoo.")

                    start_scrolling_display(cover_img, artist, title)
                    last_song_id = song_id
                    last_display_was_fallback = False

                    _write_status(artist, title, cover_url=cover_url, album=album)

        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    main_loop()
