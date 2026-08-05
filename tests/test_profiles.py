from __future__ import annotations

import io
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

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

    def _configure_default_password(self, password: str = "mainpass") -> None:
        profiles.ensure_profiles_initialized()
        profiles.update_profile("default", new_password=password)

    @staticmethod
    def _avatar_png() -> bytes:
        output = io.BytesIO()
        Image.new("RGB", (400, 240), (120, 20, 90)).save(output, format="PNG")
        output.seek(0)
        return profiles.prepare_profile_avatar(output)

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
        self.assertFalse(profiles.get_active_profile()["password_configured"])
        self.assertEqual(
            json.loads((default_dir / "config.json").read_text(encoding="utf-8")),
            {"audio": {"sample_seconds": 7}},
        )
        with sqlite3.connect(default_dir / "vinylpi.db") as conn:
            value = conn.execute("SELECT value FROM migration_marker").fetchone()[0]
        self.assertEqual(value, "preserved")

    def test_default_profile_can_be_renamed_while_setting_its_first_password(self):
        profiles.ensure_profiles_initialized()

        updated = profiles.update_profile(
            "default",
            name="Simon",
            new_password="mainpass",
        )

        self.assertEqual(updated["name"], "Simon")
        self.assertTrue(updated["password_configured"])
        self.assertEqual(profiles.get_active_profile()["name"], "Simon")

    def test_profile_login_requires_the_correct_password(self):
        self._configure_default_password()
        second = profiles.create_profile("Second", "secret")

        with self.assertRaisesRegex(profiles.ProfileAuthenticationError, "Incorrect password"):
            profiles.activate_profile(second["id"], "wrong")

        active = profiles.activate_profile(second["id"], "secret")
        self.assertEqual(active["id"], second["id"])

    def test_inactive_legacy_profile_can_set_its_initial_password_once(self):
        registry = profiles.ensure_profiles_initialized()
        registry["profiles"].append(
            {
                "id": "legacy",
                "name": "Legacy",
                "password_hash": "",
                "avatar_version": None,
                "created_at": 1,
                "updated_at": 1,
            }
        )
        profiles._atomic_write_json(self.registry_path, registry)

        active = profiles.initialize_profile_password("legacy", "newpass")

        self.assertEqual(active["id"], "legacy")
        self.assertTrue(active["password_configured"])
        with self.assertRaisesRegex(ValueError, "already has a password"):
            profiles.initialize_profile_password("legacy", "another")

        profiles.logout_to_guest()
        logged_in = profiles.activate_profile("legacy", "newpass")
        self.assertEqual(logged_in["name"], "Legacy")

    def test_profiles_keep_config_and_statistics_separate(self):
        self._configure_default_password()
        runtime.write_config({"audio": {"sample_seconds": 5}})
        stats_db.update_song_stats("Default Artist", "Default Song")

        second = profiles.create_profile("Second", "secondpass", copy_current_settings=False)
        profiles.activate_profile(second["id"], "secondpass")
        runtime.clear_config_cache()

        self.assertEqual(runtime.read_config()["audio"]["sample_seconds"], 4)
        self.assertEqual(stats_db.get_ranked_stats()["top_songs"], [])

        runtime.write_config({"audio": {"sample_seconds": 9}})
        stats_db.update_song_stats("Second Artist", "Second Song")

        profiles.activate_profile("default", "mainpass")
        runtime.clear_config_cache()
        default_stats = stats_db.get_ranked_stats()

        self.assertEqual(runtime.read_config()["audio"]["sample_seconds"], 5)
        self.assertEqual(default_stats["top_songs"][0]["artist"], "Default Artist")
        self.assertNotIn("Second Artist", [item["artist"] for item in default_stats["top_songs"]])

    def test_logout_requires_a_password_and_uses_separate_guest_storage(self):
        profiles.ensure_profiles_initialized()
        with self.assertRaisesRegex(profiles.ProfilePasswordNotConfiguredError, "Set a password"):
            profiles.logout_to_guest()

        profiles.update_profile("default", new_password="mainpass")
        runtime.write_config({"audio": {"channels": 2}})
        stats_db.update_song_stats("Profile Artist", "Profile Song")

        guest = profiles.logout_to_guest(copy_current_settings=True)
        runtime.clear_config_cache()

        self.assertTrue(guest["is_guest"])
        self.assertEqual(runtime.read_config()["audio"]["channels"], 2)
        self.assertEqual(stats_db.get_ranked_stats()["top_songs"], [])

        stats_db.update_song_stats("Guest Artist", "Guest Song")
        profiles.activate_profile("default", "mainpass")
        runtime.clear_config_cache()

        songs = stats_db.get_ranked_stats()["top_songs"]
        self.assertEqual(songs[0]["artist"], "Profile Artist")
        self.assertNotIn("Guest Artist", [item["artist"] for item in songs])

    def test_profile_avatar_is_saved_and_exposed_without_password_hash(self):
        self._configure_default_password()
        second = profiles.create_profile("Picture", "secret", avatar_png=self._avatar_png())
        listed = profiles.list_profiles()
        public = next(item for item in listed["profiles"] if item["id"] == second["id"])

        self.assertTrue((self.profiles_dir / second["id"] / "avatar.png").is_file())
        self.assertIn("/avatar?v=", public["avatar_url"])
        self.assertNotIn("password_hash", public)

    def test_default_and_active_profiles_cannot_be_deleted(self):
        self._configure_default_password()
        second = profiles.create_profile("Second", "secret")
        profiles.activate_profile(second["id"], "secret")

        with self.assertRaisesRegex(ValueError, "active profile"):
            profiles.delete_profile(second["id"])
        with self.assertRaisesRegex(ValueError, "default profile"):
            profiles.delete_profile("default")


if __name__ == "__main__":
    unittest.main()
