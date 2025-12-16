import sounddevice as sd
import soundfile as sf
import io

from vinylpi.web.services.config import read_config


def auto_detect_usb_device():
    cfg = read_config()
    needle = (cfg["audio"]["device_name_contains"] or "").upper()
    debug_log = bool(cfg["debug"]["logs"])

    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        name = dev.get("name", "")
        max_in = dev.get("max_input_channels", 0)
        if max_in > 0 and needle in name.upper():
            if debug_log:
                print(f"Auto-Detected Turntable Device: #{idx} -> {name}")
            return idx

    print("No appropriate audio device was found. Try using 'arecord -l'\n Set the name in the config.json file.")
    return None

def record_sample():
    cfg = read_config()
    debug_log = bool(cfg["debug"]["logs"])
    audio_cfg = cfg["audio"]
    debug_cfg = cfg["debug"]

    sample_rate = int(audio_cfg["sample_rate"])
    seconds = float(audio_cfg["sample_seconds"])
    channels = int(audio_cfg["channels"])
    debug_wav_path = debug_cfg.get("wav_path") or ""

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