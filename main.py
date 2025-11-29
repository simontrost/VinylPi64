# main.py
import time
from audio_capture import record_sample
from recognition import recognize_song, start_scrolling_display, show_fallback_image
from config_loader import CONFIG


def main_loop():
    delay = CONFIG["behavior"].get("loop_delay_seconds", 20)
    debug_log = CONFIG["debug"]["logs"]

    print(f"\nStarting to loop VinylPi64 (every {delay}s)\n")

    last_song_id = None              # (artist, title) des zuletzt erkannten Songs
    last_display_was_fallback = False

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
                print("Keine gültige Erkennung – Fallback anzeigen.")
                show_fallback_image()

                # Merken, dass jetzt Fallback auf dem Pixoo liegt
                last_display_was_fallback = True
                # last_song_id lassen wir so, damit wir noch wissen,
                # welcher Song „in der Luft“ war, falls du das später brauchen willst.
            else:
                artist, title, cover_img = result

                song_id = (
                    artist.strip().casefold(),
                    title.strip().casefold(),
                )

                # FALL 1: gleicher Song und es lief bereits dieser Song → nichts tun
                if song_id == last_song_id and not last_display_was_fallback:
                    if debug_log:
                        print("Gleicher Song wie zuvor – Pixoo-Update übersprungen.")
                    # Scroll-Thread läuft weiter wie gehabt

                # FALL 2: neuer Song ODER Fallback war aktiv → neu rendern & scrollen
                else:
                    if debug_log:
                        if last_display_was_fallback:
                            print("Gleicher Song wie zuvor, aber Fallback war aktiv – Pixoo wird aktualisiert.")
                        else:
                            print("Neuer Song erkannt – Pixoo wird aktualisiert.")

                    start_scrolling_display(cover_img, artist, title)
                    last_song_id = song_id
                    last_display_was_fallback = False

        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    main_loop()
