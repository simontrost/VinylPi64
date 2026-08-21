import unittest

from vinylpi.integrations.spotify_client import SpotifyClient


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


if __name__ == "__main__":
    unittest.main()
