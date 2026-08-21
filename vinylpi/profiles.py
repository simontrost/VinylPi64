from __future__ import annotations

import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import threading
import time
import uuid
from copy import deepcopy
from contextvars import ContextVar, Token
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError
from vinylpi.paths import (
    CONFIG_PATH,
    DB_PATH,
    DATA_DIR,
    PROFILE_REGISTRY_PATH,
    PROFILES_DIR,
)

_DEFAULT_PROFILE_ID = "default"
_GUEST_STORAGE_KEY = "_guest"
_REGISTRY_VERSION = 2
_LOCK = threading.RLock()
_CACHE: dict[str, Any] = {"mtime_ns": None, "registry": None}
_NAME_RE = re.compile(r"\s+")
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_PASSWORD_HASH_ITERATIONS = 260_000
_PASSWORD_HASH_PREFIX = "pbkdf2_sha256"
_AVATAR_FILENAME = "avatar.png"
_MAX_AVATAR_BYTES = 5 * 1024 * 1024
_AVATAR_SIZE = 256
_ALLOWED_AVATAR_FORMATS = {"JPEG", "PNG", "WEBP"}

# Web requests can be scoped to a browser-local profile without changing the
# single global playback owner. Worker processes run without this override and
# therefore keep using the registry's ``active_profile_id`` as the runtime
# profile for recognition/statistics.
_PROFILE_STORAGE_OVERRIDE: ContextVar[str | None] = ContextVar(
    "vinylpi_profile_storage_override",
    default=None,
)


class ProfileAuthenticationError(PermissionError):
    pass


