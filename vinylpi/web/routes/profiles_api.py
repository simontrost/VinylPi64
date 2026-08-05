from __future__ import annotations

import threading

from flask import Blueprint, jsonify, request

from vinylpi.config.runtime import clear_config_cache, read_config
from vinylpi.core.discogs_service import SYNC_MANAGER
from vinylpi.core.storage import initialize_storage
from vinylpi.profiles import (
    activate_profile,
    create_profile,
    delete_profile,
    list_profiles,
    logout_to_guest,
    rename_profile,
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


@profiles_bp.get("/api/profiles")
def api_profiles():
    return jsonify({"ok": True, **list_profiles()})


@profiles_bp.post("/api/profiles")
def api_create_profile():
    data = request.get_json(silent=True) or {}
    activated = bool(data.get("activate", True))
    if activated and SYNC_MANAGER.is_syncing():
        return jsonify({"ok": False, "error": "Wait for the current Discogs sync to finish before switching profiles"}), 409
    try:
        profile = create_profile(
            str(data.get("name") or ""),
            copy_current_settings=bool(data.get("copy_current_settings", True)),
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    recognizer_restarted = False
    if activated:
        try:
            profile, recognizer_restarted = _switch_profile(lambda: activate_profile(profile["id"]))
        except RuntimeError as exc:
            try:
                delete_profile(profile["id"])
            except Exception:
                pass
            return jsonify({"ok": False, "error": str(exc)}), 409

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
    try:
        profile, restarted = _switch_profile(lambda: activate_profile(profile_id))
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "profile": profile, "recognizer_restarted": restarted})


@profiles_bp.post("/api/profiles/logout")
def api_logout_profile():
    try:
        profile, restarted = _switch_profile(logout_to_guest)
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 409
    return jsonify({"ok": True, "profile": profile, "recognizer_restarted": restarted})


@profiles_bp.patch("/api/profiles/<profile_id>")
def api_rename_profile(profile_id: str):
    data = request.get_json(silent=True) or {}
    try:
        profile = rename_profile(profile_id, str(data.get("name") or ""))
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "profile": profile})


@profiles_bp.delete("/api/profiles/<profile_id>")
def api_delete_profile(profile_id: str):
    try:
        delete_profile(profile_id)
    except KeyError:
        return jsonify({"ok": False, "error": "Profile not found"}), 404
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True})
