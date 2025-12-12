import json
from typing import Any, Dict
from vinylpi.config.config_loader import CONFIG_DEFAULTS, reload_config
from vinylpi.paths import CONFIG_PATH

def read_config() -> Dict[str, Any]:
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def write_config(data: Dict[str, Any]) -> None:
    CONFIG_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")
    try:
        reload_config()
    except Exception:
        pass

def reset_config() -> None:
    CONFIG_PATH.write_text(json.dumps(CONFIG_DEFAULTS, indent=4), encoding="utf-8")
    try:
        reload_config()
    except Exception:
        pass

def set_fallback_image_path(rel_path: str) -> bool:
    try:
        cfg = read_config()
    except Exception:
        cfg = json.loads(json.dumps(CONFIG_DEFAULTS))

    cfg.setdefault("fallback", {})
    cfg["fallback"]["image_path"] = rel_path
    write_config(cfg)
    return True

def get_current_fallback_path() -> str | None:
    try:
        cfg = read_config()
        return (cfg.get("fallback") or {}).get("image_path") or None
    except Exception:
        return None
