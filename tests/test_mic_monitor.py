"""Tests for MicMonitor — the idle-time mic level feed."""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np

from app.recording.mic_monitor import MicMonitor


class TestMicMonitor(unittest.TestCase):
    def test_start_with_none_device_does_nothing(self):
        cb = MagicMock()
        mon = MicMonitor(level_callback=cb)
        with patch("app.recording.mic_monitor.sd.InputStream") as mock_stream:
            mon.start(None)
        mock_stream.assert_not_called()
        self.assertFalse(mon.is_active)
        self.assertIsNone(mon.device_index)

    def test_start_opens_stream_and_records_device(self):
        cb = MagicMock()
        mon = MicMonitor(sample_rate=16000, channels=1, level_callback=cb)
        stream_instance = MagicMock()
        with patch(
            "app.recording.mic_monitor.sd.InputStream",
            return_value=stream_instance,
        ) as mock_stream:
            mon.start(5)
        mock_stream.assert_called_once()
        kwargs = mock_stream.call_args.kwargs
        self.assertEqual(kwargs["device"], 5)
        self.assertEqual(kwargs["samplerate"], 16000)
        self.assertEqual(kwargs["channels"], 1)
        stream_instance.start.assert_called_once()
        self.assertTrue(mon.is_active)
        self.assertEqual(mon.device_index, 5)

    def test_start_replaces_existing_stream(self):
        cb = MagicMock()
        mon = MicMonitor(level_callback=cb)
        first = MagicMock()
        second = MagicMock()
        with patch(
            "app.recording.mic_monitor.sd.InputStream",
            side_effect=[first, second],
        ):
            mon.start(1)
            mon.start(2)
        first.stop.assert_called_once()
        first.close.assert_called_once()
        second.start.assert_called_once()
        self.assertEqual(mon.device_index, 2)

    def test_stop_is_idempotent(self):
        mon = MicMonitor()
        mon.stop()  # no stream — should not raise
        self.assertFalse(mon.is_active)

    def test_stop_closes_active_stream(self):
        mon = MicMonitor()
        stream = MagicMock()
        with patch("app.recording.mic_monitor.sd.InputStream", return_value=stream):
            mon.start(3)
        mon.stop()
        stream.stop.assert_called_once()
        stream.close.assert_called_once()
        self.assertFalse(mon.is_active)
        self.assertIsNone(mon.device_index)

    def test_callback_forwards_copy_to_level_callback(self):
        """The audio callback must copy the indata buffer before handing it off."""
        received = []
        mon = MicMonitor(level_callback=received.append)
        indata = np.array([[0.1], [0.2], [0.3]], dtype=np.float32)
        mon._callback(indata, 3, None, None)
        self.assertEqual(len(received), 1)
        self.assertTrue(np.array_equal(received[0], indata))
        # The forwarded chunk must not be the same object — otherwise a later
        # device-buffer reuse would corrupt what the UI sees.
        self.assertIsNot(received[0], indata)

    def test_gain_applied_and_clipped(self):
        """Gain multiplies the signal and clips to [-1, 1] so downstream meters
        match what the recorder would actually write."""
        received = []
        mon = MicMonitor(level_callback=received.append)
        mon.set_gain(3.0)
        indata = np.array([[0.1], [0.5], [-0.5]], dtype=np.float32)
        mon._callback(indata, 3, None, None)
        out = received[0]
        self.assertAlmostEqual(float(out[0, 0]), 0.3, places=5)
        self.assertAlmostEqual(float(out[1, 0]), 1.0, places=5)   # clipped
        self.assertAlmostEqual(float(out[2, 0]), -1.0, places=5)  # clipped

    def test_gain_of_one_is_fast_path(self):
        """Default gain=1.0 should not mutate the signal."""
        received = []
        mon = MicMonitor(level_callback=received.append)
        indata = np.array([[0.4], [-0.2]], dtype=np.float32)
        mon._callback(indata, 2, None, None)
        self.assertTrue(np.array_equal(received[0], indata))

    def test_callback_no_op_when_callback_is_none(self):
        mon = MicMonitor(level_callback=None)
        indata = np.zeros((10, 1), dtype=np.float32)
        mon._callback(indata, 10, None, None)  # should not raise

    def test_start_failure_leaves_monitor_inactive(self):
        mon = MicMonitor()
        with patch(
            "app.recording.mic_monitor.sd.InputStream",
            side_effect=RuntimeError("device busy"),
        ):
            mon.start(7)
        self.assertFalse(mon.is_active)
        self.assertIsNone(mon.device_index)


if __name__ == "__main__":
    unittest.main()
