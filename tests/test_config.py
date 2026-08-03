from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from vinylpi.config import runtime
from vinylpi.config.config_loader import CONFIG_DEFAULTS, deep_update, load_config


class ConfigLoaderTests(unittest.TestCase):
    def test_deep_update_merges_nested_values_without_dropping_defaults(self):
        base = {"audio": {"sample_rate": 44100, "channels": 1}, "debug": {"logs": True}}

        result = deep_update(base, {"audio": {"channels": 2}})

        self.assertIs(result, base)
        self.assertEqual(result["audio"], {"sample_rate": 44100, "channels": 2})
        self.assertTrue(result["debug"]["logs"])

    def test_load_config_merges_user_values_with_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(json.dumps({"audio": {"sample_seconds": 7}}), encoding="utf-8")

            cfg = load_config(path)

        self.assertEqual(cfg["audio"]["sample_seconds"], 7)
        self.assertEqual(cfg["audio"]["sample_rate"], CONFIG_DEFAULTS["audio"]["sample_rate"])
        self.assertIn("image", cfg)

    def test_load_config_returns_independent_defaults_for_missing_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            first = load_config(missing)
            first["audio"]["channels"] = 99
            second = load_config(missing)

        self.assertEqual(second["audio"]["channels"], CONFIG_DEFAULTS["audio"]["channels"])

    def test_load_config_ignores_invalid_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text("{invalid", encoding="utf-8")

            cfg = load_config(path)

        self.assertEqual(cfg, CONFIG_DEFAULTS)

    def test_load_config_removes_legacy_discogs_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "config.json"
            path.write_text(
                json.dumps({"discogs": {"token": "secret", "username": "collector"}}),
                encoding="utf-8",
            )

            cfg = load_config(path)

        self.assertNotIn("token", cfg["discogs"])
        self.assertEqual(cfg["discogs"]["username"], "collector")


class RuntimeConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.config_path = Path(self.temp_dir.name) / "data" / "config.json"
        self.path_patch = patch.object(runtime, "CONFIG_PATH", self.config_path)
        self.path_patch.start()
        runtime._CACHE.update({"mtime": None, "cfg": None, "ts": 0.0})

    def tearDown(self):
        self.path_patch.stop()
        runtime._CACHE.update({"mtime": None, "cfg": None, "ts": 0.0})
        self.temp_dir.cleanup()

    def test_write_config_merges_partial_update_and_writes_valid_json(self):
        updated = runtime.write_config({"image": {"uppercase": False}})

        on_disk = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.assertFalse(updated["image"]["uppercase"])
        self.assertEqual(on_disk, updated)
        self.assertEqual(updated["audio"]["sample_rate"], CONFIG_DEFAULTS["audio"]["sample_rate"])
        self.assertFalse(self.config_path.with_suffix(".json.tmp").exists())

    def test_read_config_returns_copy_not_mutable_cache_reference(self):
        runtime.write_config({"debug": {"logs": False}})

        first = runtime.read_config()
        first["debug"]["logs"] = True
        second = runtime.read_config()

        self.assertFalse(second["debug"]["logs"])

    def test_reset_config_restores_defaults(self):
        runtime.write_config({"audio": {"channels": 2}})

        reset = runtime.reset_config()

        self.assertEqual(reset, CONFIG_DEFAULTS)
        self.assertEqual(json.loads(self.config_path.read_text(encoding="utf-8")), CONFIG_DEFAULTS)

    def test_fallback_path_helpers_round_trip(self):
        runtime.set_fallback_image_path("assets/fallback/custom.png")
        runtime.set_fallback_image_path(
            "assets/fallback/custom_turn.png",
            kind="turn",
        )

        self.assertEqual(runtime.get_current_fallback_path(), "assets/fallback/custom.png")
        self.assertEqual(
            runtime.get_current_fallback_path(kind="turn"),
            "assets/fallback/custom_turn.png",
        )

    def test_invalid_fallback_kind_is_rejected(self):
        with self.assertRaises(ValueError):
            runtime.get_current_fallback_path(kind="other")


if __name__ == "__main__":
    unittest.main()
