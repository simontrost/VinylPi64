from __future__ import annotations

import unittest
from unittest.mock import patch

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
    @patch("vinylpi.web.services.source._restore_source_display")
    @patch("vinylpi.web.services.source.spotify.stop")
    @patch("vinylpi.web.services.source.set_runtime_profile")
    @patch("vinylpi.web.services.source.get_runtime_profile")
    @patch("vinylpi.web.services.source.get_active_storage_key", return_value="simon")
    @patch("vinylpi.web.services.source.get_mode", return_value="off")
    def test_profile_claims_mutex_when_starting_vinyl(
        self,
        _get_mode,
        _viewer,
        runtime_profile,
        set_runtime_profile,
        _spotify_stop,
        _restore,
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
        recognizer_start.assert_called_once()


if __name__ == "__main__":
    unittest.main()
