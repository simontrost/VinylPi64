import json
from copy import deepcopy
from pathlib import Path
from vinylpi.paths import CONFIG_PATH

CONFIG_DEFAULTS = {
    "audio": {
        "device_name_contains": "USB AUDIO",
        "sample_seconds": 4,
        "sample_rate": 44100,
        "channels": 1
    },
    "image": {
        "canvas_size": 64,
        "top_margin": 1,
        "cover_size": 46,
        "margin_image_text": 3,
        "line_spacing_margin": 3,
        "font_path": "assets/fonts/rasbpixel.ttf",
        "font_size": 5,
        "use_dynamic_bg": True,
        "manual_bg_color": [0, 0, 0],
        "use_dynamic_text_color": True,
        "text_color": [255, 255, 255],
        "uppercase": True,
        "preview_scale": 8,
        "marquee_speed": 20,
        "sleep_seconds": 0.01
    },
    "divoom": {
        "ip": "",
        "device_name": "",
        "device_id": 0,
        "device_mac": "",
        "timeout": 2.0,
        "auto_reset_gif_id": False,
        "discovery": {
            "enabled": True,
            "subnet_prefix": "192.168.2.",
            "ip_range_start": 100,
            "ip_range_end": 199
        }
    },
    "debug": {
        "logs": True,
        "pixoo_frame_path": "",
        "preview_path": "",
        "wav_path": ""
    },
    "fallback": {
        "enabled": True,
        "image_path": "assets/fallback/fallback.png",
        "allowed_failures": 3
    },
    "behavior": {
        "loop_delay_seconds": 1,
        "auto_sleep": 30
    },
}

def deep_update(base: dict, updates: dict) -> dict:
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base

def load_config(path: Path | str | None = None) -> dict:
    path = Path(path) if path is not None else CONFIG_PATH
    cfg = deepcopy(CONFIG_DEFAULTS)

    try:
        user_cfg = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(user_cfg, dict):
            deep_update(cfg, user_cfg)
    except FileNotFoundError:
        pass
    except Exception:
        pass

    return cfg