from __future__ import annotations

import threading

import requests

from vinylpi.config.runtime import read_config

_lock = threading.Lock()
_last_sent_rgb: tuple[int, int, int] | None = None
_session = requests.Session()


def _webhook_url() -> str | None:
    cfg = read_config()
    ha_cfg = cfg.get("homeassistant") or {}
    if not ha_cfg.get("use_ha", False):
        return None

    base_url = str(ha_cfg.get("base_url") or "").strip().rstrip("/")
    webhook_id = str(ha_cfg.get("webhook_id") or "").strip()
    if not base_url or not webhook_id:
        return None
    return f"{base_url}/api/webhook/{webhook_id}"


def send_rgb(rgb: tuple[int, int, int]) -> None:
    """Send a cover-derived color to Home Assistant when configured."""
    global _last_sent_rgb

    webhook_url = _webhook_url()
    if not webhook_url:
        return

    normalized = tuple(max(0, min(255, int(value))) for value in rgb)
    with _lock:
        if normalized == _last_sent_rgb:
            return

    r, g, b = normalized
    try:
        _session.post(
            webhook_url,
            json={"r": r, "g": g, "b": b},
            timeout=2,
        ).raise_for_status()
    except requests.RequestException as exc:
        print(f"[HA] Failed sending RGB: {exc}")
        return

    with _lock:
        _last_sent_rgb = normalized
