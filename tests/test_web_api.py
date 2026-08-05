from __future__ import annotations

import os
import unittest
from unittest.mock import patch

try:
    from flask import Flask
except ModuleNotFoundError:  # Allows partial local test runs without optional CI dependencies.
    Flask = None

if Flask is not None:
    from vinylpi.web.routes.config_api import config_bp
    from vinylpi.web.routes.genius_api import genius_bp
    from vinylpi.web.routes.pixoo_api import pixoo_bp
    from vinylpi.web.routes.profiles_api import profiles_bp
    from vinylpi.web.routes.status_api import status_bp
    from vinylpi.web.routes.uploads_api import uploads_bp


@unittest.skipIf(Flask is None, "Flask is not installed")
class WebApiTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True)
        for blueprint in (config_bp, genius_bp, pixoo_bp, profiles_bp, status_bp, uploads_bp):
            app.register_blueprint(blueprint)
        self.client = app.test_client()

    @patch.dict(os.environ, {"DISCOGS_API_TOKEN": "secret"})
    @patch("vinylpi.web.routes.config_api.read_config")
    def test_config_get_exposes_only_token_configured_flag(self, read_config):
        read_config.return_value = {"discogs": {"token": "legacy", "username": "collector"}}

        response = self.client.get("/api/config")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertNotIn("token", data["discogs"])
        self.assertTrue(data["discogs"]["token_configured"])

    @patch("vinylpi.web.routes.config_api.request_display_refresh")
    @patch("vinylpi.web.routes.config_api.write_config")
    @patch("vinylpi.web.routes.config_api.read_config")
    def test_config_post_strips_sensitive_fields_and_refreshes_changed_display(
        self,
        read_config,
        write_config,
        request_refresh,
    ):
        read_config.return_value = {"image": {"uppercase": True}}
        write_config.return_value = {"image": {"uppercase": False}}

        response = self.client.post(
            "/api/config",
            json={
                "image": {"uppercase": False},
                "discogs": {"token": "secret", "token_configured": True, "username": "collector"},
            },
        )

        self.assertEqual(response.status_code, 200)
        written = write_config.call_args.args[0]
        self.assertNotIn("token", written["discogs"])
        self.assertNotIn("token_configured", written["discogs"])
        self.assertEqual(written["discogs"]["username"], "collector")
        request_refresh.assert_called_once_with()
        self.assertTrue(response.get_json()["display_refresh_requested"])

    def test_pixoo_brightness_requires_value(self):
        response = self.client.post("/api/pixoo/brightness", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "missing brightness")

    @patch("vinylpi.web.routes.pixoo_api.pixoo.set_brightness")
    def test_pixoo_brightness_calls_service(self, set_brightness):
        response = self.client.post("/api/pixoo/brightness", json={"brightness": "75"})

        self.assertEqual(response.status_code, 200)
        set_brightness.assert_called_once_with(75)

    def test_play_remote_requires_file_id(self):
        response = self.client.post("/api/pixoo/play-remote", json={})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "missing file_id")

    @patch("vinylpi.web.routes.status_api.get_current_status", return_value=None)
    def test_status_endpoint_reports_empty_state(self, get_status):
        response = self.client.get("/api/status")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": False, "status": None})

    @patch("vinylpi.web.routes.status_api.get_current_status")
    def test_status_endpoint_returns_current_status(self, get_status):
        get_status.return_value = {"artist": "Artist", "title": "Song"}

        response = self.client.get("/api/status")

        self.assertEqual(response.get_json(), {"artist": "Artist", "title": "Song"})

    def test_lyrics_endpoint_requires_artist_and_title(self):
        response = self.client.get("/api/lyrics?artist=Artist")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "missing_params")

    @patch("vinylpi.web.routes.genius_api.get_lyrics")
    def test_lyrics_endpoint_returns_service_payload(self, get_lyrics):
        get_lyrics.return_value = {"ok": True, "lyrics": "Words"}

        response = self.client.get("/api/lyrics?artist=Artist&title=Song")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json(), {"ok": True, "lyrics": "Words"})
        get_lyrics.assert_called_once_with("Artist", "Song")

    def test_fallback_gallery_rejects_unknown_kind(self):
        response = self.client.get("/api/fallback-images?kind=unknown")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "invalid kind")

    @patch("vinylpi.web.routes.uploads_api.list_fallback_images")
    def test_turn_record_gallery_passes_kind_to_service(self, list_images):
        list_images.return_value = []

        response = self.client.get("/api/fallback-images?kind=turn")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["kind"], "turn")
        list_images.assert_called_once_with(kind="turn")


    @patch("vinylpi.web.routes.uploads_api.list_fonts")
    def test_font_gallery_returns_available_fonts(self, list_fonts_mock):
        list_fonts_mock.return_value = [
            {
                "filename": "vinylpixel.ttf",
                "name": "vinylpixel",
                "path": "assets/fonts/vinylpixel.ttf",
                "preview_url": "/api/font-preview/vinylpixel.ttf",
                "is_current": True,
                "deletable": False,
            }
        ]

        response = self.client.get("/api/fonts")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()["ok"])
        self.assertEqual(response.get_json()["fonts"][0]["filename"], "vinylpixel.ttf")

    @patch("vinylpi.web.routes.uploads_api.build_font_preview", return_value=None)
    def test_missing_font_preview_returns_404(self, build_preview):
        response = self.client.get("/api/font-preview/missing.ttf")

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.get_json()["error"], "font not found or invalid")


    @patch("vinylpi.web.routes.profiles_api.list_profiles")
    def test_profiles_endpoint_returns_active_profile(self, list_profiles_mock):
        list_profiles_mock.return_value = {
            "active_profile": {"id": "default", "name": "Default", "is_guest": False},
            "profiles": [{"id": "default", "name": "Default", "is_active": True}],
        }

        response = self.client.get("/api/profiles")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["active_profile"]["name"], "Default")

    @patch("vinylpi.web.routes.profiles_api.SYNC_MANAGER.is_syncing", return_value=False)
    @patch("vinylpi.web.routes.profiles_api._switch_profile")
    @patch("vinylpi.web.routes.profiles_api.create_profile")
    def test_create_profile_can_copy_settings_and_activate(
        self, create_profile_mock, switch_profile_mock, is_syncing_mock
    ):
        create_profile_mock.return_value = {"id": "abc", "name": "Simon"}
        switch_profile_mock.return_value = (
            {"id": "abc", "name": "Simon", "is_guest": False},
            True,
        )

        response = self.client.post(
            "/api/profiles",
            json={"name": "Simon", "copy_current_settings": True, "activate": True},
        )

        self.assertEqual(response.status_code, 201)
        create_profile_mock.assert_called_once_with("Simon", copy_current_settings=True)
        self.assertTrue(response.get_json()["activated"])


if __name__ == "__main__":
    unittest.main()
