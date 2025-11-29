# main.py
import time
from audio_capture import record_sample
from recognition import recognize_song, start_scrolling_display
from config_loader import CONFIG


def main_loop():
    delay = CONFIG["behavior"].get("loop_delay_seconds", 20)
    debug_log = CONFIG["debug"]["logs"]

    print(f"\nStarting to loop VinylPi64 (every {delay}s)\n")

    last_song_id = None   # (artist, title) des zuletzt angezeigten Songs

    while True:
        try:
            if debug_log:
                print("Recording sample...")

            wav_bytes = record_sample()
            if not wav_bytes:
                print("No recording possible, trying again in 5s...")
                time.sleep(5)
                continue

            # --- Shazam-Erkennung ---
            result = recognize_song(wav_bytes)
            if result is None:
                print("Keine gültige Erkennung, nächster Versuch...")
            else:
                artist, title, cover_img = result

                # Normalisierte ID für Song bauen
                song_id = (
                    artist.strip().casefold(),
                    title.strip().casefold(),
                )

                # --- Prüfen, ob Song gleich geblieben ist ---
                if song_id == last_song_id:
                    if debug_log:
                        print("Gleicher Song wie zuvor – Pixoo-Update übersprungen.")
                    # alter Scroll-Thread läuft einfach weiter
                else:
                    if debug_log:
                        print("Neuer Song erkannt – Pixoo wird aktualisiert.")
                    start_scrolling_display(cover_img, artist, title)
                    last_song_id = song_id

        except Exception as e:
            print(f"Error in loop: {e}")

        # währenddessen scrollt der Text weiter im Hintergrund
        time.sleep(delay)


if __name__ == "__main__":
    main_loop()