class ProfilePasswordNotConfiguredError(ValueError):
    pass


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
    timestamp = _now()
    return {
        "version": _REGISTRY_VERSION,
        "active_profile_id": _DEFAULT_PROFILE_ID,
        "profiles": [
            {
                "id": _DEFAULT_PROFILE_ID,
                "name": "Default",
                "password_hash": "",
                "avatar_version": None,
                "created_at": timestamp,
                "updated_at": timestamp,
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
        password_hash = item.get("password_hash")
        if not isinstance(password_hash, str):
            password_hash = ""
        avatar_version = item.get("avatar_version")
        try:
            avatar_version = int(avatar_version) if avatar_version is not None else None
        except (TypeError, ValueError):
            avatar_version = None
        profiles.append(
            {
                "id": profile_id,
                "name": name,
                "password_hash": password_hash,
                "avatar_version": avatar_version,
                "created_at": _timestamp(item.get("created_at")),
                "updated_at": _timestamp(item.get("updated_at")),
            }
        )

    if _DEFAULT_PROFILE_ID not in seen:
        timestamp = _now()
        profiles.insert(
            0,
            {
                "id": _DEFAULT_PROFILE_ID,
                "name": "Default",
                "password_hash": "",
                "avatar_version": None,
                "created_at": timestamp,
                "updated_at": timestamp,
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


def _normalise_password(value: Any, *, field_name: str = "Password") -> str:
    password = str(value or "")
    if len(password) < 4:
        raise ValueError(f"{field_name} must contain at least 4 characters")
    if len(password) > 128:
        raise ValueError(f"{field_name} must not exceed 128 characters")
    return password


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PASSWORD_HASH_ITERATIONS,
    )
    salt_b64 = base64.urlsafe_b64encode(salt).decode("ascii").rstrip("=")
    digest_b64 = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return f"{_PASSWORD_HASH_PREFIX}${_PASSWORD_HASH_ITERATIONS}${salt_b64}${digest_b64}"


def _decode_b64(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


def _check_password(stored_hash: str, password: str) -> bool:
    try:
        prefix, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
        if prefix != _PASSWORD_HASH_PREFIX:
            return False
        iterations = int(iterations_raw)
        if iterations < 100_000 or iterations > 2_000_000:
            return False
        salt = _decode_b64(salt_raw)
        expected = _decode_b64(digest_raw)
    except (TypeError, ValueError, base64.binascii.Error):
        return False

    actual = hashlib.pbkdf2_hmac(
        "sha256",
        str(password or "").encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(actual, expected)


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


def _avatar_path(profile_id: str) -> Path:
    return _profile_dir(profile_id) / _AVATAR_FILENAME


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


def _public_profile(profile: dict[str, Any], *, active_id: str | None = None) -> dict[str, Any]:
    profile_id = str(profile["id"])
    avatar_exists = _avatar_path(profile_id).is_file()
    avatar_version = profile.get("avatar_version")
    avatar_url = None
    if avatar_exists:
        suffix = f"?v={avatar_version}" if avatar_version is not None else ""
        avatar_url = f"/api/profiles/{profile_id}/avatar{suffix}"
    return {
        "id": profile_id,
        "name": str(profile["name"]),
        "created_at": _timestamp(profile.get("created_at")),
        "updated_at": _timestamp(profile.get("updated_at")),
        "is_active": profile_id == active_id,
        "is_default": profile_id == _DEFAULT_PROFILE_ID,
        "password_configured": bool(profile.get("password_hash")),
        "avatar_url": avatar_url,
    }


def set_profile_storage_override(storage_key: str | None) -> Token:
    key = str(storage_key or _GUEST_STORAGE_KEY).strip() or _GUEST_STORAGE_KEY
    return _PROFILE_STORAGE_OVERRIDE.set(key)


def reset_profile_storage_override(token: Token) -> None:
    _PROFILE_STORAGE_OVERRIDE.reset(token)


def restore_profile_storage_override(storage_key: str | None) -> None:
    """Restore an exact override value without relying on a ContextVar token.

    Flask streaming responses may finish in a copied Python context. A token
    created during ``before_request`` cannot be reset from that different
    context and raises ``ValueError``. Setting the previous value directly is
    safe for request teardown and also preserves ``None`` (meaning: use the
    global runtime/playback profile).
    """
    _PROFILE_STORAGE_OVERRIDE.set(storage_key)


def get_profile_storage_override() -> str | None:
    return _PROFILE_STORAGE_OVERRIDE.get()


def profile_exists(profile_id: str | None) -> bool:
    profile_id = str(profile_id or "").strip()
    if not profile_id:
        return False
    registry = ensure_profiles_initialized()
    return _find_profile(registry, profile_id) is not None


def get_runtime_storage_key() -> str:
    registry = ensure_profiles_initialized()
    return str(registry.get("active_profile_id") or _GUEST_STORAGE_KEY)


def set_runtime_profile(profile_id: str | None) -> dict[str, Any]:
    """Select the one profile that owns the physical recognition pipeline."""
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        if profile_id:
            profile = _find_profile(registry, profile_id)
            if profile is None:
                raise KeyError("Profile not found")
            _profile_dir(profile_id).mkdir(parents=True, exist_ok=True)
            registry["active_profile_id"] = profile_id
            _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
            return {
                **_public_profile(profile, active_id=profile_id),
                "is_guest": False,
                "storage_key": profile_id,
            }

        registry["active_profile_id"] = None
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {
            "id": None,
            "name": "Guest",
            "is_guest": True,
            "storage_key": _GUEST_STORAGE_KEY,
            "password_configured": False,
            "avatar_url": None,
        }


def get_runtime_profile() -> dict[str, Any]:
    registry = ensure_profiles_initialized()
    runtime_id = registry.get("active_profile_id")
    if runtime_id is None:
        return {
            "id": None,
            "name": "Guest",
            "is_guest": True,
            "storage_key": _GUEST_STORAGE_KEY,
            "password_configured": False,
            "avatar_url": None,
        }
    profile = _find_profile(registry, str(runtime_id))
    if profile is None:
        return {
            "id": None,
            "name": "Guest",
            "is_guest": True,
            "storage_key": _GUEST_STORAGE_KEY,
            "password_configured": False,
            "avatar_url": None,
        }
    return {
        **_public_profile(profile, active_id=str(runtime_id)),
        "is_guest": False,
        "storage_key": str(profile["id"]),
    }


def get_active_storage_key() -> str:
    override = get_profile_storage_override()
    if override is not None:
        return override
    registry = ensure_profiles_initialized()
    return str(registry.get("active_profile_id") or _GUEST_STORAGE_KEY)


def get_active_profile() -> dict[str, Any]:
    registry = ensure_profiles_initialized()
    override = get_profile_storage_override()
    active_id = override if override is not None else registry.get("active_profile_id")
    if active_id in (None, _GUEST_STORAGE_KEY):
        return {
            "id": None,
            "name": "Guest",
            "is_guest": True,
            "storage_key": _GUEST_STORAGE_KEY,
            "password_configured": False,
            "avatar_url": None,
        }

    profile = _find_profile(registry, str(active_id))
    if profile is None:
        profile = _find_profile(registry, _DEFAULT_PROFILE_ID)
    public = _public_profile(profile or {"id": _DEFAULT_PROFILE_ID, "name": "Default"}, active_id=str(active_id))
    return {
        **public,
        "is_guest": False,
        "storage_key": str((profile or {}).get("id") or _DEFAULT_PROFILE_ID),
    }


def list_profiles() -> dict[str, Any]:
    registry = ensure_profiles_initialized()
    override = get_profile_storage_override()
    active_id = override if override is not None else registry.get("active_profile_id")
    if active_id == _GUEST_STORAGE_KEY:
        active_id = None
    profiles = [_public_profile(item, active_id=active_id) for item in registry["profiles"]]
    return {"active_profile": get_active_profile(), "profiles": profiles}


def _active_config_path_unlocked(registry: dict[str, Any]) -> Path:
    storage_key = get_active_storage_key()
    return _profile_dir(storage_key) / "config.json"


def prepare_profile_avatar(file_storage: Any) -> bytes:
    if file_storage is None:
        raise ValueError("Profile image is missing")

    stream = getattr(file_storage, "stream", file_storage)
    if not hasattr(stream, "read"):
        raise ValueError("Invalid profile image")

    try:
        stream.seek(0)
    except Exception:
        pass
    raw = stream.read(_MAX_AVATAR_BYTES + 1)
    if not raw:
        raise ValueError("Profile image is empty")
    if len(raw) > _MAX_AVATAR_BYTES:
        raise ValueError("Profile image must not exceed 5 MB")

    try:
        with Image.open(io.BytesIO(raw)) as source:
            if (source.format or "").upper() not in _ALLOWED_AVATAR_FORMATS:
                raise ValueError("Profile image must be PNG, JPG or WEBP")
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Profile image is invalid") from exc

    image = ImageOps.fit(
        image,
        (_AVATAR_SIZE, _AVATAR_SIZE),
        method=Image.Resampling.LANCZOS,
        centering=(0.5, 0.5),
    )
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=True)
    return output.getvalue()


def _write_avatar_unlocked(profile_id: str, avatar_png: bytes) -> int:
    directory = _profile_dir(profile_id)
    directory.mkdir(parents=True, exist_ok=True)
    target = _avatar_path(profile_id)
    temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_bytes(avatar_png)
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return time.time_ns()


def create_profile(
    name: str,
    password: str,
    *,
    copy_current_settings: bool = True,
    avatar_png: bytes | None = None,
) -> dict[str, Any]:
    clean_name = _normalise_name(name)
    clean_password = _normalise_password(password)
    with _LOCK:
        registry = ensure_profiles_initialized()
        if any(item["name"].casefold() == clean_name.casefold() for item in registry["profiles"]):
            raise ValueError("A profile with this name already exists")

        profile_id = uuid.uuid4().hex[:12]
        timestamp = _now()
        profile = {
            "id": profile_id,
            "name": clean_name,
            "password_hash": _hash_password(clean_password),
            "avatar_version": None,
            "created_at": timestamp,
            "updated_at": timestamp,
        }
        target_dir = _profile_dir(profile_id)
        target_dir.mkdir(parents=True, exist_ok=False)

        try:
            if copy_current_settings:
                source = _active_config_path_unlocked(registry)
                _copy_if_missing(source, target_dir / "config.json")
            if avatar_png is not None:
                profile["avatar_version"] = _write_avatar_unlocked(profile_id, avatar_png)
            registry["profiles"].append(profile)
            _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        except Exception:
            shutil.rmtree(target_dir, ignore_errors=True)
            raise

        return _public_profile(profile, active_id=registry.get("active_profile_id"))


def activate_profile(profile_id: str, password: str) -> dict[str, Any]:
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        password_hash = str(profile.get("password_hash") or "")
        if not password_hash:
            raise ProfilePasswordNotConfiguredError(
                "This profile has no password yet. Set one while the profile is active before signing out."
            )
        if not _check_password(password_hash, str(password or "")):
            raise ProfileAuthenticationError("Incorrect password")
        _profile_dir(profile_id).mkdir(parents=True, exist_ok=True)
        registry["active_profile_id"] = profile_id
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {
            **_public_profile(profile, active_id=profile_id),
            "is_guest": False,
            "storage_key": profile_id,
        }


def authenticate_profile(profile_id: str, password: str) -> dict[str, Any]:
    """Authenticate a browser session without claiming the playback runtime."""
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        password_hash = str(profile.get("password_hash") or "")
        if not password_hash:
            raise ProfilePasswordNotConfiguredError(
                "This profile has no password yet. Set one before signing in."
            )
        if not _check_password(password_hash, str(password or "")):
            raise ProfileAuthenticationError("Incorrect password")
        _profile_dir(profile_id).mkdir(parents=True, exist_ok=True)
        return {
            **_public_profile(profile, active_id=profile_id),
            "is_guest": False,
            "storage_key": profile_id,
        }


def initialize_profile_password(profile_id: str, password: str) -> dict[str, Any]:
    profile_id = str(profile_id or "").strip()
    clean_password = _normalise_password(password)
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        if profile.get("password_hash"):
            raise ValueError("This profile already has a password")
        profile["password_hash"] = _hash_password(clean_password)
        profile["updated_at"] = _now()
        _profile_dir(profile_id).mkdir(parents=True, exist_ok=True)
        registry["active_profile_id"] = profile_id
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {
            **_public_profile(profile, active_id=profile_id),
            "is_guest": False,
            "storage_key": profile_id,
        }


def initialize_profile_password_for_session(profile_id: str, password: str) -> dict[str, Any]:
    """Set a legacy profile password and return it without changing playback owner."""
    profile_id = str(profile_id or "").strip()
    clean_password = _normalise_password(password)
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        if profile.get("password_hash"):
            raise ValueError("This profile already has a password")
        profile["password_hash"] = _hash_password(clean_password)
        profile["updated_at"] = _now()
        _profile_dir(profile_id).mkdir(parents=True, exist_ok=True)
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {
            **_public_profile(profile, active_id=profile_id),
            "is_guest": False,
            "storage_key": profile_id,
        }


def logout_to_guest(*, copy_current_settings: bool = True) -> dict[str, Any]:
    with _LOCK:
        registry = ensure_profiles_initialized()
        active_id = registry.get("active_profile_id")
        if active_id is not None:
            profile = _find_profile(registry, str(active_id))
            if profile is not None and not profile.get("password_hash"):
                raise ProfilePasswordNotConfiguredError(
                    "Set a password for the active profile before signing out."
                )
        guest_dir = _profile_dir(_GUEST_STORAGE_KEY)
        guest_dir.mkdir(parents=True, exist_ok=True)
        guest_config = guest_dir / "config.json"
        if copy_current_settings and not guest_config.exists():
            _copy_if_missing(_active_config_path_unlocked(registry), guest_config)
        registry["active_profile_id"] = None
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return get_active_profile()


def update_profile(
    profile_id: str,
    *,
    name: str | None = None,
    current_password: str = "",
    new_password: str | None = None,
    avatar_png: bytes | None = None,
    remove_avatar: bool = False,
) -> dict[str, Any]:
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        profile = _find_profile(registry, profile_id)
        if profile is None:
            raise KeyError("Profile not found")
        if get_active_storage_key() != profile_id:
            raise ProfileAuthenticationError("Log in to this profile before editing it")

        existing_hash = str(profile.get("password_hash") or "")
        if existing_hash:
            if not _check_password(existing_hash, str(current_password or "")):
                raise ProfileAuthenticationError("Current password is incorrect")
        elif new_password is None:
            raise ProfilePasswordNotConfiguredError("Set a password to finish configuring this profile")

        if name is not None:
            clean_name = _normalise_name(name)
            if any(
                item["id"] != profile_id and item["name"].casefold() == clean_name.casefold()
                for item in registry["profiles"]
            ):
                raise ValueError("A profile with this name already exists")
            profile["name"] = clean_name

        if new_password is not None:
            clean_password = _normalise_password(new_password, field_name="New password")
            profile["password_hash"] = _hash_password(clean_password)

        if avatar_png is not None:
            profile["avatar_version"] = _write_avatar_unlocked(profile_id, avatar_png)
        elif remove_avatar:
            _avatar_path(profile_id).unlink(missing_ok=True)
            profile["avatar_version"] = None

        profile["updated_at"] = _now()
        _atomic_write_json(PROFILE_REGISTRY_PATH, registry)
        return {
            **_public_profile(profile, active_id=profile_id),
            "is_guest": False,
            "storage_key": profile_id,
        }


def get_profile_avatar_path(profile_id: str) -> Path:
    profile_id = str(profile_id or "").strip()
    with _LOCK:
        registry = ensure_profiles_initialized()
        if _find_profile(registry, profile_id) is None:
            raise KeyError("Profile not found")
        path = _avatar_path(profile_id)
        if not path.is_file():
            raise FileNotFoundError("Profile image not found")
        return path


def rename_profile(profile_id: str, name: str, *, current_password: str = "") -> dict[str, Any]:
    return update_profile(profile_id, name=name, current_password=current_password)


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
    return get_active_storage_key() == _DEFAULT_PROFILE_ID
