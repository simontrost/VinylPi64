from flask import Blueprint, jsonify
from vinylpi.web.services.stats import get_top_stats

stats_bp = Blueprint("stats_api", __name__)

@stats_bp.get("/api/stats")
def api_stats():
    return jsonify(get_top_stats(limit=10))
