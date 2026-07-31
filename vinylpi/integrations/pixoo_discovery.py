from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import requests

from vinylpi.config.runtime import read_config


def _probe_ip(ip: str, timeout: float) -> bool:
    cfg = read_config()
    debug_log = bool(cfg["debug"].get("logs", False))
    device_name = str((cfg.get("divoom") or {}).get("device_name") or "").casefold()

    try:
        response = requests.post(
            f"http://{ip}/post",
            json={"Command": "Channel/GetAllConf"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        return False

    if not isinstance(data, dict):
        return False

    server_header = response.headers.get("Server", "").casefold()
    if device_name and device_name in server_header and debug_log:
        print(f"Pixoo ({device_name}) found by server header at {ip}")

    is_pixoo = (
        "DeviceName" in data
        or "error_code" in data
        or "Brightness" in data
        or "SelectIndex" in data
    )
    if is_pixoo and debug_log:
        print(f"Pixoo-compatible device found at {ip}")
    return is_pixoo


def discover_pixoo_ip() -> Optional[str]:
    cfg = read_config()
    debug_log = bool(cfg["debug"].get("logs", False))
    divoom_cfg = cfg.get("divoom") or {}
    discovery_cfg = divoom_cfg.get("discovery") or {}

    if not discovery_cfg.get("enabled", False):
        if debug_log:
            print("Pixoo discovery is disabled in config.")
        return None

    subnet_prefix = str(discovery_cfg.get("subnet_prefix") or "").strip()
    if not subnet_prefix:
        if debug_log:
            print("No subnet prefix configured for Pixoo discovery.")
        return None

    start = max(1, int(discovery_cfg.get("ip_range_start", 2)))
    end = min(254, int(discovery_cfg.get("ip_range_end", 254)))
    if start > end:
        start, end = end, start

    timeout = max(0.1, float(divoom_cfg.get("timeout", 0.5)))
    candidates = [f"{subnet_prefix}{host}" for host in range(start, end + 1)]
    if debug_log:
        print(f"Searching Pixoo in {subnet_prefix}{start}-{end} ...")

    max_workers = min(24, len(candidates))
    with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="pixoo-scan") as pool:
        futures = {pool.submit(_probe_ip, ip, timeout): ip for ip in candidates}
        for future in as_completed(futures):
            ip = futures[future]
            try:
                if future.result():
                    for pending in futures:
                        pending.cancel()
                    return ip
            except Exception:
                continue

    if debug_log:
        print("No Pixoo device found in the configured subnet range.")
    return None
