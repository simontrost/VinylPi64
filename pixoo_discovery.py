from __future__ import annotations

from typing import Optional

import requests

from config_loader import CONFIG


def _probe_ip(ip: str, timeout: float) -> bool:
    url = f"http://{ip}/post"
    payload = {"Command": "Channel/GetAllConf"}

    divoom_cfg = CONFIG.get("divoom", {})

    try:
        resp = requests.post(url, json=payload, timeout=timeout)
        resp.raise_for_status()

        server_header = resp.headers.get("Server", "").lower()
        if divoom_cfg["device_name"] in server_header:
            print(f"Pixoo ({divoom_cfg["device_name"]}) found by server-header at {ip}")
            return True

        data = resp.json()
    except Exception:
        return False

    if not isinstance(data, dict):
        return False

    if "DeviceName" in data:
        print(f"Pixoo found (DeviceName match) at {ip}: {data['DeviceName']}")
        return True

    if "error_code" in data or "Brightness" in data:
        print(f"Pixoo-like response from {ip}: {data}")
        return True

    return False

def discover_pixoo_ip() -> Optional[str]:
    divoom_cfg = CONFIG.get("divoom", {})
    disc_cfg = divoom_cfg.get("discovery", {})

    if not disc_cfg.get("enabled", False):
        print("Pixoo discovery is disabled in config.")
        return None

    subnet_prefix = disc_cfg.get("subnet_prefix")
    if not subnet_prefix:
        print("No subnet prefix configured for Pixoo discovery.")
        return None

    start = int(disc_cfg.get("ip_range_start", 2))
    end = int(disc_cfg.get("ip_range_end", 254))
    timeout = float(divoom_cfg.get("timeout", 0.3))

    print(f"Starting pixoo discovery from subnet: {subnet_prefix}{start}-{end} ...")

    for host in range(start, end + 1):
        ip = f"{subnet_prefix}{host}"
        print(f"  Trying {ip} ...", end="\r")
        if _probe_ip(ip, timeout):
            print(f"\nPixoofound under {ip}")
            return ip

    print("\nNo Pixoo device found in the specified subnet range.")
    return None
