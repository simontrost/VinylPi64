from __future__ import annotations

import base64
import unittest
from unittest.mock import Mock

from PIL import Image

from vinylpi.integrations.divoom_api import PixooClient, PixooError


class PixooEncodingTests(unittest.TestCase):
    def test_image_to_rgb_bytes_uses_row_major_rgb_order(self):
        image = Image.new("RGB", (16, 16), (0, 0, 0))
        image.putpixel((0, 0), (1, 2, 3))
        image.putpixel((1, 0), (4, 5, 6))

        raw = PixooClient._image_to_rgb_bytes(image)

        self.assertEqual(raw[:6], bytes([1, 2, 3, 4, 5, 6]))
        self.assertEqual(len(raw), 16 * 16 * 3)

    def test_image_to_rgb_bytes_converts_non_rgb_image(self):
        image = Image.new("L", (16, 16), 7)

        raw = PixooClient._image_to_rgb_bytes(image)

        self.assertEqual(raw[:3], bytes([7, 7, 7]))

    def test_image_to_rgb_bytes_rejects_non_square_image(self):
        with self.assertRaises(PixooError):
            PixooClient._image_to_rgb_bytes(Image.new("RGB", (16, 32)))

    def test_image_to_rgb_bytes_rejects_unsupported_size(self):
        with self.assertRaises(PixooError):
            PixooClient._image_to_rgb_bytes(Image.new("RGB", (24, 24)))

    def test_send_frame_builds_expected_payload(self):
        client = object.__new__(PixooClient)
        client.auto_reset_gif_id = True
        client.gif_speed_ms = 100
        client.reset_pic_id = Mock()
        client.get_next_pic_id = Mock(return_value=42)
        client._post = Mock(return_value={})
        image = Image.new("RGB", (16, 16), (1, 2, 3))

        client.send_frame(image, speed_ms=250)

        client.reset_pic_id.assert_called_once_with()
        payload = client._post.call_args.args[0]
        self.assertEqual(payload["Command"], "Draw/SendHttpGif")
        self.assertEqual(payload["PicID"], 42)
        self.assertEqual(payload["PicWidth"], 16)
        self.assertEqual(payload["PicSpeed"], 250)
        self.assertEqual(payload["PicSpped"], 250)
        self.assertEqual(base64.b64decode(payload["PicData"])[:3], bytes([1, 2, 3]))

    def test_set_brightness_clamps_to_supported_range(self):
        client = object.__new__(PixooClient)
        client._post = Mock(return_value={})

        client.set_brightness(150)
        client.set_brightness(-5)

        self.assertEqual(
            client._post.call_args_list[0].args[0],
            {"Command": "Channel/SetBrightness", "Brightness": 100},
        )
        self.assertEqual(
            client._post.call_args_list[1].args[0],
            {"Command": "Channel/SetBrightness", "Brightness": 0},
        )

    def test_play_remote_gif_rejects_empty_id(self):
        client = object.__new__(PixooClient)

        with self.assertRaises(PixooError):
            client.play_remote_gif("")


if __name__ == "__main__":
    unittest.main()
