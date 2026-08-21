import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from vinylpi.integrations.spotify_client import (
    SpotifyClient,
    clear_spotify_account,
    get_spotify_account,
    save_spotify_account,
)


class SpotifyPayloadTests(unittest.TestCase):
    def test_parse_currently_playing_track(self):
        payload = {
            "is_playing": True,
            "progress_ms": 42_000,
            "device": {"name": "Living Room"},
            "item": {
                "type": "track",
                "id": "spotify-track-id",
                "name": "Test Song",
                "duration_ms": 180_000,
                "artists": [{"id": "artist-id", "name": "Test Artist"}],
                "album": {
                    "name": "Test Album",
                    "images": [{"url": "https://example.invalid/cover.jpg"}],
                },
                "external_urls": {"spotify": "https://open.spotify.com/track/spotify-track-id"},
            },
        }

        track = SpotifyClient.parse_currently_playing(payload)

        self.assertIsNotNone(track)
        self.assertEqual(track.track_id, "spotify-track-id")
        self.assertEqual(track.title, "Test Song")
        self.assertEqual(track.artist, "Test Artist")
        self.assertEqual(track.artist_id, "artist-id")
        self.assertEqual(track.album, "Test Album")
        self.assertEqual(track.cover_url, "https://example.invalid/cover.jpg")
        self.assertEqual(track.duration_ms, 180_000)
        self.assertEqual(track.progress_ms, 42_000)
        self.assertTrue(track.is_playing)
        self.assertEqual(track.device_name, "Living Room")

    def test_parse_ignores_non_track_item(self):
        self.assertIsNone(
            SpotifyClient.parse_currently_playing({"item": {"type": "episode", "id": "episode"}})
        )


class SpotifyProfileAccountTests(unittest.TestCase):
    def test_refresh_tokens_are_kept_separate_by_profile_database(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            first = Path(temp_dir) / "first.db"
            second = Path(temp_dir) / "second.db"

            save_spotify_account("token-one", display_name="Simon", db_path=first)
            save_spotify_account("token-two", display_name="Other", db_path=second)

            self.assertEqual(get_spotify_account(first)["display_name"], "Simon")
            self.assertEqual(get_spotify_account(second)["display_name"], "Other")

            clear_spotify_account(first)
            self.assertIsNone(get_spotify_account(first))
            self.assertEqual(get_spotify_account(second)["display_name"], "Other")

    @patch.dict("os.environ", {"LAST_FM_API_KEY": "lastfm-key"}, clear=False)
    def test_lastfm_tags_are_used_when_spotify_genre_is_empty(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            client = SpotifyClient(profile_db_path=Path(temp_dir) / "profile.db")
            spotify_response = Mock(status_code=200)
            spotify_response.json.return_value = {"genres": []}
            lastfm_response = Mock(status_code=200)
            lastfm_response.json.return_value = {
                "toptags": {"tag": [{"name": "indie rock"}]}
            }

            with patch.object(client, "_api_get", return_value=spotify_response), patch(
                "vinylpi.integrations.spotify_client.requests.get",
                return_value=lastfm_response,
            ):
                genre = client.get_artist_genre(
                    "artist-id",
                    artist="Arctic Monkeys",
                    title="Snap Out Of It",
                )

            self.assertEqual(genre, "indie rock")


if __name__ == "__main__":
    unittest.main()
