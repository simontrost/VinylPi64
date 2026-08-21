from __future__ import annotations

import os
import secrets
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask, g, session

from vinylpi.core.storage import initialize_storage
from vinylpi.paths import BASE_DIR, DATA_DIR
from vinylpi.profiles import (
    profile_exists,
    reset_profile_storage_override,
    set_profile_storage_override,
)
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
from vinylpi.web.routes.source_api import source_bp
from vinylpi.web.routes.spotify_api import spotify_bp
from vinylpi.web.routes.stats_api import stats_bp
from vinylpi.web.routes.status_api import status_bp
from vinylpi.web.routes.uploads_api import uploads_bp

load_dotenv(BASE_DIR / "vinylpi.env", override=False)
load_dotenv(BASE_DIR / ".env", override=True)

_BLUEPRINTS = (
    pages_bp,
    status_bp,
    events_bp,
    config_bp,
    profiles_bp,
    discogs_bp,
    recognizer_bp,
    source_bp,
    spotify_bp,
    pixoo_bp,
    stats_bp,
    uploads_bp,
    genius_bp,
    ha_api_bp,
    shazam_bp,
)


def _session_secret() -> str:
    configured = (
        os.getenv("VINYLPI_SESSION_SECRET")
        or os.getenv("VINYLPI_API_TOKEN")
        or ""
    ).strip()
    if configured:
        return configured

    path = DATA_DIR / ".session_secret"
    try:
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    except OSError:
        pass

    value = secrets.token_urlsafe(48)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
    except OSError:
        # The fallback only affects persistence across web-process restarts.
        pass
    return value


def create_app() -> Flask:
    initialize_storage()
    app = Flask(
        __name__,
        static_folder="static",
        static_url_path="/static",
        template_folder="templates",
    )
    app.secret_key = _session_secret()
    app.config.update(
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
    )

    @app.before_request
    def _bind_browser_profile() -> None:
        session.permanent = True
        profile_id = str(session.get("vinylpi_profile_id") or "").strip()
        if profile_id and not profile_exists(profile_id):
            session.pop("vinylpi_profile_id", None)
            profile_id = ""
        g._vinylpi_profile_override_token = set_profile_storage_override(
            profile_id or "_guest"
        )

    @app.teardown_request
    def _release_browser_profile(_exc=None) -> None:
        token = getattr(g, "_vinylpi_profile_override_token", None)
        if token is not None:
            reset_profile_storage_override(token)

    for blueprint in _BLUEPRINTS:
        app.register_blueprint(blueprint)

    return app
