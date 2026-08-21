from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from vinylpi.web.services import source


class SourceMutexTests(unittest.TestCase):
    @patch("vinylpi.web.services.source.get_runtime_profile")
    @patch("vinylpi.web.services.source.get_active_storage_key", return_value="test")
    @patch("vinylpi.web.services.source.get_mode", return_value="vinyl")
    def test_other_profile_cannot_change_active_playback(
        self,
        _get_mode,
        _viewer,
        runtime_profile,
    ):
        runtime_profile.return_value = {
            "storage_key": "simon",
            "name": "Simon",
            "is_guest": False,
        }

        with self.assertRaises(source.SourceBusyError) as caught:
            source.set_mode("off")

        self.assertEqual(caught.exception.owner_name, "Simon")

    @patch("vinylpi.web.services.source.get_status", return_value={"mode": "vinyl"})
    @patch("vinylpi.web.services.source.recognizer.start", return_value=True)
    @patch("vinylpi.web.services.source.show_fallback_image", return_value=True)
    @patch("vinylpi.web.services.source.spotify.stop")
    @patch("vinylpi.web.services.source.set_runtime_profile")
    @patch("vinylpi.web.services.source.get_runtime_profile")
    @patch("vinylpi.web.services.source.get_active_storage_key", return_value="simon")
    @patch("vinylpi.web.services.source.get_mode", return_value="off")
    def test_profile_claims_mutex_when_starting_vinyl_without_replaying_cached_track(
        self,
        _get_mode,
        _viewer,
        runtime_profile,
        set_runtime_profile,
        spotify_stop,
        show_fallback,
        recognizer_start,
        _get_status,
    ):
        runtime_profile.return_value = {
            "storage_key": "_guest",
            "name": "Guest",
            "is_guest": True,
        }

        result = source.set_mode("vinyl")

        self.assertEqual(result["mode"], "vinyl")
        set_runtime_profile.assert_called_once_with("simon")
        spotify_stop.assert_called_once_with()
        show_fallback.assert_called_once_with()
        recognizer_start.assert_called_once()

        # Regression: source.py must not own a persistent Pixoo marquee. The
        # actual recognizer subprocess is the only process allowed to scroll a
        # Vinyl track, otherwise its frames fight the remembered dashboard song.
        self.assertFalse(hasattr(source, "_restore_source_display"))

    @patch("vinylpi.web.services.source.get_status", return_value={"mode": "vinyl"})
    @patch("vinylpi.web.services.source.show_fallback_image")
    @patch("vinylpi.web.services.source.recognizer.start")
    @patch("vinylpi.web.services.source.spotify.stop")
    @patch("vinylpi.web.services.source.get_runtime_profile")
    @patch("vinylpi.web.services.source.get_active_storage_key", return_value="simon")
    @patch("vinylpi.web.services.source.get_mode", return_value="vinyl")
    def test_reselecting_active_vinyl_is_noop_and_does_not_blank_pixoo(
        self,
        _get_mode,
        _viewer,
        runtime_profile,
        spotify_stop,
        recognizer_start,
        show_fallback,
        _get_status,
    ):
        runtime_profile.return_value = {
            "storage_key": "simon",
            "name": "Simon",
            "is_guest": False,
        }

        result = source.set_mode("vinyl")

        self.assertEqual(result["mode"], "vinyl")
        spotify_stop.assert_not_called()
        recognizer_start.assert_not_called()
        show_fallback.assert_not_called()

    @patch("vinylpi.web.services.source.get_status", return_value={"mode": "off"})
    @patch("vinylpi.web.services.source.set_runtime_profile")
    @patch("vinylpi.web.services.source.show_fallback_image", return_value=True)
    @patch("vinylpi.web.services.source.recognizer.stop")
    @patch("vinylpi.web.services.source.spotify.stop")
    @patch("vinylpi.web.services.source.get_runtime_profile")
    @patch("vinylpi.web.services.source.get_active_storage_key", return_value="simon")
    @patch("vinylpi.web.services.source.get_mode", return_value="off")
    def test_off_resends_fallback_even_when_already_off(
        self,
        _get_mode,
        _viewer,
        runtime_profile,
        spotify_stop,
        recognizer_stop,
        show_fallback,
        set_runtime_profile,
        _get_status,
    ):
        runtime_profile.return_value = {
            "storage_key": "_guest",
            "name": "Guest",
            "is_guest": True,
        }

        source.set_mode("off")

        spotify_stop.assert_called_once_with()
        recognizer_stop.assert_called_once_with()
        show_fallback.assert_called_once_with()
        set_runtime_profile.assert_called_once_with(None)

    @patch("vinylpi.web.services.source.get_status", return_value={"mode": "spotify"})
    @patch("vinylpi.web.services.source.spotify.start", return_value=True)
    @patch("vinylpi.web.services.source.show_fallback_image", return_value=True)
    @patch("vinylpi.web.services.source.recognizer.stop")
    @patch("vinylpi.web.services.source.SpotifyClient")
    @patch("vinylpi.web.services.source.spotify_env_status", return_value={"configured": True, "connected": True})
    @patch("vinylpi.web.services.source.set_runtime_profile")
    @patch("vinylpi.web.services.source.get_runtime_profile")
    @patch("vinylpi.web.services.source.get_active_storage_key", return_value="simon")
    @patch("vinylpi.web.services.source.get_mode", return_value="vinyl")
    def test_switch_to_spotify_uses_fallback_until_worker_confirms_current_track(
        self,
        _get_mode,
        _viewer,
        runtime_profile,
        _set_runtime,
        _env_status,
        spotify_client_cls,
        recognizer_stop,
        show_fallback,
        spotify_start,
        _get_status,
    ):
        runtime_profile.return_value = {
            "storage_key": "simon",
            "name": "Simon",
            "is_guest": False,
        }
        spotify_client_cls.return_value.get_currently_playing.return_value = MagicMock()

        result = source.set_mode("spotify")

        self.assertEqual(result["mode"], "spotify")
        recognizer_stop.assert_called_once_with()
        show_fallback.assert_called_once_with()
        spotify_start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
