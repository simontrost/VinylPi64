from flask import Blueprint, jsonify, request
from vinylpi.integrations.divoom_api import PixooError
from ..services import pixoo
from ..services.config import read_config, write_config
from vinylpi.config.config_loader import CONFIG_DEFAULTS, reload_config

pixoo_bp = Blueprint("pixoo_api", __name__)

@pixoo_bp.get("/api/pixoo/status")
def api_pixoo_status():
    try:
        return jsonify(pixoo.get_status())
    except PixooError as e:
        return jsonify({"ok": False, "online": False, "error": str(e)}), 500

@pixoo_bp.post("/api/pixoo/brightness")
def api_pixoo_brightness():
    data = request.get_json() or {}
    value = data.get("brightness")
    if value is None:
        return jsonify({"ok": False, "error": "missing brightness"}), 400
    try:
        pixoo.set_brightness(int(value))
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@pixoo_bp.post("/api/pixoo/reboot")
def api_pixoo_reboot():
    try:
        pixoo.reboot()
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@pixoo_bp.post("/api/pixoo/channel")
def api_pixoo_channel():
    data = request.get_json() or {}
    ch = data.get("channel")
    if ch is None:
        return jsonify({"ok": False, "error": "missing channel"}), 400
    try:
        pixoo.set_channel(int(ch))
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@pixoo_bp.get("/api/pixoo/liked-gifs")
def api_pixoo_liked_gifs():
    try:
        gifs = pixoo.get_liked_gifs(page=1)
        return jsonify({"ok": True, "gifs": gifs})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@pixoo_bp.post("/api/pixoo/play-remote")
def api_pixoo_play_remote():
    data = request.get_json() or {}
    file_id = data.get("file_id")
    if not file_id:
        return jsonify({"ok": False, "error": "missing file_id"}), 400
    try:
        pixoo.play_remote_gif(file_id)
        return jsonify({"ok": True})
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

@pixoo_bp.post("/api/pixoo/discover-and-save")
def api_pixoo_discover_and_save():
    try:
        dev = pixoo.discover_cloud_device()
    except PixooError as e:
        return jsonify({"ok": False, "error": str(e)}), 500

    try:
        cfg = read_config()
    except Exception:
        cfg = CONFIG_DEFAULTS

    divoom_cfg = cfg.get("divoom") or {}
    if dev.get("device_private_ip"):
        divoom_cfg["ip"] = dev["device_private_ip"]
    if dev.get("device_id") is not None:
        divoom_cfg["device_id"] = dev["device_id"]
    if dev.get("device_mac"):
        divoom_cfg["device_mac"] = dev["device_mac"]

    cfg["divoom"] = divoom_cfg
    write_config(cfg)

    return jsonify({"ok": True, "device": dev, "divoom": divoom_cfg})
