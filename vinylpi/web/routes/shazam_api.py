from flask import Blueprint, jsonify, request
from vinylpi.core.shazam_info import get_shazam_info

shazam_bp = Blueprint("shazam_api", __name__)


@shazam_bp.get("/api/shazam/info")
def api_shazam_info():
    track_id = request.args.get("track_id") or None
    artist_id = request.args.get("artist_id") or None

    data = get_shazam_info(track_id, artist_id)

    if not data.get("ok"):
        return jsonify(data), 400

    return jsonify(data)