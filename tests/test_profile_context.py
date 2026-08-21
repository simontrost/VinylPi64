from __future__ import annotations

import unittest
from contextvars import copy_context

from vinylpi.profiles import (
    get_profile_storage_override,
    reset_profile_storage_override,
    restore_profile_storage_override,
    set_profile_storage_override,
)


class ProfileContextTests(unittest.TestCase):
    def test_direct_restore_is_safe_in_copied_context(self):
        original = get_profile_storage_override()
        token = set_profile_storage_override("simon")
        copied = copy_context()

        try:
            # This is the failure mode seen when Flask closes a streamed SSE
            # response in a copied context.
            with self.assertRaises(ValueError):
                copied.run(reset_profile_storage_override, token)

            copied.run(restore_profile_storage_override, original)
            self.assertEqual(copied.run(get_profile_storage_override), original)
            self.assertEqual(get_profile_storage_override(), "simon")
        finally:
            reset_profile_storage_override(token)


if __name__ == "__main__":
    unittest.main()
