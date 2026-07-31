from flask import Blueprint, jsonify, request

from vinylpi.core.display_refresh import request_display_refresh
from vinylpi.web.services.config import read_config, write_config, reset_config

config_bp = Blueprint("config_api", __name__)


@config_bp.get("/api/config")
def api_config():
    return jsonify(read_config())


@config_bp.post("/api/config")
def api_config_update():
    data = request.get_json(force=True) or {}
    before = read_config(force=True)
    updated = write_config(data)
    display_changed = before.get("image") != updated.get("image")
    if display_changed:
        request_display_refresh()
    return jsonify({"ok": True, "display_refresh_requested": display_changed})


@config_bp.post("/api/config/reset")
def api_config_reset():
    before = read_config(force=True)
    updated = reset_config()
    display_changed = before.get("image") != updated.get("image")
    if display_changed:
        request_display_refresh()
    return jsonify({"ok": True, "display_refresh_requested": display_changed})
