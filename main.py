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
    consecutive_failures = 0         # Anzahl aufeinanderfolgender Erkennungsfehler

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

            # =========================
            #  FALL: KEIN SONG ERKANNT
            # =========================
            if result is None:
                consecutive_failures += 1
                if debug_log:
                    print(f"Keine gültige Erkennung (#{consecutive_failures} in Folge).")

                # Fallback erst ab z.B. 3 Fehlschlägen in Folge
                if consecutive_failures >= 3 and not last_display_was_fallback:
                    print(">= 3 Erkennungsfehler in Folge – Fallback anzeigen.")
                    show_fallback_image()
                    last_display_was_fallback = True
                # last_song_id bleibt bewusst unverändert
            else:
                # ==================
                #  FALL: SONG ERKANNT
                # ==================
                consecutive_failures = 0  # Fehlerzähler resetten

                artist, title, cover_img = result
                song_id = (
                    artist.strip().casefold(),
                    title.strip().casefold(),
                )

                # Gleicher Song wie vorher und aktuell KEIN Fallback aktiv:
                # -> nix neu rendern, Scroll-Thread läuft weiter
                if song_id == last_song_id and not last_display_was_fallback:
                    if debug_log:
                        print("Gleicher Song wie zuvor – Pixoo-Update übersprungen.")
                else:
                    # Entweder neuer Song ODER Fallback war aktiv
                    if debug_log:
                        if last_display_was_fallback and song_id == last_song_id:
                            print("Gleicher Song wie zuvor, aber Fallback aktiv – Pixoo wird aktualisiert.")
                        elif last_display_was_fallback:
                            print("Neuer Song nach Fallback – Pixoo wird aktualisiert.")
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
