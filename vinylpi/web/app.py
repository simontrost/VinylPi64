from flask import Flask
from vinylpi.paths import WEBAPP_DIR
from .routes.pages import pages_bp
from .routes.status_api import status_bp
from .routes.config_api import config_bp
from .routes.recognizer_api import recognizer_bp
from .routes.pixoo_api import pixoo_bp
from .routes.stats_api import stats_bp
from .routes.uploads_api import uploads_bp
from .routes.genius_api import genius_bp
from .routes.ha_api import bp as ha_api_bp

def create_app() -> Flask:
    app = Flask(
        __name__,
        static_folder=str(WEBAPP_DIR),
        static_url_path=""
    )

    app.register_blueprint(pages_bp)
    app.register_blueprint(status_bp)
    app.register_blueprint(config_bp)
    app.register_blueprint(recognizer_bp)
    app.register_blueprint(pixoo_bp)
    app.register_blueprint(stats_bp)
    app.register_blueprint(uploads_bp)
    app.register_blueprint(genius_bp)
    app.register_blueprint(ha_api_bp)
    return app
