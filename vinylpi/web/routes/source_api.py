from __future__ import annotations

from flask import Blueprint, jsonify, request

from vinylpi.web.services.source import SourceBusyError, get_status, set_mode

source_bp = Blueprint("source_api", __name__)


@source_bp.get("/api/source")
def api_source_status():
    return jsonify({"ok": True, **get_status()})


@source_bp.post("/api/source")
def api_source_set():
    data = request.get_json(silent=True) or {}
    mode = str(data.get("mode") or "").strip().lower()
    try:
        status = set_mode(mode)
        return jsonify({"ok": True, **status})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except PermissionError as exc:
        return jsonify({"ok": False, "error": str(exc), "needs_auth": True, **get_status()}), 409
    except ConnectionError as exc:
        return jsonify({"ok": False, "error": str(exc), **get_status()}), 503
    except SourceBusyError as exc:
        return jsonify(
            {
                "ok": False,
                "error": str(exc),
                "busy": True,
                "owner_name": exc.owner_name,
                **get_status(),
            }
        ), 409
    except RuntimeError as exc:
        return jsonify({"ok": False, "error": str(exc), "needs_config": True, **get_status()}), 409
