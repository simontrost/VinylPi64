from flask import Blueprint, jsonify, request
from ..services.config import read_config, write_config, reset_config

config_bp = Blueprint("config_api", __name__)

@config_bp.get("/api/config")
def api_config():
    return jsonify(read_config())

@config_bp.post("/api/config")
def api_config_update():
    data = request.get_json(force=True) or {}
    write_config(data)
    return jsonify({"ok": True})

@config_bp.post("/api/config/reset")
def api_config_reset():
    reset_config()
    return jsonify({"ok": True})
