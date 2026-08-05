from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

from flask import Blueprint, jsonify, request, send_file

from vinylpi.config.runtime import clear_config_cache, read_config
from vinylpi.core.discogs_service import SYNC_MANAGER
from vinylpi.core.storage import initialize_storage
from vinylpi.profiles import (
    ProfileAuthenticationError,
    ProfilePasswordNotConfiguredError,
    activate_profile,
    create_profile,
    delete_profile,
    get_profile_avatar_path,
    initialize_profile_password,
    list_profiles,
    logout_to_guest,
    prepare_profile_avatar,
    update_profile,
)
from vinylpi.web.services.recognizer import is_running, start, stop

profiles_bp = Blueprint("profiles_api", __name__)
_PROFILE_SWITCH_LOCK = threading.Lock()


def _restart_recognizer_after_profile_change(was_running: bool) -> None:
    clear_config_cache()
    initialize_storage()
    SYNC_MANAGER.reset_runtime()
    if was_running:
        debug_log = bool((read_config().get("debug") or {}).get("logs", False))
        start(silence_output=not debug_log)


def _switch_profile(action):
    with _PROFILE_SWITCH_LOCK:
        if SYNC_MANAGER.is_syncing():
            raise RuntimeError("Wait for the current Discogs sync to finish before switching profiles")
        was_running = is_running()
        if was_running:
            stop()
        try:
            result = action()
        except Exception:
            _restart_recognizer_after_profile_change(was_running)
            raise
        _restart_recognizer_after_profile_change(was_running)
        return result, was_running


def _request_data() -> Mapping[str, Any]:
    if request.is_json:
        return request.get_json(silent=True) or {}
    return request.form


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _avatar_from_request() -> bytes | None:
    upload = request.files.get("avatar")
    if upload is None or not upload.filename:
        return None
    return prepare_profile_avatar(upload)


@profiles_bp.get("/api/profiles")
def api_profiles():
    return jsonify({"ok": True, **list_profiles()})


@profiles_bp.post("/api/profiles")
def api_create_profile():
    data = _request_data()
    activated = _as_bool(data.get("activate"), True)
    password = str(data.get("password") or "")
    password_confirmation = data.get("password_confirmation")
    if password_confirmation is not None and password != str(password_confirmation):
        return jsonify({"ok": False, "error": "Passwords do not match"}), 400
    if activated and SYNC_MANAGER.is_syncing():
        return jsonify({"ok": False, "error": "Wait for the current Discogs sync to finish before switching profiles"}), 409

    try:
        avatar_png = _avatar_from_request()
        profile = create_profile(
            str(data.get("name") or ""),
            password,
            copy_current_settings=_as_bool(data.get("copy_current_settings"), True),
            avatar_png=avatar_png,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    recognizer_restarted = False
    if activated:
        try:
            profile, recognizer_restarted = _switch_profile(
                lambda: activate_profile(profile["id"], password)
            )
        except (RuntimeError, ProfilePasswordNotConfiguredError) as exc:
            try:
                delete_profile(profile["id"])
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(exc)}), 409
        except ProfileAuthenticationError as exc:
            try:
                delete_profile(profile["id"])
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(exc)}), 401

    return jsonify(
        {
            "ok": True,
            "profile": profile,
            "activated": activated,
            "recognizer_restarted": recognizer_restarted,
        }
    ), 201


@profiles_bp.post("/api/profiles/<profile_id>/activate")
def api_activate_profile(profile_id: str):
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    try:
        profile, restarted = _switch_profile(lambda: activate_profile(profile_id, password))
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except ProfileAuthenticationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except ProfilePasswordNotConfiguredError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "profile": profile, "recognizer_restarted": restarted})


@profiles_bp.post("/api/profiles/<profile_id>/initialize-password")
def api_initialize_profile_password(profile_id: str):
    data = request.get_json(silent=True) or {}
    password = str(data.get("password") or "")
    confirmation = data.get("password_confirmation")
    if confirmation is not None and password != str(confirmation):
        return jsonify({"ok": False, "error": "Passwords do not match"}), 400
    try:
        profile, restarted = _switch_profile(
            lambda: initialize_profile_password(profile_id, password)
        )
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "profile": profile, "recognizer_restarted": restarted})


@profiles_bp.post("/api/profiles/logout")
def api_logout_profile():
    try:
        profile, restarted = _switch_profile(logout_to_guest)
    except ProfilePasswordNotConfiguredError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "profile": profile, "recognizer_restarted": restarted})


@profiles_bp.patch("/api/profiles/<profile_id>")
def api_update_profile(profile_id: str):
    data = _request_data()
    name = str(data.get("name")) if "name" in data else None
    new_password_raw = data.get("new_password")
    new_password = str(new_password_raw) if new_password_raw not in (None, "") else None
    confirmation = data.get("new_password_confirmation")
    if new_password is not None and confirmation is not None and new_password != str(confirmation):
        return jsonify({"ok": False, "error": "New passwords do not match"}), 400

    try:
        avatar_png = _avatar_from_request()
        profile = update_profile(
            profile_id,
            name=name,
            current_password=str(data.get("current_password") or ""),
            new_password=new_password,
            avatar_png=avatar_png,
            remove_avatar=_as_bool(data.get("remove_avatar"), False),
        )
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except ProfileAuthenticationError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 401
    except (ProfilePasswordNotConfiguredError, ValueError) as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "profile": profile})


@profiles_bp.get("/api/profiles/<profile_id>/avatar")
def api_profile_avatar(profile_id: str):
    try:
        path = get_profile_avatar_path(profile_id)
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except FileNotFoundError:
        return jsonify({"ok": False, "error": "Profile image not found"}), 404
    return send_file(path, mimetype="image/png", conditional=True, max_age=86400)


@profiles_bp.delete("/api/profiles/<profile_id>")
def api_delete_profile(profile_id: str):
    try:
        delete_profile(profile_id)
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})
