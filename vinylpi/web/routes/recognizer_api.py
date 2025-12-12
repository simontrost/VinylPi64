from flask import Blueprint, jsonify
from ..services.recognizer import is_running, start, stop
from ..services.config import read_config

recognizer_bp = Blueprint("recognizer_api", __name__)

@recognizer_bp.get("/api/recognizer/status")
def api_recognizer_status():
    return jsonify({"running": is_running()})

@recognizer_bp.post("/api/recognizer/start")
def api_recognizer_start():
    cfg = read_config()
    debug_log = (cfg.get("debug") or {}).get("logs", False)
    started = start(silence_output=not debug_log)
    return jsonify({"ok": True, "started": started, "running": is_running()})

@recognizer_bp.post("/api/recognizer/stop")
def api_recognizer_stop():
    stopped = stop()
    return jsonify({"ok": True, "stopped": stopped, "running": is_running()})
