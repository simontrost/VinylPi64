from __future__ import annotations

import io

from flask import Blueprint, jsonify, request, send_file

from vinylpi.web.services.stats import build_share_card_image
from vinylpi.web.services.stats_scoped import get_scoped_stats

stats_bp = Blueprint("stats_api", __name__)


@stats_bp.get("/api/stats")
def api_stats():
    scope = request.args.get("scope", "vinyl")
    return jsonify(get_scoped_stats(scope=scope, limit=10))


@stats_bp.get("/api/stats/share-card")
def api_stats_share_card():
    # The existing share artwork intentionally remains "Vinyl Wrapped". The
    # scope selector hides this action for Spotify/Combined views.
    image_bytes = build_share_card_image()
    return send_file(
        io.BytesIO(image_bytes),
        mimetype="image/png",
        download_name="vinylpi-wrapped.png",
        as_attachment=False,
        max_age=0,
    )
