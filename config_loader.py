import json
from copy import deepcopy

CONFIG_DEFAULTS = {
    "audio": {
        "device_name_contains": "USB AUDIO",
        "sample_seconds": 10,
        "sample_rate": 44100,
        "channels": 1
    },
    "image": {
        "canvas_size": 64,
        "top_margin": 1,
        "bottom_margin": 1,
        "cover_size": 46,
        "margin_image_text": 3,
        "line_height": 5,
        "line_spacing_margin": 3,
        "font_path": "DejaVuSans.ttf",
        "font_size":5,
        "use_dynamic_font": True,
        "background_color": [255, 255, 255],
        "text_color_mode": "dominant",
        "text_color_manual": [0, 0, 0],
        "uppercase": True,
        "preview_scale": 8
    },
    "fallback": {
        "enabled": True,
        "image_path": "assets/fallback.png"
    },

    "debug": {
        "logs" : False,
        "pixoo_frame_path": "",
        "preview_path": "",
        "output_wav": ""

    },
    "shazam": {
        "timeout_seconds": 15
    }
}


def deep_update(base: dict, updates: dict) -> dict:
    for k, v in updates.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_update(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path: str = "config.json") -> dict:
    cfg = deepcopy(CONFIG_DEFAULTS)
    try:
        with open(path, "r", encoding="utf-8") as f:
            user_cfg = json.load(f)
        deep_update(cfg, user_cfg)
        print(f"Config found at: {path}")
    except FileNotFoundError:
        print("No config was found, using defaults. Try creating a file with the name config.json")
    return cfg

CONFIG = load_config()
