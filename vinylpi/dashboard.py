# dashboard.py
from flask import Flask, request, jsonify
import json
import time
from pathlib import Path
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parents[1]
WEBAPP_DIR = BASE_DIR / "WebApp"

app = Flask(
    __name__,
    static_folder=str(WEBAPP_DIR),
    static_url_path=""
)

CONFIG_PATH = BASE_DIR / "config.json"
STATUS_PATH = Path("/tmp/vinylpi_status.json")

# 👉 NEU: Upload-Verzeichnis (z.B. im assets-Ordner)
UPLOAD_DIR = BASE_DIR / "assets" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg"}

def _update_config_fallback_path(rel_path: str):
    """Schreibt den neuen Fallback-Pfad in die config.json."""
    try:
        cfg = {}
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        cfg.setdefault("fallback", {})
        cfg["fallback"]["image_path"] = rel_path  # z.B. "assets/uploads/fallback_123.png"

        CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
        return True
    except Exception as e:
        print(f"Could not update config.json with new fallback path: {e}")
        return False


@app.post("/api/fallback-image")
def api_fallback_image_upload():
    if "file" not in request.files:
        return jsonify({"ok": False, "error": "no file field"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"ok": False, "error": "empty filename"}), 400

    ext = file.filename.rsplit(".", 1)[-1].lower()
    if ext not in ALLOWED_EXT:
        return jsonify({"ok": False, "error": "invalid file type"}), 400

    filename = secure_filename(f"fallback_{int(time.time())}.{ext}")
    dst_path = UPLOAD_DIR / filename
    file.save(dst_path)

    # Pfad relativ zum Projekt (damit dein Python-Code ihn wie bisher benutzen kann)
    rel_path = str(dst_path.relative_to(BASE_DIR))

    if not _update_config_fallback_path(rel_path):
        return jsonify({"ok": False, "error": "could not write config"}), 500

    return jsonify({"ok": True, "image_path": rel_path})


@app.route("/")
def index():
    return app.send_static_file("index.html")


@app.route("/settings.html")
def settings_page():
    return app.send_static_file("settings.html")


@app.get("/api/status")
def api_status():
    if STATUS_PATH.exists():
        return jsonify(json.loads(STATUS_PATH.read_text(encoding="utf-8")))
    return jsonify({"error": "no status"}), 404


@app.get("/api/config")
def api_config():
    return jsonify(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))


@app.post("/api/config")
def api_config_update():
    data = request.json
    CONFIG_PATH.write_text(json.dumps(data, indent=4), encoding="utf-8")
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
