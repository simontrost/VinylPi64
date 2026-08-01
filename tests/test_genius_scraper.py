from __future__ import annotations

import unittest
from unittest.mock import Mock, patch

from vinylpi.core.genius_scraper import _tokens, fetch_lyrics, get_lyrics, search_genius


class GeniusScraperTests(unittest.TestCase):
    def test_tokens_remove_noise_words_and_punctuation(self):
        self.assertEqual(_tokens("Song (Official Video) feat. Guest"), {"song", "guest"})

    @patch("vinylpi.core.genius_scraper.requests.get")
    def test_search_genius_selects_best_matching_lyrics_result(self, requests_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": {
                "sections": [
                    {
                        "type": "song",
                        "hits": [
                            {
                                "result": {
                                    "url": "https://genius.com/Wrong-artist-song-remix-lyrics",
                                    "title": "Song Remix",
                                    "primary_artist": {"name": "Wrong Artist"},
                                }
                            },
                            {
                                "result": {
                                    "url": "https://genius.com/Right-artist-song-lyrics",
                                    "title": "Song",
                                    "primary_artist": {"name": "Right Artist"},
                                }
                            },
                        ],
                    }
                ]
            }
        }
        requests_get.return_value = response

        url = search_genius("Right Artist", "Song")

        self.assertEqual(url, "https://genius.com/Right-artist-song-lyrics")
        response.raise_for_status.assert_called_once_with()

    @patch("vinylpi.core.genius_scraper.requests.get")
    def test_search_genius_rejects_low_confidence_result(self, requests_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "response": {
                "sections": [
                    {
                        "type": "song",
                        "hits": [
                            {
                                "result": {
                                    "url": "https://genius.com/Unrelated-lyrics",
                                    "title": "Different",
                                    "primary_artist": {"name": "Someone Else"},
                                }
                            }
                        ],
                    }
                ]
            }
        }
        requests_get.return_value = response

        self.assertIsNone(search_genius("Right Artist", "Song"))

    @patch("vinylpi.core.genius_scraper.requests.get")
    def test_fetch_lyrics_preserves_line_breaks_and_excludes_annotations(self, requests_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.text = """
            <div data-lyrics-container="true">
                First line<br/>Second line
                <span data-exclude-from-selection="true">123Embed</span>
            </div>
            <div data-lyrics-container="true">Third line</div>
        """
        requests_get.return_value = response

        lyrics = fetch_lyrics("https://genius.com/test-lyrics")

        self.assertEqual(lyrics, "First line\nSecond line\n\nThird line")
        self.assertNotIn("Embed", lyrics)

    @patch("vinylpi.core.genius_scraper.fetch_lyrics", return_value="Lyrics")
    @patch("vinylpi.core.genius_scraper.search_genius", return_value="https://genius.com/test-lyrics")
    def test_get_lyrics_returns_success_payload(self, search, fetch):
        result = get_lyrics("Artist", "Song")

        self.assertEqual(
            result,
            {
                "ok": True,
                "source": "genius",
                "url": "https://genius.com/test-lyrics",
                "lyrics": "Lyrics",
            },
        )
        search.assert_called_once_with("Artist", "Song")
        fetch.assert_called_once_with("https://genius.com/test-lyrics")

    @patch("vinylpi.core.genius_scraper.search_genius", return_value=None)
    def test_get_lyrics_reports_not_found(self, search):
        self.assertEqual(get_lyrics("Artist", "Song"), {"ok": False, "error": "not_found"})


if __name__ == "__main__":
    unittest.main()
