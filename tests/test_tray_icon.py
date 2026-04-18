"""Unit tests for tray icon pure helpers."""
import unittest

from app.ui.tray_icon import (
    format_tray_tooltip,
    tray_action_visibility,
    resolve_overlay,
)
from app.recording.recorder import RecordingState


class TestFormatTrayTooltip(unittest.TestCase):
    def test_idle_returns_plain_name(self):
        self.assertEqual(format_tray_tooltip(RecordingState.IDLE, 0), "TalkTrack")

    def test_recording_shows_elapsed(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.RECORDING, 754),
            "TalkTrack \u2014 Recording 00:12:34",
        )

    def test_paused_shows_elapsed(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.PAUSED, 65),
            "TalkTrack \u2014 Paused 00:01:05",
        )

    def test_stopping_falls_back_to_idle_form(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.STOPPING, 0), "TalkTrack"
        )

    def test_long_duration_hours(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.RECORDING, 3661),
            "TalkTrack \u2014 Recording 01:01:01",
        )


class TestTrayActionVisibility(unittest.TestCase):
    def test_idle_shows_record_only(self):
        vis = tray_action_visibility(RecordingState.IDLE)
        self.assertTrue(vis["record"])
        self.assertFalse(vis["pause"])
        self.assertFalse(vis["resume"])
        self.assertFalse(vis["stop"])

    def test_recording_shows_pause_and_stop(self):
        vis = tray_action_visibility(RecordingState.RECORDING)
        self.assertFalse(vis["record"])
        self.assertTrue(vis["pause"])
        self.assertFalse(vis["resume"])
        self.assertTrue(vis["stop"])

    def test_paused_shows_resume_and_stop(self):
        vis = tray_action_visibility(RecordingState.PAUSED)
        self.assertFalse(vis["record"])
        self.assertFalse(vis["pause"])
        self.assertTrue(vis["resume"])
        self.assertTrue(vis["stop"])

    def test_stopping_shows_nothing(self):
        vis = tray_action_visibility(RecordingState.STOPPING)
        self.assertFalse(vis["record"])
        self.assertFalse(vis["pause"])
        self.assertFalse(vis["resume"])
        self.assertFalse(vis["stop"])


class TestResolveOverlay(unittest.TestCase):
    """resolve_overlay(has_success, has_error) returns None | 'green' | 'red'."""

    def test_nothing_pending_returns_none(self):
        self.assertIsNone(resolve_overlay(False, False))

    def test_success_returns_green(self):
        self.assertEqual(resolve_overlay(True, False), "green")

    def test_error_returns_red(self):
        self.assertEqual(resolve_overlay(False, True), "red")

    def test_error_wins_when_both(self):
        self.assertEqual(resolve_overlay(True, True), "red")


if __name__ == "__main__":
    unittest.main()
