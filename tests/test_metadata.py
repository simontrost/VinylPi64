from __future__ import annotations

import unittest

from PIL import Image

from vinylpi.core.genre_tags import normalize_genre
from vinylpi.core.models import RecognizedTrack
from vinylpi.core.title_variants import canonicalize_title, is_live_variant, variant_score


class TitleVariantTests(unittest.TestCase):
    def test_canonicalize_title_removes_parenthesized_remaster(self):
        self.assertEqual(canonicalize_title("Black Dog (2012 Remaster)"), "black dog")

    def test_canonicalize_title_removes_bracketed_version(self):
        self.assertEqual(canonicalize_title("Song [Deluxe Version]"), "song")

    def test_canonicalize_title_normalizes_unicode_dash_suffix(self):
        self.assertEqual(canonicalize_title("Song — Radio Edit"), "song")

    def test_canonicalize_title_keeps_meaningful_parentheses(self):
        self.assertEqual(canonicalize_title("The Man Who Sold the World (Live)"), "the man who sold the world (live)")

    def test_live_variant_is_penalized_against_studio_release(self):
        studio = variant_score("Nutshell", "Jar of Flies")
        live = variant_score("Nutshell", "MTV Unplugged")

        self.assertGreater(studio, live)

    def test_cover_is_penalized_more_than_remaster(self):
        self.assertLess(
            variant_score("Song (Cover)", "Album"),
            variant_score("Song (Remastered)", "Album"),
        )

    def test_is_live_variant_checks_album_metadata(self):
        self.assertTrue(is_live_variant("Nutshell", "MTV Unplugged"))
        self.assertFalse(is_live_variant("Nutshell", "Jar of Flies"))


class GenreTests(unittest.TestCase):
    def test_normalize_genre_maps_known_alias(self):
        self.assertEqual(normalize_genre("hip hop/rap"), "Hip-Hop/Rap")

    def test_normalize_genre_uses_first_non_empty_list_item(self):
        self.assertEqual(normalize_genre(["", "Electronic"]), "Electronic")

    def test_normalize_genre_returns_none_for_empty_value(self):
        self.assertIsNone(normalize_genre("   "))

    def test_normalize_genre_limits_untrusted_length(self):
        self.assertEqual(len(normalize_genre("x" * 100)), 80)


class RecognizedTrackTests(unittest.TestCase):
    def test_identity_is_casefolded_and_trimmed(self):
        track = RecognizedTrack(
            artist="  Alice In Chains ",
            title=" NUTSHELL ",
            cover_image=Image.new("RGB", (1, 1)),
        )

        self.assertEqual(track.identity, ("alice in chains", "nutshell"))


if __name__ == "__main__":
    unittest.main()
