from __future__ import annotations

import io

from flask import Blueprint, jsonify, send_file

from vinylpi.web.services.stats import build_share_card_image, get_top_stats

stats_bp = Blueprint("stats_api", __name__)


@stats_bp.get("/api/stats")
def api_stats():
    return jsonify(get_top_stats(limit=10))


@stats_bp.get("/api/stats/share-card")
def api_stats_share_card():
    image_bytes = build_share_card_image()
    return send_file(
        io.BytesIO(image_bytes),
        mimetype="image/png",
        download_name="vinylpi-wrapped.png",
        as_attachment=False,
        max_age=0,
    )
