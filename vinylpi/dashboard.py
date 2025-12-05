from flask import Flask, request, jsonify
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
WEBAPP_DIR = BASE_DIR / "WebApp"

app = Flask(
    __name__,
    static_folder=str(WEBAPP_DIR),
    static_url_path=""
)

CONFIG_PATH = BASE_DIR / "config.json"
STATUS_PATH = Path("/tmp/vinylpi_status.json")


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
