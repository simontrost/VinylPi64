from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = BASE_DIR / "data"

# Legacy locations from VinylPi versions before profile support. They remain
# available for one-time migration and for maintenance scripts/tests that pass
# an explicit path.
CONFIG_PATH = DATA_DIR / "config.json"
STATS_PATH = DATA_DIR / "stats.json"
DB_PATH = DATA_DIR / "vinylpi.db"
DISPLAY_REFRESH_PATH = DATA_DIR / "display_refresh.request"
STATUS_PATH = DATA_DIR / "status.json"

PROFILES_DIR = DATA_DIR / "profiles"
PROFILE_REGISTRY_PATH = DATA_DIR / "profiles.json"


def get_active_profile_dir() -> Path:
    from vinylpi.profiles import get_active_storage_key

    return PROFILES_DIR / get_active_storage_key()


def get_active_config_path() -> Path:
    if not PROFILE_REGISTRY_PATH.exists():
        return CONFIG_PATH
    return get_active_profile_dir() / "config.json"


def get_active_db_path() -> Path:
    if not PROFILE_REGISTRY_PATH.exists():
        return DB_PATH
    return get_active_profile_dir() / "vinylpi.db"


def get_active_display_refresh_path() -> Path:
    if not PROFILE_REGISTRY_PATH.exists():
        return DISPLAY_REFRESH_PATH
    return get_active_profile_dir() / "display_refresh.request"


UPLOAD_DIR = BASE_DIR / "assets" / "fallback"
FONTS_DIR = BASE_DIR / "assets" / "fonts"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXT = {"png", "jpg", "jpeg"}
ALLOWED_FONT_EXT = {"ttf", "otf"}

CLOUD_BASE_URL = "https://app.divoom-gz.com"
MB_URL = "https://musicbrainz.org/ws/2/recording"
MB_UA = "VinylPi64/1.0 (https://github.com/simontrost/VinylPi64)"
