from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any

from vinylpi.paths import (
    CONFIG_PATH,
    DB_PATH,
    DATA_DIR,
    PROFILE_REGISTRY_PATH,
    PROFILES_DIR,
)

_DEFAULT_PROFILE_ID = "default"
_GUEST_STORAGE_KEY = "_guest"
_REGISTRY_VERSION = 1
_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"mtime_ns": None, "registry": None}
_NAME_RE = re.compile(r"\s+")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _now() -> int:
    return int(time.time())


def _timestamp(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return _now()


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=4, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)
    if path == PROFILE_REGISTRY_PATH:
        _CACHE["mtime_ns"] = path.stat().st_mtime_ns
        _CACHE["registry"] = deepcopy(payload)


def _default_registry() -> dict[str, Any]:
    return {
        "version": _REGISTRY_VERSION,
        "active_profile_id": _DEFAULT_PROFILE_ID,
        "profiles": [
            {
                "id": _DEFAULT_PROFILE_ID,
                "name": "Default",
                "created_at": _now(),
                "updated_at": _now(),
            }
        ],
    }


def _normalise_registry(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        payload = {}

    profiles: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in payload.get("profiles") or []:
        if not isinstance(item, dict):
            continue
        profile_id = str(item.get("id") or "").strip()
        name = _normalise_name(item.get("name"), allow_empty=True)
        if not _ID_RE.fullmatch(profile_id) or not name or profile_id in seen or profile_id == _GUEST_STORAGE_KEY:
            continue
        seen.add(profile_id)
        profiles.append(
            {
                "id": profile_id,
                "name": name,
                "created_at": _timestamp(item.get("created_at")),
                "updated_at": _timestamp(item.get("updated_at")),
            }
        )

    if _DEFAULT_PROFILE_ID not in seen:
        profiles.insert(
            0,
            {
                "id": _DEFAULT_PROFILE_ID,
                "name": "Default",
                "created_at": _now(),
                "updated_at": _now(),
            },
        )
        seen.add(_DEFAULT_PROFILE_ID)

    active = payload.get("active_profile_id")
    if active is not None:
        active = str(active)
        if active not in seen:
            active = _DEFAULT_PROFILE_ID

    return {
        "version": _REGISTRY_VERSION,
        "active_profile_id": active,
        "profiles": profiles,
    }


def _normalise_name(value: Any, *, allow_empty: bool = False) -> str:
    name = _NAME_RE.sub(" ", str(value or "").strip())
    if not name and not allow_empty:
        raise ValueError("Profile name is required")
    if len(name) > 40:
        raise ValueError("Profile name must not exceed 40 characters")
    return name


def _read_registry_unlocked() -> tuple[dict[str, Any], bool]:
    try:
        mtime_ns = PROFILE_REGISTRY_PATH.stat().st_mtime_ns
    except FileNotFoundError:
        mtime_ns = None

    if _CACHE["registry"] is not None and _CACHE["mtime_ns"] == mtime_ns:
        return deepcopy(_CACHE["registry"]), False

    try:
        raw = json.loads(PROFILE_REGISTRY_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        raw = _default_registry()

    registry = _normalise_registry(raw)
    needs_write = mtime_ns is None or raw != registry
    _CACHE["mtime_ns"] = mtime_ns
    _CACHE["registry"] = deepcopy(registry)
    return registry, needs_write


def _profile_dir(storage_key: str) -> Path:
    return PROFILES_DIR / storage_key


def _copy_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _copy_database_if_missing(source: Path, destination: Path) -> None:
    if destination.exists() or not source.is_file():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    try:
        with sqlite3.connect(source, timeout=10.0) as source_conn:
            with sqlite3.connect(temporary, timeout=10.0) as target_conn:
                source_conn.backup(target_conn)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def _ensure_default_storage_unlocked(*, import_legacy: bool) -> None:
    directory = _profile_dir(_DEFAULT_PROFILE_ID)
    directory.mkdir(parents=True, exist_ok=True)
    if import_legacy:
        _copy_if_missing(CONFIG_PATH, directory / "config.json")
        _copy_database_if_missing(DB_PATH, directory / "vinylpi.db")


def ensure_profiles_initialized() -> dict[str, Any]:
    with _LOCK:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        registry_existed = PROFILE_REGISTRY_PATH.exists()
        registry, needs_write = _read_registry_unlocked()
        _ensure_default_storage_unlocked(import_legacy=not registry_existed)
        for profile in registry["profiles"]:
            _profile_dir(profile["id"]).mkdir(parents=True, exist_ok=True)
        if needs_write:
            _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return deepcopy(registry)


def _find_profile(registry: dict[str, Any], profile_id: str) -> dict[str, Any] | None:
    return next((item for item in registry["profiles"] if item["id"] == profile_id), None)


def get_active_storage_key() -> str:
    registry = ensure_profiles_initialized()
    return str(registry.get("active_profile_id") or _GUEST_STORAGE_KEY)


def get_active_profile() -> dict[str, Any]:
    registry = ensure_profiles_initialized()
    active_id = registry.get("active_profile_id")
    if active_id is None:
        return {
            "id": None,
            "name": "Guest",
            "is_guest": True,
            "storage_key": _GUEST_STORAGE_KEY,
        }

    profile = _find_profile(registry, str(active_id))
    if profile is None:
        profile = _find_profile(registry, _DEFAULT_PROFILE_ID)
    return {
        **deepcopy(profile or {"id": _DEFAULT_PROFILE_ID, "name": "Default"}),
        "is_guest": False,
        "storage_key": str((profile or {}).get("id") or _DEFAULT_PROFILE_ID),
    }


def list_profiles() -> dict[str, Any]:
    registry = ensure_profiles_initialized()
    active = get_active_profile()
    profiles = []
    for item in registry["profiles"]:
        profiles.append(
            {
                **deepcopy(item),
                "is_active": item["id"] == registry.get("active_profile_id"),
                "is_default": item["id"] == _DEFAULT_PROFILE_ID,
            }
        )
    return {"active_profile": active, "profiles": profiles}


def _active_config_path_unlocked(registry: dict[str, Any]) -> Path:
    storage_key = str(registry.get("active_profile_id") or _GUEST_STORAGE_KEY)
    return _profile_dir(storage_key) / "config.json"


def create_profile(name: str, *, copy_current_settings: bool = True) -> dict[str, Any]:
    clean_name = _normalise_name(name)
    with _LOCK:
        registry = ensure_profiles_initialized()
        if any(item["name"].casefold() == clean_name.casefold() for item in registry["profiles"]):
            raise ValueError("A profile with this name already exists")

        profile_id = uuid.uuid4().hex[:12]
        timestamp = _now()
        profile = {
            "id": profile_id,
            "name": clean_name,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        target_dir = _profile_dir(profile_id)
        target_dir.mkdir(parents=True, exist_ok=False)

        if copy_current_settings:
            source = _active_config_path_unlocked(registry)
            _copy_if_missing(source, target_dir / "config.json")

        registry["profiles"].append(profile)
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {**deepcopy(profile), "is_active": False, "is_default": False}


def activate_profile(profile_id: str) -> dict[str, Any]:
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        _profile_dir(profile_id).mkdir(parents=True, exist_ok=True)
        registry["active_profile_id"] = profile_id
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {
            **deepcopy(profile),
            "is_guest": False,
            "storage_key": profile_id,
        }


def logout_to_guest(*, copy_current_settings: bool = True) -> dict[str, Any]:
    with _LOCK:
        registry = ensure_profiles_initialized()
        guest_dir = _profile_dir(_GUEST_STORAGE_KEY)
        guest_dir.mkdir(parents=True, exist_ok=True)
        guest_config = guest_dir / "config.json"
        if copy_current_settings and not guest_config.exists():
            _copy_if_missing(_active_config_path_unlocked(registry), guest_config)
        registry["active_profile_id"] = None
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return get_active_profile()


def rename_profile(profile_id: str, name: str) -> dict[str, Any]:
    clean_name = _normalise_name(name)
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, str(profile_id))
        if profile is None:
            raise KeyError("Profile not found")
        if any(
            item["id"] != profile["id"] and item["name"].casefold() == clean_name.casefold()
            for item in registry["profiles"]
        ):
            raise ValueError("A profile with this name already exists")
        profile["name"] = clean_name
        profile["updated_at"] = _now()
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return deepcopy(profile)


def delete_profile(profile_id: str) -> None:
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        if profile_id == _DEFAULT_PROFILE_ID:
            raise ValueError("The default profile cannot be deleted")
        if registry.get("active_profile_id") == profile_id:
            raise ValueError("The active profile cannot be deleted")
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        registry["profiles"] = [item for item in registry["profiles"] if item["id"] != profile_id]
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        shutil.rmtree(_profile_dir(profile_id), ignore_errors=True)


def is_default_profile_active() -> bool:
    return ensure_profiles_initialized().get("active_profile_id") == _DEFAULT_PROFILE_ID
