from flask import Blueprint, jsonify, request, send_from_directory

from vinylpi.config.runtime import normalize_fallback_kind
from vinylpi.paths import UPLOAD_DIR
from vinylpi.web.services.uploads import (
    delete_fallback_image,
    list_fallback_images,
    upload_fallback_image,
)

uploads_bp = Blueprint("uploads_api", __name__)


def _requested_kind() -> str:
    return normalize_fallback_kind(request.args.get("kind"))


@uploads_bp.get("/api/fallback-images")
def api_list_fallback_images():
    try:
        kind = _requested_kind()
    except ValueError:
        return jsonify({"ok": False, "error": "invalid kind"}), 400
    return jsonify({"ok": True, "kind": kind, "images": list_fallback_images(kind=kind)})


@uploads_bp.get("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@uploads_bp.delete("/api/fallback-image/<path:filename>")
def api_delete_fallback_image(filename):
    ok = delete_fallback_image(filename)
    if not ok:
        return jsonify({"ok": False, "error": "file not found"}), 404
    return jsonify({"ok": True})


@uploads_bp.post("/api/fallback-image")
def api_fallback_image_upload():
    try:
        kind = _requested_kind()
    except ValueError:
        return jsonify({"ok": False, "error": "invalid kind"}), 400

    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "no file field"}), 400

    payload, err = upload_fallback_image(file, kind=kind)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    return jsonify({"ok": True, **payload})
