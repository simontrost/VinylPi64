from flask import Blueprint, jsonify

from vinylpi.web.services.source import get_visible_status

status_bp = Blueprint("status_api", __name__)


@status_bp.get("/api/status")
def api_status():
    return jsonify(get_visible_status())
