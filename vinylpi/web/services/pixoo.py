from vinylpi.integrations.divoom_api import PixooClient, PixooError

def get_client():
    try:
        return PixooClient()
    except PixooError:
        return None

def get_status():
    client = get_client()
    if not client:
        return {"ok": False, "online": False, "error": "Pixoo not reachable"}

    conf = client.get_all_conf()
    return {
        "ok": True,
        "online": True,
        "brightness": conf.get("Brightness"),
        "channel": conf.get("SelectIndex"),
        "device_name": conf.get("DeviceName") or "Pixoo",
        "raw": conf,
    }

def set_brightness(value: int):
    client = get_client()
    if not client:
        raise PixooError("Pixoo not reachable")
    client.set_brightness(int(value))

def reboot():
    client = PixooClient()
    client.reboot()

def set_channel(channel: int):
    client = get_client()
    if not client:
        raise PixooError("Pixoo not reachable")
    client.set_channel(int(channel))

def get_liked_gifs(page: int = 1):
    client = get_client()
    if not client:
        raise PixooError("Pixoo not reachable")
    return client.get_liked_gifs(page=page)

def play_remote_gif(file_id: str):
    client = get_client()
    if not client:
        raise PixooError("Pixoo not reachable")
    client.play_remote_gif(file_id)

def discover_cloud_device():
    client = PixooClient()
    return client.discover_cloud_device()
