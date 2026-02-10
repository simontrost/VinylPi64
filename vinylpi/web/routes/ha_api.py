from __future__ import annotations

from flask import Blueprint, request, jsonify, abort

from vinylpi.web.services import pixoo
from vinylpi.web.services import recognizer

bp = Blueprint("ha_api", __name__, url_prefix="/api/ha")

API_TOKEN = "CHANGE_ME"

def require_token():
    token = request.headers.get("X-Api-Token", "")
    if token != API_TOKEN:
        abort(401)

# test
DESIGN_PRESETS = {
    "lofi": "123456",
    "waves": "ABCDEF",
}

@bp.post("/design/<name>")
def show_design(name: str):
    require_token()

    file_id = DESIGN_PRESETS.get(name)
    if not file_id:
        return jsonify({"ok": False, "error": f"Unknown design: {name}"}), 400

    pixoo.play_remote_gif(file_id)
    return jsonify({"ok": True, "design": name, "file_id": file_id})


@bp.post("/music_mode/on")
def music_mode_on():
    require_token()
    started = recognizer.start(silence_output=True)
    return jsonify({"ok": True, "started": started})

@bp.post("/music_mode/off")
def music_mode_off():
    require_token()
    stopped = recognizer.stop()
    return jsonify({"ok": True, "stopped": stopped})


@bp.post("/off")
def pixoo_off():
    require_token()
    pixoo.set_brightness(0)
    return jsonify({"ok": True})

@bp.post("/on")
def pixoo_on():
    require_token()
    pixoo.set_brightness(100)
    return jsonify({"ok": True})
