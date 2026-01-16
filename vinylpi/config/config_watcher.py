from vinylpi.paths import CONFIG_PATH
from vinylpi.web.services.config import read_config

_last_cfg_mtime: float | None = None

def maybe_log_config_reload() -> bool:
    global _last_cfg_mtime

    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        return False

    if _last_cfg_mtime is None:
        _last_cfg_mtime = mtime
        return False

    if mtime != _last_cfg_mtime:
        _last_cfg_mtime = mtime
        cfg = read_config(force=True)
        if cfg.get("debug", {}).get("logs"):
            print("Config reloaded from disk.")
        return True

    return False
