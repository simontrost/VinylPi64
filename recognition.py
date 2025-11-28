import asyncio
from shazamio import Shazam
from PIL import Image

from config_loader import CONFIG
from image_utils import load_image, build_static_frame
from divoom_api import PixooClient, PixooError
from audio_capture import record_sample


async def recognize_and_render():
    print("Starte Shazam-Erkennung ...")
    shazam = Shazam()

    audio_cfg = CONFIG["audio"]
    debug_cfg = CONFIG["debug"]
    img_cfg = CONFIG["image"]

    # Audio aufnehmen
    wav_bytes = record_sample()

    # Track erkennen
    result = await shazam.recognize(wav_bytes)
    track = result.get("track", {})
    title = track.get("title") or "UNKNOWN"
    artist = track.get("subtitle") or "UNKNOWN"
    cover_url = track.get("images", {}).get("coverart")

    if debug_cfg["logs"]:
        print(f"Erkannt: {artist} – {title}")
        print(f"Cover-URL: {cover_url}")

    if not cover_url:
        print("Kein Cover gefunden – abbrechen.")
        return

    # Cover laden
    cover_img = load_image(cover_url)

    tick = 0
    first_frame_saved = False
    pixoo = PixooClient()

    while True:
        # Frame mit aktuellem Tick (für Marquee)
        frame = build_static_frame(cover_img, artist, title, tick=tick)

        # Debug-Frame & Preview nur einmal (beim ersten Durchlauf) speichern
        if not first_frame_saved:
            if debug_cfg["pixoo_frame_path"]:
                frame.save(debug_cfg["pixoo_frame_path"])
                if debug_cfg["logs"]:
                    print(f"Finished: {debug_cfg['pixoo_frame_path']} created.")

            scale = img_cfg["preview_scale"]
            size = img_cfg["canvas_size"]
            preview = frame.resize(
                (size * scale, size * scale),
                Image.Resampling.NEAREST
            )

            if debug_cfg["preview_path"]:
                preview.save(debug_cfg["preview_path"])
                if debug_cfg["logs"]:
                    print(f"Finished: {debug_cfg['preview_path']} created.")

            first_frame_saved = True

        # An Pixoo senden (statt send_to_pixoo)
        try:
            pixoo.send_frame(frame)
        except PixooError as e:
            print(f"Pixoo not available or API-error: {e}")
            break

        tick += 1           # 1 Pixel pro Frame
        await asyncio.sleep(0.05)  # Scroll-Geschwindigkeit


def run_recognition():
    asyncio.run(recognize_and_render())
