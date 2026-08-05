from __future__ import annotations

from dotenv import load_dotenv
from flask import Flask

from vinylpi.core.storage import initialize_storage
from vinylpi.paths import BASE_DIR
from vinylpi.web.routes.config_api import config_bp
from vinylpi.web.routes.discogs_api import discogs_bp
from vinylpi.web.routes.events_api import events_bp
from vinylpi.web.routes.genius_api import genius_bp
from vinylpi.web.routes.ha_api import bp as ha_api_bp
from vinylpi.web.routes.pages import pages_bp
from vinylpi.web.routes.pixoo_api import pixoo_bp
from vinylpi.web.routes.profiles_api import profiles_bp
from vinylpi.web.routes.recognizer_api import recognizer_bp
from vinylpi.web.routes.shazam_api import shazam_bp
from vinylpi.web.routes.stats_api import stats_bp
from vinylpi.web.routes.status_api import status_bp
from vinylpi.web.routes.uploads_api import uploads_bp

load_dotenv(BASE_DIR / "vinylpi.env")

_BLUEPRINTS = (
    pages_bp,
    status_bp,
    events_bp,
    config_bp,
    profiles_bp,
    discogs_bp,
    recognizer_bp,
    pixoo_bp,
    stats_bp,
    uploads_bp,
    genius_bp,
    ha_api_bp,
    shazam_bp,
)


def create_app() -> Flask:
    initialize_storage()
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )

    for blueprint in _BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app
