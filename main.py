import time

from audio_capture import record_sample
from recognition import run_recognition
from config_loader import CONFIG


def main_loop():
    delay = CONFIG["behavior"].get("loop_delay_seconds", 5)
    debug_log = CONFIG["debug"]["logs"]

    if debug_log:
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

            # Shazam + Pixoo + Fallback passiert nun komplett in recognition.run_recognition
            run_recognition(wav_bytes)

        except KeyboardInterrupt:
            print("Interrupted by user, exiting.")
            break
        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    main_loop()
