from flask import Blueprint, jsonify, request, send_file, send_from_directory

from vinylpi.config.runtime import normalize_fallback_kind
from vinylpi.paths import UPLOAD_DIR
from vinylpi.web.services.uploads import (
    build_font_preview,
    delete_fallback_image,
    delete_font,
    list_fallback_images,
    list_fonts,
    upload_fallback_image,
    upload_font,
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


@uploads_bp.get("/api/fonts")
def api_list_fonts():
    return jsonify({"ok": True, "fonts": list_fonts()})


@uploads_bp.get("/api/font-preview/<path:filename>")
def api_font_preview(filename):
    preview = build_font_preview(filename)
    if preview is None:
        return jsonify({"ok": False, "error": "font not found or invalid"}), 404
    return send_file(preview, mimetype="image/png", max_age=300)


@uploads_bp.post("/api/font")
def api_font_upload():
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "no file field"}), 400

    payload, err = upload_font(file)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    return jsonify({"ok": True, **payload})


@uploads_bp.delete("/api/font/<path:filename>")
def api_delete_font(filename):
    ok = delete_font(filename)
    if not ok:
        return jsonify({"ok": False, "error": "file not found"}), 404
    return jsonify({"ok": True})
