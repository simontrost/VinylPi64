from __future__ import annotations
from typing import Optional
import requests
from config_loader import CONFIG


def _probe_ip(ip: str, timeout: float) -> bool:
    debug_log = CONFIG["debug"]["logs"]
    url = f"http://{ip}/post"
    payload = {"Command": "Channel/GetAllConf"}

    divoom_cfg = CONFIG.get("divoom", {})

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()

        server_header = resp.headers.get("Server", "").lower()
        device_name = divoom_cfg["device_name"]
        if device_name in server_header and debug_log:
            print(f"Pixoo ({device_name}) found by server-header at {ip}")


        data = resp.json()
    except Exception:
        return False

    if not isinstance(data, dict):
        return False

    if "DeviceName" in data and debug_log:
        print(f"Pixoo found (DeviceName match) at {ip}: {data['DeviceName']}")
        return True

    if "error_code" in data or "Brightness" in data and debug_log:
        print(f"Pixoo-like response from {ip}: {data}")
        return True

    return False

def discover_pixoo_ip() -> Optional[str]:
    debug_log = CONFIG["debug"]["logs"]
    divoom_cfg = CONFIG.get("divoom", {})
    disc_cfg = divoom_cfg.get("discovery", {})

    if not disc_cfg.get("enabled", False) and debug_log:
        print("Pixoo discovery is disabled in config.")
        return None

    subnet_prefix = disc_cfg.get("subnet_prefix")
    if not subnet_prefix and debug_log:
        print("No subnet prefix configured for Pixoo discovery.")
        return None

    start = int(disc_cfg.get("ip_range_start", 2))
    end = int(disc_cfg.get("ip_range_end", 254))
    timeout = float(divoom_cfg.get("timeout", 0.3))

    if debug_log:
        print(f"Starting pixoo discovery from subnet: {subnet_prefix}{start}-{end} ...")

    for host in range(start, end + 1):
        ip = f"{subnet_prefix}{host}"
        if debug_log:
            print(f"  Trying {ip} ...", end="\r")
        if _probe_ip(ip, timeout) and debug_log:
            print(f"\nPixoofound under {ip}")
            return ip

    print("\nNo Pixoo device found in the specified subnet range.")
    return None
