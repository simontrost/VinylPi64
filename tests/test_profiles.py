from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from vinylpi import paths, profiles
from vinylpi.config import runtime
from vinylpi.core import database, stats_db, storage


class ProfileStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.data_dir = self.root / "data"
        self.profiles_dir = self.data_dir / "profiles"
        self.registry_path = self.data_dir / "profiles.json"
        self.legacy_config = self.data_dir / "config.json"
        self.legacy_db = self.data_dir / "vinylpi.db"

        patches = (
            patch.object(paths, "DATA_DIR", self.data_dir),
            patch.object(paths, "PROFILES_DIR", self.profiles_dir),
            patch.object(paths, "PROFILE_REGISTRY_PATH", self.registry_path),
            patch.object(profiles, "DATA_DIR", self.data_dir),
            patch.object(profiles, "PROFILES_DIR", self.profiles_dir),
            patch.object(profiles, "PROFILE_REGISTRY_PATH", self.registry_path),
            patch.object(profiles, "CONFIG_PATH", self.legacy_config),
            patch.object(profiles, "DB_PATH", self.legacy_db),
        )
        self.patchers = patches
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

        profiles._CACHE.update({"mtime_ns": None, "registry": None})
        runtime.clear_config_cache()
        database._INITIALIZED_PATHS.clear()
        storage._initialized_paths.clear()

    def tearDown(self):
        profiles._CACHE.update({"mtime_ns": None, "registry": None})
        runtime.clear_config_cache()
        database._INITIALIZED_PATHS.clear()
        storage._initialized_paths.clear()
        self.temp_dir.cleanup()

    def test_first_start_migrates_existing_config_and_database_to_default_profile(self):
        self.data_dir.mkdir(parents=True)
        self.legacy_config.write_text(
            json.dumps({"audio": {"sample_seconds": 7}}),
            encoding="utf-8",
        )
        with sqlite3.connect(self.legacy_db) as conn:
            conn.execute("CREATE TABLE migration_marker(value TEXT)")
            conn.execute("INSERT INTO migration_marker(value) VALUES('preserved')")

        registry = profiles.ensure_profiles_initialized()
        default_dir = self.profiles_dir / "default"

        self.assertEqual(registry["active_profile_id"], "default")
        self.assertEqual(
            json.loads((default_dir / "config.json").read_text(encoding="utf-8")),
            {"audio": {"sample_seconds": 7}},
        )
        with sqlite3.connect(default_dir / "vinylpi.db") as conn:
            value = conn.execute("SELECT value FROM migration_marker").fetchone()[0]
        self.assertEqual(value, "preserved")

    def test_profiles_keep_config_and_statistics_separate(self):
        profiles.ensure_profiles_initialized()
        runtime.write_config({"audio": {"sample_seconds": 5}})
        stats_db.update_song_stats("Default Artist", "Default Song")

        second = profiles.create_profile("Second", copy_current_settings=False)
        profiles.activate_profile(second["id"])
        runtime.clear_config_cache()

        self.assertEqual(runtime.read_config()["audio"]["sample_seconds"], 4)
        self.assertEqual(stats_db.get_ranked_stats()["top_songs"], [])

        runtime.write_config({"audio": {"sample_seconds": 9}})
        stats_db.update_song_stats("Second Artist", "Second Song")

        profiles.activate_profile("default")
        runtime.clear_config_cache()
        default_stats = stats_db.get_ranked_stats()

        self.assertEqual(runtime.read_config()["audio"]["sample_seconds"], 5)
        self.assertEqual(default_stats["top_songs"][0]["artist"], "Default Artist")
        self.assertNotIn("Second Artist", [item["artist"] for item in default_stats["top_songs"]])

    def test_logout_uses_separate_guest_storage_and_preserves_profile_data(self):
        profiles.ensure_profiles_initialized()
        runtime.write_config({"audio": {"channels": 2}})
        stats_db.update_song_stats("Profile Artist", "Profile Song")

        guest = profiles.logout_to_guest(copy_current_settings=True)
        runtime.clear_config_cache()

        self.assertTrue(guest["is_guest"])
        self.assertEqual(runtime.read_config()["audio"]["channels"], 2)
        self.assertEqual(stats_db.get_ranked_stats()["top_songs"], [])

        stats_db.update_song_stats("Guest Artist", "Guest Song")
        profiles.activate_profile("default")
        runtime.clear_config_cache()

        songs = stats_db.get_ranked_stats()["top_songs"]
        self.assertEqual(songs[0]["artist"], "Profile Artist")
        self.assertNotIn("Guest Artist", [item["artist"] for item in songs])

    def test_default_and_active_profiles_cannot_be_deleted(self):
        profiles.ensure_profiles_initialized()
        second = profiles.create_profile("Second")
        profiles.activate_profile(second["id"])

        with self.assertRaisesRegex(ValueError, "active profile"):
            profiles.delete_profile(second["id"])
        with self.assertRaisesRegex(ValueError, "default profile"):
            profiles.delete_profile("default")


if __name__ == "__main__":
    unittest.main()
