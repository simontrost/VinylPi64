from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

try:
    import werkzeug  # noqa: F401
except ModuleNotFoundError:
    werkzeug = None

if werkzeug is not None:
    from vinylpi.web.services.uploads import _safe_child_path, build_font_preview


@unittest.skipIf(werkzeug is None, "Werkzeug is not installed")
class UploadPathTests(unittest.TestCase):
    def test_safe_child_path_allows_spaces_but_rejects_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            expected = directory / "Pixel Millennium.ttf"
            expected.touch()

            self.assertEqual(_safe_child_path(directory, expected.name), expected.resolve())
            self.assertIsNone(_safe_child_path(directory, "../Pixel Millennium.ttf"))
            self.assertIsNone(_safe_child_path(directory, "subdir/font.ttf"))

    def test_font_preview_supports_existing_font_filename_with_spaces(self):
        source = Path(__file__).resolve().parents[1] / "assets" / "fonts" / "Pixel5.ttf"
        self.assertTrue(source.is_file())

        with tempfile.TemporaryDirectory() as tmp:
            fonts_dir = Path(tmp)
            target = fonts_dir / "Pixel Millennium.ttf"
            shutil.copyfile(source, target)

            with patch("vinylpi.web.services.uploads.FONTS_DIR", fonts_dir):
                preview = build_font_preview(target.name)

            self.assertIsNotNone(preview)
            self.assertTrue(preview.getvalue().startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
