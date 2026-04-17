"""Tests for pure helpers in app.ui.meters_panel (no Qt widgets instantiated)."""
import time
import unittest

import numpy as np


class TestChunkMaxAbs(unittest.TestCase):
    """chunk_max_abs returns the peak absolute sample value (for clip detection)."""

    def test_empty_chunk_returns_zero(self):
        from app.ui.meters_panel import chunk_max_abs
        self.assertEqual(chunk_max_abs(np.array([], dtype=np.float32)), 0.0)

    def test_positive_peak(self):
        from app.ui.meters_panel import chunk_max_abs
        self.assertAlmostEqual(
            chunk_max_abs(np.array([0.1, 0.8, 0.3], dtype=np.float32)),
            0.8,
            places=5,
        )

    def test_negative_peak(self):
        from app.ui.meters_panel import chunk_max_abs
        self.assertAlmostEqual(
            chunk_max_abs(np.array([-0.9, 0.2, 0.1], dtype=np.float32)),
            0.9,
            places=5,
        )

    def test_multidim_chunk(self):
        from app.ui.meters_panel import chunk_max_abs
        arr = np.array([[0.1], [-0.7], [0.3]], dtype=np.float32)
        self.assertAlmostEqual(chunk_max_abs(arr), 0.7, places=5)


class TestIsClipping(unittest.TestCase):
    """is_clipping: True when any sample in the chunk is >= 0.99 absolute."""

    def test_no_clip(self):
        from app.ui.meters_panel import is_clipping
        self.assertFalse(is_clipping(np.array([0.5, 0.7, -0.8], dtype=np.float32)))

    def test_exact_threshold_clips(self):
        from app.ui.meters_panel import is_clipping
        self.assertTrue(is_clipping(np.array([0.99, 0.1, 0.2], dtype=np.float32)))

    def test_above_threshold_clips(self):
        from app.ui.meters_panel import is_clipping
        self.assertTrue(is_clipping(np.array([0.5, 0.995, 0.1], dtype=np.float32)))

    def test_negative_clip_detected(self):
        from app.ui.meters_panel import is_clipping
        self.assertTrue(is_clipping(np.array([-0.999, 0.1], dtype=np.float32)))

    def test_just_below_threshold_no_clip(self):
        from app.ui.meters_panel import is_clipping
        self.assertFalse(is_clipping(np.array([0.98, -0.98], dtype=np.float32)))

    def test_empty_chunk_is_not_clipping(self):
        from app.ui.meters_panel import is_clipping
        self.assertFalse(is_clipping(np.array([], dtype=np.float32)))


class TestPeakHoldDecay(unittest.TestCase):
    """peak_hold_value decays after a hold window."""

    def test_current_above_peak_updates_immediately(self):
        from app.ui.meters_panel import peak_hold_value
        now = 10.0
        new_peak, new_ts = peak_hold_value(
            current=0.8, peak=0.5, peak_ts=5.0, now=now,
            hold_seconds=1.5, decay_seconds=0.5,
        )
        self.assertAlmostEqual(new_peak, 0.8, places=5)
        self.assertEqual(new_ts, now)

    def test_current_equals_peak_refreshes_timestamp(self):
        from app.ui.meters_panel import peak_hold_value
        now = 10.0
        new_peak, new_ts = peak_hold_value(
            current=0.5, peak=0.5, peak_ts=5.0, now=now,
            hold_seconds=1.5, decay_seconds=0.5,
        )
        self.assertAlmostEqual(new_peak, 0.5, places=5)
        self.assertEqual(new_ts, now)

    def test_within_hold_window_peak_stays(self):
        from app.ui.meters_panel import peak_hold_value
        peak_ts = 10.0
        now = peak_ts + 1.0  # hold_seconds=1.5, still within hold
        new_peak, new_ts = peak_hold_value(
            current=0.2, peak=0.8, peak_ts=peak_ts, now=now,
            hold_seconds=1.5, decay_seconds=0.5,
        )
        self.assertAlmostEqual(new_peak, 0.8, places=5)
        self.assertEqual(new_ts, peak_ts)  # ts unchanged

    def test_after_hold_peak_decays_linearly(self):
        from app.ui.meters_panel import peak_hold_value
        peak_ts = 10.0
        # 1.5s hold + 0.25s into 0.5s decay = decay 50% of the way from peak to current
        now = peak_ts + 1.75
        new_peak, _ = peak_hold_value(
            current=0.2, peak=0.8, peak_ts=peak_ts, now=now,
            hold_seconds=1.5, decay_seconds=0.5,
        )
        # Expected: 0.8 - (0.8 - 0.2) * 0.5 = 0.5
        self.assertAlmostEqual(new_peak, 0.5, places=5)

    def test_after_full_decay_peak_equals_current(self):
        from app.ui.meters_panel import peak_hold_value
        peak_ts = 10.0
        now = peak_ts + 1.5 + 0.5 + 0.1  # beyond hold+decay
        new_peak, _ = peak_hold_value(
            current=0.2, peak=0.8, peak_ts=peak_ts, now=now,
            hold_seconds=1.5, decay_seconds=0.5,
        )
        self.assertAlmostEqual(new_peak, 0.2, places=5)


class TestGainSliderMapping(unittest.TestCase):
    """Slider integer value <-> float multiplier conversion."""

    def test_slider_to_gain_min(self):
        from app.ui.meters_panel import slider_to_gain
        self.assertAlmostEqual(slider_to_gain(5), 0.5, places=5)

    def test_slider_to_gain_one(self):
        from app.ui.meters_panel import slider_to_gain
        self.assertAlmostEqual(slider_to_gain(10), 1.0, places=5)

    def test_slider_to_gain_max(self):
        from app.ui.meters_panel import slider_to_gain
        self.assertAlmostEqual(slider_to_gain(50), 5.0, places=5)

    def test_gain_to_slider_min(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(0.5), 5)

    def test_gain_to_slider_one(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(1.0), 10)

    def test_gain_to_slider_max(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(5.0), 50)

    def test_gain_to_slider_rounds(self):
        from app.ui.meters_panel import gain_to_slider
        # 1.54 -> 15.4 -> 15 (rounded)
        self.assertEqual(gain_to_slider(1.54), 15)

    def test_gain_to_slider_clamps_below(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(0.2), 5)

    def test_gain_to_slider_clamps_above(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(10.0), 50)


if __name__ == "__main__":
    unittest.main()
