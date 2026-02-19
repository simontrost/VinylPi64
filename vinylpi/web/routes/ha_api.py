from __future__ import annotations

import os
import hmac
import requests
from flask import Blueprint, request, jsonify, abort

from vinylpi.web.services import pixoo
from vinylpi.web.services import recognizer
from vinylpi.web.services.config import read_config

bp = Blueprint("ha_api", __name__, url_prefix="/api/ha")

API_TOKEN = os.getenv("VINYLPI_API_TOKEN", "")
if not API_TOKEN:
    raise RuntimeError("VINYLPI_API_TOKEN is not set")

cfg = read_config()
ha_cfg = cfg.get("homeassistant", {})

USE_HA = bool(ha_cfg.get("use_ha", False))

if USE_HA:
    base_url = ha_cfg.get("base_url")
    webhook_id = ha_cfg.get("webhook_id")

    if not base_url or not webhook_id:
        raise RuntimeError("Home Assistant config incomplete")

    HA_WEBHOOK_URL = f"{base_url.rstrip('/')}/api/webhook/{webhook_id}"
else:
    HA_WEBHOOK_URL = None

_last_sent_rgb = None


def require_token():
    token = request.headers.get("X-Api-Token", "")
    if not hmac.compare_digest(token, API_TOKEN):
        abort(401)


def send_rgb_to_ha(rgb):
    if not HA_WEBHOOK_URL:
        return

    global _last_sent_rgb
    if rgb == _last_sent_rgb:
        return
    _last_sent_rgb = rgb

    r, g, b = rgb
    try:
        requests.post(
            HA_WEBHOOK_URL,
            json={"r": int(r), "g": int(g), "b": int(b)},
            timeout=2,
        ).raise_for_status()
    except Exception as e:
        print(f"[HA] Failed sending RGB: {e}")


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
