from flask import Blueprint, jsonify, request
from vinylpi.core.genius_scraper import get_lyrics

genius_bp = Blueprint("genius_api", __name__)


@genius_bp.get("/api/lyrics")
def api_lyrics():
    artist = request.args.get("artist", "")
    title = request.args.get("title", "")

    if not artist or not title:
        return jsonify({"ok": False, "error": "missing_params"}), 400

    data = get_lyrics(artist, title)
    return jsonify(data)
