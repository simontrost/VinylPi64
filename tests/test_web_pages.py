from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask
except ModuleNotFoundError:  # Allows partial local test runs without web dependencies.
    Flask = None

if Flask is not None:
    from vinylpi.web.app import create_app


@unittest.skipIf(Flask is None, "Flask is not installed")
class WebPageStructureTests(unittest.TestCase):
    def setUp(self):
        storage_patcher = patch("vinylpi.web.app.initialize_storage")
        self.addCleanup(storage_patcher.stop)
        storage_patcher.start()

        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def test_all_page_templates_render(self):
        pages = {
            "/": "Dashboard",
            "/index.html": "Dashboard",
            "/settings.html": "Settings",
            "/pixoo.html": "Pixoo",
            "/stats.html": "Statistics",
            "/about.html": "About",
        }

        for route, heading in pages.items():
            with self.subTest(route=route):
                response = self.client.get(route)
                self.assertEqual(response.status_code, 200)
                self.assertIn(heading.encode(), response.data)
                self.assertIn(b"/static/css/base.css", response.data)

    def test_page_specific_assets_are_served_from_static_tree(self):
        assets = (
            "/static/css/base.css",
            "/static/css/pages/dashboard.css",
            "/static/js/pages/dashboard.js",
            "/static/js/profile.js",
            "/static/images/logo.png",
            "/static/icons/favicon.svg",
            "/static/site.webmanifest",
        )

        for asset in assets:
            with self.subTest(asset=asset):
                self.assertEqual(self.client.get(asset).status_code, 200)

    def test_navigation_marks_only_current_page_active(self):
        response = self.client.get("/settings.html")
        html = response.get_data(as_text=True)

        self.assertIn('href="/settings.html" class="active" aria-current="page"', html)
        self.assertNotIn('href="/" class="nav-center active"', html)

    def test_dashboard_contains_discogs_add_release_link(self):
        response = self.client.get("/")
        html = response.get_data(as_text=True)

        self.assertIn('id="discogs-add-link"', html)
        self.assertIn('Add to Discogs', html)
        self.assertIn('target="_blank"', html)


    def test_settings_contains_profile_specific_spotify_section(self):
        response = self.client.get("/settings.html")
        html = response.get_data(as_text=True)

        self.assertIn('id="section-spotify"', html)
        self.assertIn('id="spotifySettingsConnect"', html)
        self.assertIn('Profile account connection', html)

    def test_stats_page_contains_share_button(self):
        response = self.client.get("/stats.html")
        html = response.get_data(as_text=True)

        self.assertIn('id="stats-share-button"', html)
        self.assertIn('Share', html)


if __name__ == "__main__":
    unittest.main()
