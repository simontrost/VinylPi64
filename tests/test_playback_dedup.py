from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from vinylpi.core.loop_state import StatsSwitchState
from vinylpi.core.loop_logic import restore_last_vinyl_song
from vinylpi.spotify_worker import _last_recognized_spotify_track_id, _poll_seconds


class PersistentPlaybackDedupTests(unittest.TestCase):
    @patch("vinylpi.core.loop_logic.get_last_source_status")
    def test_vinyl_restores_last_recognized_song_after_worker_restart(self, get_status):
        get_status.return_value = {"artist": "The Artist", "title": "The Song - Remastered 2024"}
        state = StatsSwitchState()

        restore_last_vinyl_song(state)

        self.assertEqual(state.current_song_id, ("the artist", "the song"))

    @patch("vinylpi.spotify_worker.get_last_source_status")
    def test_spotify_restores_last_track_id_after_off(self, get_status):
        get_status.return_value = {"source": "spotify", "track_id": "track-123"}
        self.assertEqual(_last_recognized_spotify_track_id(), "track-123")

    @patch("vinylpi.spotify_worker.read_config")
    def test_spotify_poll_interval_comes_from_settings(self, read_config):
        read_config.return_value = {"spotify": {"poll_seconds": 3.5}}
        self.assertEqual(_poll_seconds(), 3.5)

    @patch("vinylpi.spotify_worker.read_config")
    def test_spotify_poll_interval_has_safe_minimum(self, read_config):
        read_config.return_value = {"spotify": {"poll_seconds": 0.1}}
        self.assertEqual(_poll_seconds(), 1.0)

    @staticmethod
    def _spotify_track(track_id: str, progress_ms: int = 1000, *, is_playing: bool = True):
        return SimpleNamespace(
            track_id=track_id,
            artist="Artist",
            title=f"Song {track_id}",
            artist_id="artist-id",
            album="Album",
            cover_url=None,
            genre=None,
            duration_ms=180000,
            spotify_url=None,
            progress_ms=progress_ms,
            is_playing=is_playing,
        )

    @patch("vinylpi.spotify_worker.load_dotenv")
    @patch("vinylpi.spotify_worker._backfill_missing_genres")
    @patch("vinylpi.spotify_worker._display_track")
    @patch("vinylpi.spotify_worker.record_spotify_play")
    @patch("vinylpi.spotify_worker._last_recognized_spotify_track_id", return_value="A")
    @patch("vinylpi.spotify_worker.get_active_db_path", return_value="/tmp/profile.db")
    @patch("vinylpi.spotify_worker._poll_seconds", return_value=2.0)
    def test_spotify_pause_or_missing_response_does_not_recount_same_track(
        self, poll, db_path, last_track, record_play, display, backfill, dotenv
    ):
        from vinylpi import spotify_worker

        client = Mock()
        client.get_currently_playing.side_effect = [
            self._spotify_track("A", 1000),
            None,
            self._spotify_track("A", 1500),
        ]

        sleep_calls = 0

        def stop_after_three_sleeps(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 3:
                raise KeyboardInterrupt

        with patch("vinylpi.spotify_worker.SpotifyClient", return_value=client), patch(
            "vinylpi.spotify_worker.time.sleep", side_effect=stop_after_three_sleeps
        ):
            with self.assertRaises(KeyboardInterrupt):
                spotify_worker.main()

        record_play.assert_not_called()
        self.assertGreaterEqual(display.call_count, 1)

    @patch("vinylpi.spotify_worker.load_dotenv")
    @patch("vinylpi.spotify_worker._backfill_missing_genres")
    @patch("vinylpi.spotify_worker._display_track")
    @patch("vinylpi.spotify_worker.record_spotify_play")
    @patch("vinylpi.spotify_worker._last_recognized_spotify_track_id", return_value="A")
    @patch("vinylpi.spotify_worker.get_active_db_path", return_value="/tmp/profile.db")
    @patch("vinylpi.spotify_worker._poll_seconds", return_value=2.0)
    def test_spotify_real_a_b_a_transition_counts_b_and_a(
        self, poll, db_path, last_track, record_play, display, backfill, dotenv
    ):
        from vinylpi import spotify_worker

        client = Mock()
        client.get_currently_playing.side_effect = [
            self._spotify_track("A", 1000),
            self._spotify_track("B", 1000),
            self._spotify_track("A", 1000),
        ]

        sleep_calls = 0

        def stop_after_three_sleeps(_seconds):
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls >= 3:
                raise KeyboardInterrupt

        with patch("vinylpi.spotify_worker.SpotifyClient", return_value=client), patch(
            "vinylpi.spotify_worker.time.sleep", side_effect=stop_after_three_sleeps
        ):
            with self.assertRaises(KeyboardInterrupt):
                spotify_worker.main()

        self.assertEqual(record_play.call_count, 2)
        self.assertEqual(record_play.call_args_list[0].kwargs["track_id"], "B")
        self.assertEqual(record_play.call_args_list[1].kwargs["track_id"], "A")



if __name__ == "__main__":
    unittest.main()
