from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

from vinylpi.paths import CONFIG_PATH
from vinylpi.config.config_loader import CONFIG_DEFAULTS, deep_update, load_config


_CACHE: dict[str, Any] = {"mtime": None, "cfg": None, "ts": 0.0}
_CACHE_TTL_SECONDS = 0.5

def read_config(force: bool = False) -> Dict[str, Any]:
    path = CONFIG_PATH
    now = time.time()

    try:
        mtime = path.stat().st_mtime
    except FileNotFoundError:
        mtime = None

    if not force:
        if _CACHE["cfg"] is not None:
            fresh_enough = (now - float(_CACHE["ts"])) < _CACHE_TTL_SECONDS
            same_file = _CACHE["mtime"] == mtime
            if fresh_enough and same_file:
                return deepcopy(_CACHE["cfg"])

    cfg = load_config(path)
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

    _atomic_write_json(CONFIG_PATH, new_cfg)

    _CACHE["mtime"] = CONFIG_PATH.stat().st_mtime
    _CACHE["cfg"] = new_cfg
    _CACHE["ts"] = time.time()

    return deepcopy(new_cfg)


def reset_config() -> Dict[str, Any]:
    cfg = deepcopy(CONFIG_DEFAULTS)
    _atomic_write_json(CONFIG_PATH, cfg)

    _CACHE["mtime"] = CONFIG_PATH.stat().st_mtime
    _CACHE["cfg"] = cfg
    _CACHE["ts"] = time.time()

    return deepcopy(cfg)


def _atomic_write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")

    tmp.write_text(json.dumps(obj, indent=4), encoding="utf-8")
    os.replace(tmp, path)


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
