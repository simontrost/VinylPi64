import sounddevice as sd
import soundfile as sf
import io

from config_loader import CONFIG

INPUT_DEVICE_INDEX = None


def auto_detect_usb_device():
    needle = CONFIG["audio"]["device_name_contains"].upper()
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        name = dev.get("name", "")
        max_in = dev.get("max_input_channels", 0)
        if max_in > 0 and needle in name.upper():
            print(f"Auto-Detected Turntable Device: #{idx} -> {name}")
            return idx

    print("No appropriate audio device was found.")
    return None


def choose_input_device_interactive():
    print(sd.query_devices())
    idx = int(input("Choose your desired input device: "))
    return idx


def record_sample():
    audio_cfg = CONFIG["audio"]

    sample_rate = audio_cfg["sample_rate"]
    seconds = audio_cfg["sample_seconds"]
    channels = audio_cfg["channels"]

    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                   channels=channels, dtype="int16")
    sd.wait()

    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    wav_bytes = buffer.getvalue()

    debug_path = audio_cfg.get("output_wav", "")
    if debug_path:
        sf.write(debug_path, audio, sample_rate, format="WAV")
        print(f"Debug-WAV gespeichert: {debug_path}")

    return wav_bytes