from __future__ import annotations

import secrets
import threading
import time

from flask import Blueprint, jsonify, redirect, request, url_for

from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    clear_spotify_account,
    spotify_env_status,
)
from vinylpi.paths import get_profile_db_path
from vinylpi.profiles import get_active_profile
from vinylpi.web.services.source import get_mode, set_mode

spotify_bp = Blueprint("spotify_api", __name__)

_states: dict[str, dict] = {}
_state_lock = threading.Lock()
_STATE_TTL_SECONDS = 10 * 60


def _cleanup_states() -> None:
    cutoff = time.time() - _STATE_TTL_SECONDS
    for state, payload in list(_states.items()):
        if float(payload.get("created_at") or 0) < cutoff:
            _states.pop(state, None)


def _return_target(value: str | None) -> tuple[str, bool]:
    if str(value or "").strip().lower() == "settings":
        return "/settings.html", False
    return "/", True


@spotify_bp.get("/api/spotify/status")
def api_spotify_status():
    return jsonify({"ok": True, **spotify_env_status()})


@spotify_bp.get("/api/spotify/auth-url")
def api_spotify_auth_url():
    try:
        profile = get_active_profile()
        storage_key = str(profile.get("storage_key") or "").strip()
        return_path, auto_enable = _return_target(request.args.get("return_to"))
        force_dialog = str(request.args.get("force") or "").strip().lower() in {"1", "true", "yes"}

        client = SpotifyClient(profile_db_path=get_profile_db_path(storage_key))
        redirect_uri = client.redirect_uri or url_for("spotify_api.spotify_callback", _external=True)
        state = secrets.token_urlsafe(24)
        with _state_lock:
            _cleanup_states()
            _states[state] = {
                "created_at": time.time(),
                "storage_key": storage_key,
                "return_path": return_path,
                "auto_enable": auto_enable,
            }
        auth_url = client.build_authorize_url(
            state=state,
            redirect_uri=redirect_uri,
            show_dialog=force_dialog,
        )
        return jsonify({"ok": True, "auth_url": auth_url, "redirect_uri": redirect_uri})
    except SpotifyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@spotify_bp.post("/api/spotify/disconnect")
def api_spotify_disconnect():
    profile = get_active_profile()
    storage_key = str(profile.get("storage_key") or "").strip()
    clear_spotify_account(get_profile_db_path(storage_key))
    if get_mode() == "spotify":
        set_mode("off")
    return jsonify({"ok": True, **spotify_env_status()})


@spotify_bp.get("/api/spotify/callback")
def spotify_callback():
    state = str(request.args.get("state") or "")
    with _state_lock:
        _cleanup_states()
        state_payload = _states.pop(state, None) if state else None

    return_path = str((state_payload or {}).get("return_path") or "/")
    error = request.args.get("error")
    if error:
        return redirect(f"{return_path}?spotify=error&reason={error}")

    code = str(request.args.get("code") or "")
    if not state_payload or not code:
        return redirect(f"{return_path}?spotify=error&reason=invalid_state")

    try:
        storage_key = str(state_payload.get("storage_key") or "").strip()
        client = SpotifyClient(profile_db_path=get_profile_db_path(storage_key))
        redirect_uri = client.redirect_uri or url_for("spotify_api.spotify_callback", _external=True)
        client.exchange_code(code, redirect_uri=redirect_uri)

        active_storage = str(get_active_profile().get("storage_key") or "").strip()
        if bool(state_payload.get("auto_enable")) and active_storage == storage_key:
            try:
                set_mode("spotify")
            except Exception:
                pass
        return redirect(f"{return_path}?spotify=connected")
    except SpotifyError:
        return redirect(f"{return_path}?spotify=error&reason=authorization_failed")
