from flask import Blueprint, jsonify, request, send_from_directory
from vinylpi.paths import UPLOAD_DIR
from vinylpi.web.services.uploads import list_fallback_images, delete_fallback_image, upload_fallback_image

uploads_bp = Blueprint("uploads_api", __name__)

@uploads_bp.get("/api/fallback-images")
def api_list_fallback_images():
    return jsonify({"ok": True, "images": list_fallback_images()})

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
    file = request.files.get("file")
    if not file:
        return jsonify({"ok": False, "error": "no file field"}), 400

    payload, err = upload_fallback_image(file)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    return jsonify({"ok": True, **payload})
