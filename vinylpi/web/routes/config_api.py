from __future__ import annotations

import os
from copy import deepcopy

from flask import Blueprint, jsonify, request

from vinylpi.core.display_refresh import request_display_refresh
from vinylpi.web.services.config import read_config, write_config, reset_config

config_bp = Blueprint("config_api", __name__)


def _public_config(cfg: dict) -> dict:
    public = deepcopy(cfg)
    discogs = public.setdefault("discogs", {})
    configured = bool((discogs.get("token") or "").strip() or (os.getenv("DISCOGS_TOKEN") or "").strip())
    discogs.pop("token", None)
    discogs["token_configured"] = configured
    return public


def _strip_read_only_and_sensitive_fields(data: dict) -> dict:
    clean = deepcopy(data)
    discogs = clean.get("discogs")
    if isinstance(discogs, dict):
        discogs.pop("token", None)
        discogs.pop("token_configured", None)
    return clean


@config_bp.get("/api/config")
def api_config():
    return jsonify(_public_config(read_config()))


@config_bp.post("/api/config")
def api_config_update():
    data = request.get_json(force=True) or {}
    data = _strip_read_only_and_sensitive_fields(data if isinstance(data, dict) else {})
    before = read_config(force=True)
    updated = write_config(data)
    display_changed = before.get("image") != updated.get("image")
    if display_changed:
        request_display_refresh()
    return jsonify({"ok": True, "display_refresh_requested": display_changed})


@config_bp.post("/api/config/reset")
def api_config_reset():
    before = read_config(force=True)
    updated = reset_config()
    display_changed = before.get("image") != updated.get("image")
    if display_changed:
        request_display_refresh()
    return jsonify({"ok": True, "display_refresh_requested": display_changed})
