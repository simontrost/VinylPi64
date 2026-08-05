from __future__ import annotations

from vinylpi.config.runtime import read_config
from vinylpi.paths import get_active_config_path

_last_cfg_signature: tuple[str, float | None] | None = None


def maybe_log_config_reload() -> bool:
    global _last_cfg_signature

    path = get_active_config_path()
    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        mtime = None

    signature = (str(path), mtime)
    if _last_cfg_signature is None:
        _last_cfg_signature = signature
        return False

    if signature != _last_cfg_signature:
        profile_changed = signature[0] != _last_cfg_signature[0]
        _last_cfg_signature = signature
        cfg = read_config(force=True)
        if cfg.get("debug", {}).get("logs"):
            print("Active profile config loaded." if profile_changed else "Config reloaded from disk.")
        return True

    return False
