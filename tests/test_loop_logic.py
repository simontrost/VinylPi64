from __future__ import annotations

import unittest
from unittest.mock import patch

from vinylpi.core.discogs_matcher import _is_turn_record_transition
from vinylpi.core.loop_logic import (
    handle_no_result,
    should_update_display,
    update_album_session_on_switch,
    update_song_stats_on_switch,
)
from vinylpi.core.loop_state import AlbumState, DisplayState, LoopConfig, StatsSwitchState


class LoopConfigTests(unittest.TestCase):
    def test_sample_seconds_grow_with_failures_and_cap_at_last_value(self):
        cfg = LoopConfig(
            base_sample_seconds=4,
            adaptive_sample_enabled=True,
            adaptive_failure_durations=(6, 8),
        )

        self.assertEqual(cfg.sample_seconds_for_failures(0), 4)
        self.assertEqual(cfg.sample_seconds_for_failures(1), 6)
        self.assertEqual(cfg.sample_seconds_for_failures(2), 8)
        self.assertEqual(cfg.sample_seconds_for_failures(20), 8)

    def test_from_config_sanitizes_adaptive_values_and_minimum_confirmation(self):
        cfg = LoopConfig.from_config(
            {
                "audio": {
                    "sample_seconds": 0.1,
                    "adaptive_sample": {
                        "enabled": True,
                        "failure_durations_seconds": ["7", "bad", 0.1],
                    },
                },
                "behavior": {"stats_min_consecutive": 1},
            }
        )

        self.assertEqual(cfg.base_sample_seconds, 0.5)
        self.assertEqual(cfg.adaptive_failure_durations, (7.0, 0.5))
        self.assertEqual(cfg.stats_min_consecutive, 2)

    def test_from_config_reads_independent_fallback_switches(self):
        cfg = LoopConfig.from_config(
            {
                "fallback": {
                    "enabled": False,
                    "side_flip_enabled": True,
                    "allowed_failures": 0,
                }
            }
        )

        self.assertFalse(cfg.fallback_enabled)
        self.assertTrue(cfg.side_flip_enabled)
        self.assertEqual(cfg.fallback_allowed_failures, 1)


class SideFlipTransitionTests(unittest.TestCase):
    def test_all_paired_record_sides_are_supported(self):
        self.assertTrue(_is_turn_record_transition("A", "B"))
        self.assertTrue(_is_turn_record_transition("C", "D"))
        self.assertTrue(_is_turn_record_transition("E", "F"))

    def test_cross_record_and_reverse_transitions_are_not_prompts(self):
        self.assertFalse(_is_turn_record_transition("B", "C"))
        self.assertFalse(_is_turn_record_transition("D", "C"))
        self.assertFalse(_is_turn_record_transition("F", "G"))



class DisplayDecisionTests(unittest.TestCase):
    def test_new_song_updates_display(self):
        result = should_update_display(
            disp=DisplayState(last_song_id=("artist", "old"), last_song_variant_score=20),
            song_id=("artist", "new"),
            score=20,
        )

        self.assertEqual(result, (True, False))

    def test_same_song_after_fallback_updates_even_with_same_score(self):
        result = should_update_display(
            disp=DisplayState(
                last_song_id=("artist", "song"),
                last_song_variant_score=20,
                last_display_was_fallback=True,
            ),
            song_id=("artist", "song"),
            score=20,
        )

        self.assertEqual(result, (True, False))

    def test_same_song_with_equal_or_worse_variant_is_skipped(self):
        disp = DisplayState(last_song_id=("artist", "song"), last_song_variant_score=20)

        self.assertEqual(
            should_update_display(disp=disp, song_id=("artist", "song"), score=20),
            (False, False),
        )
        self.assertEqual(
            should_update_display(disp=disp, song_id=("artist", "song"), score=-60),
            (False, False),
        )

    def test_same_song_with_better_variant_updates(self):
        result = should_update_display(
            disp=DisplayState(last_song_id=("artist", "song"), last_song_variant_score=-60),
            song_id=("artist", "song"),
            score=20,
        )

        self.assertEqual(result, (True, True))


