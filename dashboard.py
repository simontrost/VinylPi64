from flask import Flask, request, jsonify
import json
from pathlib import Path

app = Flask(__name__, static_url_path='/static', static_folder='static')

CONFIG_PATH = Path("config.json")
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
        return jsonify(json.loads(STATUS_PATH.read_text()))
    return jsonify({"error": "no status"}), 404


@app.get("/api/config")
def api_config():
    return jsonify(json.loads(CONFIG_PATH.read_text()))


@app.post("/api/config")
def api_config_update():
    data = request.json
    CONFIG_PATH.write_text(json.dumps(data, indent=4))
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
