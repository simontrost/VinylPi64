from flask import Blueprint, jsonify

from vinylpi.core.stats_db import get_current_status

status_bp = Blueprint("status_api", __name__)


@status_bp.get("/api/status")
def api_status():
    status = get_current_status()
    if status is None:
        return jsonify({"ok": False, "status": None}), 200
    return jsonify(status)
