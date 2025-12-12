import json
from flask import Blueprint, jsonify
from vinylpi.paths import STATUS_PATH

status_bp = Blueprint("status_api", __name__)

@status_bp.get("/api/status")
def api_status():
    if STATUS_PATH.exists():
        return jsonify(json.loads(STATUS_PATH.read_text(encoding="utf-8")))
    return jsonify({"ok": False, "status": None}), 200
