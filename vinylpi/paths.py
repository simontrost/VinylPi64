from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

CONFIG_PATH = DATA_DIR / "config.json"
STATS_PATH = DATA_DIR / "stats.json"

STATUS_PATH = DATA_DIR / "status.json"

WEBAPP_DIR = BASE_DIR / "webapp"

UPLOAD_DIR = BASE_DIR / "assets" / "fallback"
FONTS_DIR = BASE_DIR / "assets" / "fonts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg"}

CLOUD_BASE_URL = "https://app.divoom-gz.com"
MB_URL = "https://musicbrainz.org/ws/2/recording"
MB_UA  = "VinylPi64/1.0 (https://github.com/simontrost/VinylPi64)"