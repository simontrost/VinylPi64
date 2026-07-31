from __future__ import annotations

import io

import sounddevice as sd
import soundfile as sf

from vinylpi.config.runtime import read_config


def auto_detect_usb_device() -> int | None:
    cfg = read_config()
    needle = str(cfg["audio"].get("device_name_contains") or "").upper()
    debug_log = bool(cfg["debug"].get("logs", False))

    try:
        devices = sd.query_devices()
    except Exception as exc:
        print(f"Could not query audio devices: {exc}")
        return None

    for index, device in enumerate(devices):
        name = str(device.get("name") or "")
        max_inputs = int(device.get("max_input_channels") or 0)
        if max_inputs > 0 and needle in name.upper():
            if debug_log:
                print(f"Auto-detected turntable device: #{index} -> {name}")
            return index

    print(
        "No matching audio input found. Check 'arecord -l' and "
        "config.json -> audio.device_name_contains."
    )
    return None


def record_sample(seconds_override: float | None = None) -> bytes | None:
    cfg = read_config()
    debug_log = bool(cfg["debug"].get("logs", False))
    audio_cfg = cfg["audio"]
    debug_cfg = cfg["debug"]

    sample_rate = int(audio_cfg["sample_rate"])
    seconds = max(0.5, float(seconds_override if seconds_override is not None else audio_cfg["sample_seconds"]))
    channels = max(1, int(audio_cfg["channels"]))
    debug_wav_path = str(debug_cfg.get("wav_path") or "")

    try:
        audio = sd.rec(
            int(seconds * sample_rate),
            samplerate=sample_rate,
            channels=channels,
            dtype="int16",
        )
        sd.wait()
    except Exception as exc:
        print(f"Audio recording failed: {exc}")
        return None

    buffer = io.BytesIO()
    sf.write(buffer, audio, sample_rate, format="WAV")
    wav_bytes = buffer.getvalue()

    if debug_wav_path:
        try:
            sf.write(debug_wav_path, audio, sample_rate, format="WAV")
            if debug_log:
                print(f"Saved WAV file at: {debug_wav_path}")
        except Exception as exc:
            print(f"Could not save debug WAV: {exc}")

    return wav_bytes
