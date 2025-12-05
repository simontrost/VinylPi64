import sounddevice as sd
import soundfile as sf
import io

from config_loader import CONFIG

def auto_detect_usb_device():
    needle = CONFIG["audio"]["device_name_contains"].upper()
    debug_log = CONFIG["debug"]["logs"]

    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        name = dev.get("name", "")
        max_in = dev.get("max_input_channels", 0)
        if max_in > 0 and needle in name.upper() and debug_log:
            print(f"Auto-Detected Turntable Device: #{idx} -> {name}")
            return idx

    print("No appropriate audio device was found. Try using 'arecord -l'\n Set the name in the config.json file.")
    return None

def record_sample():
    debug_log = CONFIG["debug"]["logs"]
    audio_cfg = CONFIG["audio"]
    debug_cfg = CONFIG["debug"]
    sample_rate = audio_cfg["sample_rate"]
    seconds = audio_cfg["sample_seconds"]
    channels = audio_cfg["channels"]
    debug_wav_path = debug_cfg["wav_path"]

    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate,
                   channels=channels, dtype="int16")
    sd.wait()

    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    wav_bytes = buffer.getvalue()

    if debug_wav_path:
        sf.write(debug_wav_path, audio, sample_rate, format="WAV")
        if debug_log:
            print(f"Saved WAV file at: {debug_wav_path}")

    return wav_bytes