class NoResultTests(unittest.TestCase):
    @patch("vinylpi.core.loop_logic.clear_side_flip_prompt")
    @patch("vinylpi.core.loop_logic.show_fallback_image")
    def test_fallback_is_shown_at_threshold(self, show_fallback, clear_prompt):
        cfg = LoopConfig(fallback_allowed_failures=2, auto_sleep=10)
        disp = DisplayState(consecutive_failures=1)

        should_sleep = handle_no_result(cfg, disp, cfg_reloaded=False)

        self.assertFalse(should_sleep)
        self.assertTrue(disp.last_display_was_fallback)
        show_fallback.assert_called_once_with()
        clear_prompt.assert_called_once_with()

    @patch("vinylpi.core.loop_logic.write_side_flip_prompt")
    @patch("vinylpi.core.loop_logic.show_side_flip_prompt")
    def test_side_flip_prompt_replaces_generic_fallback(self, show_prompt, write_prompt):
        cfg = LoopConfig(fallback_allowed_failures=1, auto_sleep=10)
        disp = DisplayState()
        prompt = {
            "from_side": "A",
            "to_side": "B",
            "next_title": "Next Song",
            "next_position": "B1",
        }

        handle_no_result(cfg, disp, cfg_reloaded=False, side_flip_prompt=prompt)

        show_prompt.assert_called_once_with("B", next_position="B1")
        write_prompt.assert_called_once_with(
            from_side="A",
            to_side="B",
            next_title="Next Song",
            next_position="B1",
        )

    @patch("vinylpi.core.loop_logic.show_fallback_image")
    def test_existing_fallback_is_not_resent_without_config_reload(self, show_fallback):
        cfg = LoopConfig(fallback_allowed_failures=1, auto_sleep=10)
        disp = DisplayState(last_display_was_fallback=True)

        handle_no_result(cfg, disp, cfg_reloaded=False)

        show_fallback.assert_not_called()

    @patch("builtins.print")
    def test_auto_sleep_returns_true_at_threshold(self, print_mock):
        cfg = LoopConfig(fallback_allowed_failures=99, auto_sleep=2)
        disp = DisplayState(consecutive_failures=1)

        self.assertTrue(handle_no_result(cfg, disp, cfg_reloaded=False))

    @patch("vinylpi.core.loop_logic.clear_side_flip_prompt")
    @patch("vinylpi.core.loop_logic.show_fallback_image")
    def test_disabled_fallback_keeps_current_display(self, show_fallback, clear_prompt):
        cfg = LoopConfig(
            fallback_allowed_failures=1,
            fallback_enabled=False,
            side_flip_enabled=False,
            auto_sleep=10,
        )
        disp = DisplayState()

        handle_no_result(cfg, disp, cfg_reloaded=False)

        show_fallback.assert_not_called()
        clear_prompt.assert_called_once_with()
        self.assertFalse(disp.last_display_was_fallback)



class StatisticsSwitchTests(unittest.TestCase):
    @patch("vinylpi.core.loop_logic._update_stats")
    def test_song_requires_consecutive_confirmations(self, update_stats):
        st = StatsSwitchState()
        kwargs = {
            "st": st,
            "song_id": ("artist", "song"),
            "artist": "Artist",
            "title": "Song",
            "album": "Album",
            "cover_url": None,
            "genre": None,
            "track_id": None,
            "artist_id": None,
            "duration_ms": None,
            "min_consecutive": 2,
            "repeat_guard_seconds": 0,
        }

        self.assertFalse(update_song_stats_on_switch(**kwargs))
        self.assertTrue(update_song_stats_on_switch(**kwargs))

        update_stats.assert_called_once()
        self.assertEqual(st.current_song_id, ("artist", "song"))
        self.assertEqual(st.candidate_streak, 0)

    @patch("vinylpi.core.loop_logic.time.monotonic", side_effect=[100.0, 150.0, 250.0])
    @patch("vinylpi.core.loop_logic._update_stats")
    def test_repeat_guard_prevents_rapid_recount(self, update_stats, monotonic):
        st = StatsSwitchState()

        def confirm(song_id):
            return update_song_stats_on_switch(
                st=st,
                song_id=song_id,
                artist="Artist",
                title=song_id[1],
                album="Album",
                cover_url=None,
                genre=None,
                track_id=None,
                artist_id=None,
                duration_ms=None,
                min_consecutive=1,
                repeat_guard_seconds=120,
            )

        self.assertTrue(confirm(("artist", "song")))
        st.current_song_id = None
        self.assertTrue(confirm(("artist", "song")))
        st.current_song_id = None
        self.assertTrue(confirm(("artist", "song")))

        self.assertEqual(update_stats.call_count, 2)
        self.assertTrue(st.last_counted)
        self.assertEqual(monotonic.call_count, 3)

    @patch("vinylpi.core.loop_logic._update_stats")
    def test_confirmation_can_be_delayed_without_losing_candidate(self, update_stats):
        st = StatsSwitchState()
        common = dict(
            st=st,
            song_id=("artist", "new"),
            artist="Artist",
            title="New",
            album=None,
            cover_url=None,
            genre=None,
            track_id=None,
            artist_id=None,
            duration_ms=None,
            min_consecutive=2,
            repeat_guard_seconds=0,
        )

        self.assertFalse(update_song_stats_on_switch(**common, allow_confirmation=False))
        self.assertFalse(update_song_stats_on_switch(**common, allow_confirmation=False))
        self.assertEqual(st.candidate_streak, 2)
        self.assertTrue(update_song_stats_on_switch(**common, allow_confirmation=True))
        update_stats.assert_called_once()


class AlbumSessionTests(unittest.TestCase):
    @patch("vinylpi.core.loop_logic._increment_album_session")
    def test_album_session_counts_once_after_two_unique_tracks(self, increment):
        st = AlbumState()

        update_album_session_on_switch(st=st, album="Album", title="One", min_tracks=2, min_consecutive=2)
        update_album_session_on_switch(st=st, album="Album", title="Two", min_tracks=2, min_consecutive=2)
        update_album_session_on_switch(st=st, album="Album", title="Three", min_tracks=2, min_consecutive=2)

        increment.assert_called_once_with("Album")
        self.assertTrue(st.current_album_session_counted)

    @patch("vinylpi.core.loop_logic._increment_album_session")
    def test_album_switch_requires_consecutive_samples(self, increment):
        st = AlbumState(current_album="Old", current_album_unique_tracks={"One"})

        update_album_session_on_switch(st=st, album="New", title="A", min_tracks=2, min_consecutive=2)
        self.assertEqual(st.current_album, "Old")
        update_album_session_on_switch(st=st, album="New", title="A", min_tracks=2, min_consecutive=2)

        self.assertEqual(st.current_album, "New")
        self.assertEqual(st.current_album_unique_tracks, {"A"})
        increment.assert_not_called()


if __name__ == "__main__":
    unittest.main()
