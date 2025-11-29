# main.py
import time
from audio_capture import record_sample
from recognition import recognize_song, start_scrolling_display
from config_loader import CONFIG


def main_loop():
    delay = CONFIG["behavior"].get("loop_delay_seconds", 20)
    debug_log = CONFIG["debug"]["logs"]

    print(f"\nStarting to loop VinylPi64 (every {delay}s)\n")

    while True:
        try:
            if debug_log:
                print("Recording sample...")

            wav_bytes = record_sample()
            if not wav_bytes:
                print("No recording possible, trying again in 5s...")
                time.sleep(5)
                continue

            # --- Erkennung (blockiert kurz) ---
            result = recognize_song(wav_bytes)
            if result is None:
                print("Keine gültige Erkennung, nächster Versuch...")
            else:
                artist, title, cover_img = result

                # --- neues Scrollen im Hintergrund starten ---
                start_scrolling_display(cover_img, artist, title)

        except Exception as e:
            print(f"Error in loop: {e}")

        # während dieser Pause läuft der Scroll-Thread weiter
        time.sleep(delay)


if __name__ == "__main__":
    main_loop()