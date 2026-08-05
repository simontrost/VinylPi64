from __future__ import annotations

import io
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from vinylpi.core import database, stats_db
from vinylpi.web.services.stats import build_share_card_image

warnings.filterwarnings("ignore", category=ResourceWarning, message="unclosed database.*")


class StatsDatabaseTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "vinylpi-test.db"
        self.db_patch = patch.object(database, "DB_PATH", self.db_path)
        self.db_patch.start()
        database._INITIALIZED_PATHS.clear()

    def tearDown(self):
        database._INITIALIZED_PATHS.clear()
        self.db_patch.stop()
        self.temp_dir.cleanup()

    def test_init_db_creates_schema_and_version(self):
        database.init_db()

        with database.get_connection() as conn:
            tables = {
                row["name"]
                for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            version = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()["value"]

        self.assertIn("songs", tables)
        self.assertIn("current_status", tables)
        self.assertEqual(version, str(database.SCHEMA_VERSION))

    def test_song_artist_album_and_genre_statistics_round_trip(self):
        stats_db.update_song_stats(
            "Artist",
            "Song",
            "Album",
            "https://example.test/cover.jpg",
            "Rock",
            "track-1",
            "artist-1",
            180000,
        )
        stats_db.update_song_stats("Artist", "Song", "Album")
        stats_db.increment_album_session("Album")
        stats_db.add_listening_seconds(180)

        ranked = stats_db.get_ranked_stats(limit=10)

        self.assertEqual(ranked["top_songs"][0]["count"], 2)
        self.assertEqual(ranked["top_artists"][0], {"name": "Artist", "count": 2})
        self.assertEqual(ranked["top_albums"][0], {"name": "Album", "count": 1})
        self.assertEqual(ranked["top_genres"][0], {"name": "Rock", "count": 2})
        self.assertEqual(ranked["total_minutes_listened"], 3)
        self.assertEqual(ranked["metadata_coverage"]["songs_with_shazam_id"], 1)

    def test_duration_cache_round_trip_is_case_insensitive(self):
        stats_db.upsert_duration_cache(
            "Artist",
            "Song",
            "Album",
            240000,
            4.0,
            "shazam",
            fetched_at=123,
        )

        cached = stats_db.get_duration_cache("artist", "song")

        self.assertEqual(cached["ms"], 240000)
        self.assertEqual(cached["minutes"], 4.0)
        self.assertEqual(cached["source"], "shazam")
        self.assertEqual(cached["ts"], 123)

    def test_current_status_round_trip_includes_side_flip_fields(self):
        stats_db.write_current_status(
            {
                "artist": "Artist",
                "title": "Song",
                "side_flip_prompt_active": True,
                "side_flip_from_side": "A",
                "side_flip_to_side": "B",
                "side_flip_next_title": "Next",
                "side_flip_next_position": "B1",
            }
        )

        status = stats_db.get_current_status()

        self.assertEqual(status["artist"], "Artist")
        self.assertEqual(status["side_flip_prompt_active"], 1)
        self.assertEqual(status["side_flip_to_side"], "B")
        self.assertEqual(status["side_flip_next_position"], "B1")

    def test_database_has_statistics_changes_after_update(self):
        self.assertFalse(database.database_has_statistics())

        stats_db.update_song_stats("Artist", "Song")

        self.assertTrue(database.database_has_statistics())

    def test_share_card_generation_returns_valid_png(self):
        payload = {
            "profile_name": "Simon",
            "total_minutes_listened": 53623,
            "top_genre": "Indie",
            "top_artists": [
                {"name": "Foo Fighters", "count": 12},
                {"name": "The Strokes", "count": 10},
            ],
            "top_albums": [
                {"name": "The Colour And The Shape", "count": 7},
                {"name": "Is This It", "count": 5},
            ],
            "top_album_covers": [],
        }

        png_bytes = build_share_card_image(payload)

        self.assertTrue(png_bytes.startswith(b"\x89PNG"))
        with Image.open(io.BytesIO(png_bytes)) as image:
            self.assertEqual(image.size, (1080, 1920))
            self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
