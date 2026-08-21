from __future__ import annotations

import secrets
import threading
import time

from flask import Blueprint, jsonify, redirect, request, url_for

from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    SpotifyError,
    spotify_env_status,
)
from vinylpi.web.services.source import set_mode

spotify_bp = Blueprint("spotify_api", __name__)

_states: dict[str, float] = {}
_state_lock = threading.Lock()
_STATE_TTL_SECONDS = 10 * 60


def _cleanup_states() -> None:
    cutoff = time.time() - _STATE_TTL_SECONDS
    for state, created in list(_states.items()):
        if created < cutoff:
            _states.pop(state, None)


@spotify_bp.get("/api/spotify/status")
def api_spotify_status():
    return jsonify({"ok": True, **spotify_env_status()})


@spotify_bp.get("/api/spotify/auth-url")
def api_spotify_auth_url():
    try:
        client = SpotifyClient()
        redirect_uri = client.redirect_uri or url_for("spotify_api.spotify_callback", _external=True)
        state = secrets.token_urlsafe(24)
        with _state_lock:
            _cleanup_states()
            _states[state] = time.time()
        auth_url = client.build_authorize_url(state=state, redirect_uri=redirect_uri)
        return jsonify({"ok": True, "auth_url": auth_url, "redirect_uri": redirect_uri})
    except SpotifyError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400


@spotify_bp.get("/api/spotify/callback")
def spotify_callback():
    error = request.args.get("error")
    if error:
        return redirect(f"/?spotify=error&reason={error}")

    state = str(request.args.get("state") or "")
    code = str(request.args.get("code") or "")
    with _state_lock:
        _cleanup_states()
        valid_state = bool(state and _states.pop(state, None))
    if not valid_state or not code:
        return redirect("/?spotify=error&reason=invalid_state")

    try:
        client = SpotifyClient()
        redirect_uri = client.redirect_uri or url_for("spotify_api.spotify_callback", _external=True)
        client.exchange_code(code, redirect_uri=redirect_uri)
        try:
            set_mode("spotify")
        except Exception:
            # Authorization itself succeeded. A worker can still be started from
            # the dashboard if an unrelated runtime problem occurred here.
            pass
        return redirect("/?spotify=connected")
    except SpotifyError:
        return redirect("/?spotify=error&reason=authorization_failed")
