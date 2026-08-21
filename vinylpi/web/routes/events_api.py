from __future__ import annotations

import json
import time

from flask import Blueprint, Response, stream_with_context

from vinylpi.web.services.source import get_visible_status

events_bp = Blueprint("events_api", __name__)


@events_bp.get("/api/events")
def api_events() -> Response:
    @stream_with_context
    def generate():
        last_revision = object()
        last_keepalive = time.monotonic()
        yield "retry: 2000\n\n"

        while True:
            status = get_visible_status()
            revision = status.get("updated_at") if status else None
            if revision != last_revision:
                last_revision = revision
                payload = status or {"ok": False, "status": None}
                yield f"event: status\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"

            now = time.monotonic()
            if now - last_keepalive >= 15:
                last_keepalive = now
                yield ": keepalive\n\n"
            time.sleep(0.25)

    response = Response(generate(), mimetype="text/event-stream")
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    response.headers["Connection"] = "keep-alive"
    return response
