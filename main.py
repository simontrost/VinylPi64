import time
from audio_capture import record_sample
from recognition import run_recognition

from config_loader import CONFIG


def main_loop():
    delay = CONFIG["behavior"].get("loop_delay_seconds", 20)
    debug_log = CONFIG["debug"]["logs"]

    print(f"\nStarting to loop VinylPi64 (every {delay}s)\n")

    while True:
        try:
            if debug_log:
                print("\n--- new iteration---")

            wav_bytes = record_sample()
            if wav_bytes is None:
                print("No recording possible, trying again in 5s...")
                time.sleep(5)
                continue

            run_recognition(wav_bytes)

        except Exception as e:
            print(f"Error in loop: {e}")

        time.sleep(delay)


if __name__ == "__main__":
    main_loop()
