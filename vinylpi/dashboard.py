from flask import Flask, request, jsonify, send_from_directory
import json
import time
from pathlib import Path
from werkzeug.utils import secure_filename
from config_loader import CONFIG_DEFAULTS

import subprocess
import threading
import sys

BASE_DIR = Path(__file__).resolve().parents[1]
WEBAPP_DIR = BASE_DIR / "WebApp"

app = Flask(
    __name__,
    static_folder=str(WEBAPP_DIR),
    static_url_path=""
)

CONFIG_PATH = BASE_DIR / "config.json"
STATUS_PATH = Path("/tmp/vinylpi_status.json")

UPLOAD_DIR = BASE_DIR / "assets" / "fallback"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_EXT = {"png", "jpg", "jpeg"}
STATS_PATH = BASE_DIR / "stats.json"

_recognizer_proc = None
_rec_lock = threading.Lock()


def _get_debug_logs_flag() -> bool:
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            return (cfg.get("debug") or {}).get("logs", False)
    except Exception as e:
        print(f"Could not read debug.logs from config: {e}")
    return False


def _is_recognizer_running():
    global _recognizer_proc
    if _recognizer_proc is None:
        return False
    if _recognizer_proc.poll() is None:
        return True
    _recognizer_proc = None
    return False


def _start_recognizer():
    global _recognizer_proc
    with _rec_lock:
        if _is_recognizer_running():
            return False

        cmd = [sys.executable, "-u", str(BASE_DIR / "vinylpi" / "main.py")]
        debug_log = _get_debug_logs_flag()

        if debug_log:
            _recognizer_proc = subprocess.Popen(cmd, cwd=BASE_DIR)
        else:
            _recognizer_proc = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        return True


def _stop_recognizer():
    global _recognizer_proc
    with _rec_lock:
        if not _is_recognizer_running():
            _recognizer_proc = None
            return False  

        _recognizer_proc.terminate()
        try:
            _recognizer_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _recognizer_proc.kill()
        finally:
            _recognizer_proc = None
        return True

@app.get("/api/fallback-images")
def api_list_fallback_images():
    current_path = None
    try:
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            current_path = (cfg.get("fallback") or {}).get("image_path")
    except Exception:
        pass

    files = []
    for p in sorted(UPLOAD_DIR.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
        if not p.is_file():
            continue
        rel_path = str(p.relative_to(BASE_DIR))          
        url = f"/uploads/{p.name}"                       
        files.append({
            "filename": p.name,
            "path": rel_path,
            "url": url,
            "is_current": (rel_path == current_path),
        })

    return jsonify({"ok": True, "images": files})

@app.get("/uploads/<path:filename>")
def serve_upload(filename):
    return send_from_directory(UPLOAD_DIR, filename)


@app.delete("/api/fallback-image/<path:filename>")
def api_delete_fallback_image(filename):
    p = UPLOAD_DIR / filename
    if not p.exists():
        return jsonify({"ok": False, "error": "file not found"}), 404

    try:
        cfg = {}
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        fb = cfg.setdefault("fallback", {})
        if fb.get("image_path") and fb["image_path"].endswith(filename):
            fb["image_path"] = ""  
            CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        print(f"Warning: could not update config after delete: {e}")

    p.unlink()
    return jsonify({"ok": True})


def _update_config_fallback_path(rel_path: str):
    try:
        cfg = {}
        if CONFIG_PATH.exists():
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

        cfg.setdefault("fallback", {})
        cfg["fallback"]["image_path"] = rel_path 

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

@app.route("/stats.html")
def stats_page():
    return app.send_static_file("stats.html")


@app.route("/about.html")
def about_page():
    return app.send_static_file("about.html")


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

@app.get("/api/recognizer/status")
def api_recognizer_status():
    running = _is_recognizer_running()
    return jsonify({"running": running})


@app.post("/api/recognizer/start")
def api_recognizer_start():
    started = _start_recognizer()
    return jsonify({"ok": True, "started": started, "running": _is_recognizer_running()})


@app.post("/api/recognizer/stop")
def api_recognizer_stop():
    stopped = _stop_recognizer()
    return jsonify({"ok": True, "stopped": stopped, "running": _is_recognizer_running()})

@app.get("/api/stats")
def api_stats():
    if not STATS_PATH.exists():
        return jsonify({
            "top_songs": [],
            "top_artists": [],
            "top_albums": [],
        })

    try:
        stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return jsonify({
            "top_songs": [],
            "top_artists": [],
            "top_albums": [],
        })

    songs = list((stats.get("songs") or {}).values())
    artists_map = stats.get("artists") or {}
    albums_map = stats.get("albums") or {}

    songs_sorted = sorted(songs, key=lambda s: s.get("count", 0), reverse=True)[:10]
    artists_sorted = sorted(
        [{"name": k, "count": v} for k, v in artists_map.items()],
        key=lambda a: a["count"],
        reverse=True
    )[:10]
    albums_sorted = sorted(
        [{"name": k, "count": v} for k, v in albums_map.items()],
        key=lambda a: a["count"],
        reverse=True
    )[:10]

    return jsonify({
        "top_songs": songs_sorted,
        "top_artists": artists_sorted,
        "top_albums": albums_sorted,
    })


@app.post("/api/config/reset")
def api_config_reset():
    try:
        CONFIG_PATH.write_text(
            json.dumps(CONFIG_DEFAULTS, indent=4),
            encoding="utf-8",
        )
        return jsonify({"ok": True})
    except Exception as e:
        print(f"Error resetting config to defaults: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500




if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
