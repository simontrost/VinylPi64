from __future__ import annotations

from flask import Blueprint, jsonify

from vinylpi.config.runtime import read_config, write_config
from vinylpi.core.discogs_service import (
    DISCOGS_TOKEN_ENV,
    SYNC_MANAGER,
    get_discogs_token,
)
from vinylpi.integrations.discogs_client import DiscogsClient, DiscogsError


discogs_bp = Blueprint("discogs_api", __name__)


def _missing_token_response():
    return jsonify({
        "ok": False,
        "error": (
            f"Set {DISCOGS_TOKEN_ENV}=... in vinylpi.env and restart VinylPi first."
        ),
    }), 400


@discogs_bp.get("/api/discogs/status")
def api_discogs_status():
    return jsonify({"ok": True, **SYNC_MANAGER.status()})


@discogs_bp.post("/api/discogs/connect")
def api_discogs_connect():
    token = get_discogs_token()
    if not token:
        return _missing_token_response()

    try:
        identity = DiscogsClient(token).identity()
    except DiscogsError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    username = str(identity.get("username") or "").strip()
    if not username:
        return jsonify({"ok": False, "error": "Discogs did not return an account name."}), 502

    write_config(
        {
            "discogs": {
                "username": username,
                "enabled": True,
            }
        }
    )
    return jsonify({"ok": True, "username": username})


@discogs_bp.post("/api/discogs/sync")
def api_discogs_sync():
    cfg = read_config()
    if not get_discogs_token(cfg):
        return _missing_token_response()
    if not bool((cfg.get("discogs") or {}).get("enabled", False)):
        write_config({"discogs": {"enabled": True}})

    started = SYNC_MANAGER.start()
    if not started:
        return jsonify({"ok": True, "started": False, "message": "A Discogs sync is already running."})
    return jsonify({"ok": True, "started": True}), 202
