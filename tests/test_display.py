from __future__ import annotations

import unittest
from pathlib import Path

from PIL import Image, ImageChops

from vinylpi.core.display import _overlay_side_letter


class SideFlipImageTests(unittest.TestCase):
    def setUp(self):
        self.template_path = Path("assets/fallback/turn_record.png")

    def test_target_side_letter_is_inserted_only_in_badge_slot(self):
        template = Image.open(self.template_path).convert("RGB")

        side_b = _overlay_side_letter(template.copy(), "B")
        side_d = _overlay_side_letter(template.copy(), "D")

        difference = ImageChops.difference(side_b, side_d)
        bbox = difference.getbbox()
        self.assertIsNotNone(bbox)
        self.assertGreaterEqual(bbox[0], 38)
        self.assertGreaterEqual(bbox[1], 54)
        self.assertLessEqual(bbox[2], 43)
        self.assertLessEqual(bbox[3], 59)

    def test_multi_disc_side_f_is_rendered(self):
        template = Image.open(self.template_path).convert("RGB")
        side_f = _overlay_side_letter(template.copy(), "F")

        slot = side_f.crop((38, 54, 43, 59))
        self.assertIsNotNone(slot.getbbox())
        self.assertNotEqual(slot.tobytes(), template.crop((38, 54, 43, 59)).tobytes())


if __name__ == "__main__":
    unittest.main()
