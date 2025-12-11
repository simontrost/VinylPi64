from flask import Flask, request, jsonify, send_from_directory, send_file
import json
from io import BytesIO
import time
from pathlib import Path
from werkzeug.utils import secure_filename
from .config_loader import CONFIG_DEFAULTS, CONFIG_PATH, reload_config
from .divoom_api import PixooClient, PixooError
from .statistics import _load_stats

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

        cmd = [sys.executable, "-u", "-m", "vinylpi.main"]
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


def _get_pixoo_client():
    try:
        return PixooClient()
    except PixooError as e:
        print(f"Pixoo error while creating client: {e}")
        return None


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


@app.get("/api/pixoo/status")
def api_pixoo_status():
    client = _get_pixoo_client()
    if not client:
        return jsonify({
            "ok": False,
            "online": False,
            "error": "Pixoo not reachable",
        })

    try:
        conf = client.get_all_conf()
    except PixooError as e:
        return jsonify({
            "ok": False,
            "online": False,
            "error": str(e),
        })

    return jsonify({
        "ok": True,
        "online": True,
        "brightness": conf.get("Brightness"),
        "channel": conf.get("SelectIndex"),
        "device_name": conf.get("DeviceName") or "Pixoo",
        "raw": conf,
    })


@app.post("/api/pixoo/brightness")
def api_pixoo_brightness():
    data = request.get_json() or {}
    value = data.get("brightness")

    if value is None:
        return jsonify({"ok": False, "error": "missing brightness"}), 400

    client = _get_pixoo_client()
    if not client:
        return jsonify({"ok": False, "error": "Pixoo not reachable"}), 500

    try:
        client.set_brightness(int(value))
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})


@app.post("/api/pixoo/reboot")
def api_pixoo_reboot():
    try:
        client = PixooClient()
        client.reboot()
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/pixoo/channel")
def api_pixoo_channel():
    data = request.get_json() or {}
    ch = data.get("channel")

    if ch is None:
        return jsonify({"ok": False, "error": "missing channel"}), 400

    client = _get_pixoo_client()
    if not client:
        return jsonify({"ok": False, "error": "Pixoo not reachable"}), 500

    try:
        client.set_channel(int(ch))
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})



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

@app.get("/api/pixoo/liked-gifs")
def api_pixoo_liked_gifs():
    client = _get_pixoo_client()
    if not client:
        return jsonify({"ok": False, "error": "Pixoo not reachable"}), 500

    try:
        gifs = client.get_liked_gifs(page=1)
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True, "gifs": gifs})


@app.post("/api/pixoo/play-remote")
def api_pixoo_play_remote():
    data = request.get_json() or {}
    file_id = data.get("file_id")

    if not file_id:
        return jsonify({"ok": False, "error": "missing file_id"}), 400

    client = _get_pixoo_client()
    if not client:
        return jsonify({"ok": False, "error": "Pixoo not reachable"}), 500

    try:
        client.play_remote_gif(file_id)
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    return jsonify({"ok": True})

@app.post("/api/pixoo/discover-and-save")
def api_pixoo_discover_and_save():
    try:
        client = PixooClient()
        dev = client.discover_cloud_device()
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    try:
        if CONFIG_PATH.exists():
            raw = CONFIG_PATH.read_text(encoding="utf-8")
            cfg = json.loads(raw)
        else:
            cfg = json.loads(json.dumps(CONFIG_DEFAULTS))
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to read config: {e}"}), 500

    divoom_cfg = cfg.get("divoom") or {}
    if dev.get("device_private_ip"):
        divoom_cfg["ip"] = dev["device_private_ip"]
    if dev.get("device_id") is not None:
        divoom_cfg["device_id"] = dev["device_id"]
    if dev.get("device_mac"):
        divoom_cfg["device_mac"] = dev["device_mac"]

    cfg["divoom"] = divoom_cfg

    try:
        CONFIG_PATH.write_text(json.dumps(cfg, indent=4), encoding="utf-8")
    except Exception as e:
        return jsonify({"ok": False, "error": f"Failed to write config: {e}"}), 500

    try:
        reload_config()
    except Exception:
        pass

    return jsonify({
        "ok": True,
        "device": dev,
        "divoom": divoom_cfg,
    })


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

