from flask import Flask, request, jsonify, send_from_directory, send_file
import json
from io import BytesIO
import time
from pathlib import Path
from werkzeug.utils import secure_filename
from .config_loader import CONFIG_DEFAULTS
from .divoom_api import PixooClient, PixooError
from .statistics import _load_stats
from PIL import Image, ImageDraw, ImageFont

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


@app.get("/api/pixoo/state")
def api_pixoo_state():
    """
    Liefert Basiszustand des Pixoo: erreichbar?, Helligkeit, Channel.
    """
    try:
        client = PixooClient()
        conf = client.get_all_conf()

        # Die exakten Keys hängen von der Firmware ab, aber
        # Brightness gibt es sicher, Channel sehr wahrscheinlich als SelectIndex.
        brightness = conf.get("Brightness")
        channel = conf.get("SelectIndex")

        return jsonify({
            "ok": True,
            "reachable": True,
            "brightness": brightness,
            "channel": channel,
            "raw": conf,
        })
    except PixooError as e:
        return jsonify({
            "ok": False,
            "reachable": False,
            "error": str(e),
        }), 500
    except Exception as e:
        return jsonify({
            "ok": False,
            "reachable": False,
            "error": f"Unexpected error: {e}",
        }), 500


@app.post("/api/pixoo/brightness")
def api_pixoo_brightness():
    data = request.json or {}
    value = data.get("brightness")
    if value is None:
        return jsonify({"ok": False, "error": "missing brightness"}), 400

    try:
        client = PixooClient()
        client.set_brightness(int(value))
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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
    data = request.json or {}
    ch = data.get("channel")
    if ch is None:
        return jsonify({"ok": False, "error": "missing channel"}), 400

    try:
        client = PixooClient()
        client.set_channel(int(ch))
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500


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


@app.get("/api/stats/share-image")
def api_stats_share_image():
    if STATS_PATH.exists():
        try:
            stats = json.loads(STATS_PATH.read_text(encoding="utf-8"))
        except Exception:
            stats = {}
    else:
        stats = {}

    songs_dict = stats.get("songs") or {}
    artists_dict = stats.get("artists") or {}
    albums_dict = stats.get("albums") or {}

    if not songs_dict and not artists_dict and not albums_dict:
        img = Image.new("RGB", (1080, 1920), (24, 24, 24))
        draw = ImageDraw.Draw(img)
        msg = "No stats yet.\nPlay a record on VinylPi64!"
        draw.multiline_text((80, 880), msg, fill=(240, 240, 240), spacing=10)
        buf = BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        return send_file(buf, mimetype="image/png", download_name="vinylpi_stats.png")

    top_songs = sorted(
        songs_dict.values(),
        key=lambda s: s.get("count", 0),
        reverse=True,
    )[:5]

    top_artists = sorted(
        artists_dict.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:5]

    top_albums = sorted(
        albums_dict.items(),
        key=lambda kv: kv[1],
        reverse=True,
    )[:5]

    width, height = 1080, 1920
    bg_color = (18, 18, 18)
    accent = (255, 214, 10)
    fg = (240, 240, 240)
    fg_sub = (180, 180, 180)

    img = Image.new("RGB", (width, height), bg_color)
    draw = ImageDraw.Draw(img)

    def load_font(size: int):
        try:
            font_path = BASE_DIR / "assets" / "Inter-SemiBold.ttf"
            return ImageFont.truetype(str(font_path), size)
        except Exception:
            return ImageFont.load_default()

    title_font = load_font(72)
    section_font = load_font(46)
    item_font = load_font(40)
    small_font = load_font(30)

    # Header
    year = time.localtime().tm_year
    header = f"VinylPi64 Wrapped {year}"
    tw, th = draw.textsize(header, font=title_font)
    draw.text(((width - tw) // 2, 80), header, font=title_font, fill=fg)

    # Optional: Logo
    logo_path = BASE_DIR / "assets" / "vinylpi_logo.png"
    if logo_path.exists():
        try:
            logo = Image.open(logo_path).convert("RGBA")
            max_w = 420
            scale = min(max_w / logo.width, 1.0)
            logo = logo.resize((int(logo.width * scale), int(logo.height * scale)), Image.Resampling.LANCZOS)
            lx = (width - logo.width) // 2
            ly = 200
            img.paste(logo, (lx, ly), logo)
        except Exception:
            pass

    col_margin_x = 120
    col_gap = 40
    col_width = (width - 2 * col_margin_x - col_gap) // 2

    left_x = col_margin_x
    right_x = col_margin_x + col_width + col_gap
    y_start = 650

    draw.text((left_x, y_start), "Top Songs", font=section_font, fill=accent)
    y = y_start + 70
    for i, song in enumerate(top_songs, start=1):
        title = song.get("title") or "Unknown"
        artist = song.get("artist") or ""
        count = song.get("count", 0)

        line = f"{i}. {title}"
        draw.text((left_x, y), line, font=item_font, fill=fg)
        sub = f"{artist} · {count} plays" if artist else f"{count} plays"
        draw.text((left_x + 40, y + 40), sub, font=small_font, fill=fg_sub)
        y += 90

    draw.text((right_x, y_start), "Top Artists", font=section_font, fill=accent)
    y2 = y_start + 70
    for i, (name, count) in enumerate(top_artists, start=1):
        line = f"{i}. {name}"
        draw.text((right_x, y2), line, font=item_font, fill=fg)
        draw.text((right_x + 40, y2 + 40), f"{count} plays", font=small_font, fill=fg_sub)
        y2 += 90

    if top_albums:
        best_album, album_plays = top_albums[0]
        footer_y = height - 200
        draw.text((left_x, footer_y), "Top Album", font=section_font, fill=accent)
        draw.text((left_x, footer_y + 60), best_album, font=item_font, fill=fg)
        draw.text((left_x, footer_y + 110), f"{album_plays} plays", font=small_font, fill=fg_sub)

    footer_text = "Generated with VinylPi64"
    ftw, fth = draw.textsize(footer_text, font=small_font)
    draw.text((width - ftw - 60, height - fth - 60), footer_text, font=small_font, fill=fg_sub)

    buf = BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return send_file(buf, mimetype="image/png", download_name="vinylpi_stats.png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)

