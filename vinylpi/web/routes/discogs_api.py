from __future__ import annotations

from flask import Blueprint, jsonify, request

from vinylpi.config.runtime import read_config, write_config
from vinylpi.core.discogs_service import SYNC_MANAGER, get_discogs_token
from vinylpi.integrations.discogs_client import DiscogsClient, DiscogsError


discogs_bp = Blueprint("discogs_api", __name__)


@discogs_bp.get("/api/discogs/status")
def api_discogs_status():
    return jsonify({"ok": True, **SYNC_MANAGER.status()})


@discogs_bp.post("/api/discogs/connect")
def api_discogs_connect():
    data = request.get_json(silent=True) or {}
    token = str(data.get("token") or "").strip()
    if not token:
        return jsonify({"ok": False, "error": "Paste a Discogs personal access token."}), 400

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
                "token": token,
                "username": username,
                "enabled": True,
            }
        }
    )
    return jsonify({"ok": True, "username": username})


@discogs_bp.post("/api/discogs/disconnect")
def api_discogs_disconnect():
    cfg = read_config(force=True)
    if get_discogs_token(cfg) and SYNC_MANAGER.status().get("syncing"):
        return jsonify({"ok": False, "error": "Wait until the current sync has finished."}), 409

    write_config(
        {
            "discogs": {
                "token": "",
                "username": "",
                "enabled": False,
            }
        }
    )
    return jsonify({"ok": True})


@discogs_bp.post("/api/discogs/sync")
def api_discogs_sync():
    cfg = read_config()
    if not get_discogs_token(cfg):
        return jsonify({"ok": False, "error": "Connect a Discogs account first."}), 400
    if not bool((cfg.get("discogs") or {}).get("enabled", False)):
        write_config({"discogs": {"enabled": True}})

    started = SYNC_MANAGER.start()
    if not started:
        return jsonify({"ok": True, "started": False, "message": "A Discogs sync is already running."})
    return jsonify({"ok": True, "started": True}), 202
