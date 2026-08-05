from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from vinylpi.config.config_loader import CONFIG_DEFAULTS, deep_update, load_config
from vinylpi.paths import CONFIG_PATH, get_active_config_path

_LEGACY_CONFIG_PATH = CONFIG_PATH


_CACHE: dict[str, Any] = {"path": None, "mtime": None, "cfg": None, "ts": 0.0}
_CACHE_TTL_SECONDS = 0.5

def _current_config_path() -> Path:
    # Preserve compatibility with tests/tools that monkey-patch CONFIG_PATH.
    if Path(CONFIG_PATH) != Path(_LEGACY_CONFIG_PATH):
        return Path(CONFIG_PATH)
    return get_active_config_path()


def clear_config_cache() -> None:
    _CACHE.update({"path": None, "mtime": None, "cfg": None, "ts": 0.0})


def read_config(force: bool = False) -> Dict[str, Any]:
    path = _current_config_path()
    now = time.time()

    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        mtime = None

    if not force:
        if _CACHE["cfg"] is not None:
            fresh_enough = (now - float(_CACHE["ts"])) < _CACHE_TTL_SECONDS
            same_file = _CACHE["path"] == str(path) and _CACHE["mtime"] == mtime
            if fresh_enough and same_file:
                return deepcopy(_CACHE["cfg"])

    cfg = load_config(path)
    _CACHE["path"] = str(path)
    _CACHE["mtime"] = mtime
    _CACHE["cfg"] = cfg
    _CACHE["ts"] = now
    return deepcopy(cfg)


def write_config(data: Dict[str, Any] | None) -> Dict[str, Any]:
    data = data or {}
    current = read_config(force=True)
    new_cfg = deepcopy(current)

    if isinstance(data, dict):
        deep_update(new_cfg, data)

    path = _current_config_path()
    _atomic_write_json(path, new_cfg)

    _CACHE["path"] = str(path)
    _CACHE["mtime"] = path.stat().st_mtime
    _CACHE["cfg"] = new_cfg
    _CACHE["ts"] = time.time()

    return deepcopy(new_cfg)


def reset_config() -> Dict[str, Any]:
    cfg = deepcopy(CONFIG_DEFAULTS)
    path = _current_config_path()
    _atomic_write_json(path, cfg)

    _CACHE["path"] = str(path)
    _CACHE["mtime"] = path.stat().st_mtime
    _CACHE["cfg"] = cfg
    _CACHE["ts"] = time.time()

    return deepcopy(cfg)


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(json.dumps(obj, indent=4), encoding="utf-8")
    os.replace(tmp, path)


_FALLBACK_PATH_FIELDS = {
    "normal": "image_path",
    "turn": "side_flip_image_path",
}


def normalize_fallback_kind(kind: str | None) -> str:
    value = str(kind or "normal").strip().casefold()
    if value not in _FALLBACK_PATH_FIELDS:
        raise ValueError("invalid fallback image kind")
    return value


def set_fallback_image_path(rel_path: str, *, kind: str = "normal") -> bool:
    selected_kind = normalize_fallback_kind(kind)
    try:
        cfg = read_config()
    except Exception:
        cfg = json.loads(json.dumps(CONFIG_DEFAULTS))

    cfg.setdefault("fallback", {})
    cfg["fallback"][_FALLBACK_PATH_FIELDS[selected_kind]] = rel_path
    write_config(cfg)
    return True


def get_current_fallback_path(*, kind: str = "normal") -> str | None:
    selected_kind = normalize_fallback_kind(kind)
    try:
        cfg = read_config()
        return (cfg.get("fallback") or {}).get(_FALLBACK_PATH_FIELDS[selected_kind]) or None
    except Exception:
        return None
