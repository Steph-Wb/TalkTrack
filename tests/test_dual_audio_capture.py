"""Tests for DualAudioCapture per-app mode integration."""
import unittest


class TestDualAudioCaptureMode(unittest.TestCase):

    def test_accepts_capture_mode_parameter(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="legacy"
        )
        self.assertEqual(cap.capture_mode, "legacy")

    def test_defaults_to_legacy_mode(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        self.assertEqual(cap.capture_mode, "legacy")

    def test_accepts_per_app_mode_with_pids(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="per_app",
            app_pids=[123, 456]
        )
        self.assertEqual(cap.capture_mode, "per_app")
        self.assertEqual(cap.app_pids, [123, 456])


import numpy as np


class TestAudioStreamMute(unittest.TestCase):
    """AudioStream.set_muted zeros audio chunks but preserves length."""

    def _make_stream(self):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        # Simulate active recording without opening a real device
        stream._recording = True
        stream._paused = False
        return stream

    def test_unmuted_writes_original_samples(self):
        stream = self._make_stream()
        chunk = np.ones((256, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 256, None, None)
        written = stream._all_chunks[0]
        self.assertEqual(written.shape, (256, 1))
        self.assertAlmostEqual(float(written.max()), 0.5)

    def test_muted_zeros_samples_but_preserves_length(self):
        stream = self._make_stream()
        stream.set_muted(True)
        chunk = np.ones((256, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 256, None, None)
        written = stream._all_chunks[0]
        self.assertEqual(written.shape, (256, 1))
        self.assertEqual(float(written.max()), 0.0)
        self.assertEqual(float(written.min()), 0.0)

    def test_unmute_restores_capture(self):
        stream = self._make_stream()
        stream.set_muted(True)
        stream._audio_callback(
            np.ones((128, 1), dtype=np.float32), 128, None, None
        )
        stream.set_muted(False)
        stream._audio_callback(
            np.ones((128, 1), dtype=np.float32) * 0.7, 128, None, None
        )
        self.assertEqual(float(stream._all_chunks[0].max()), 0.0)
        self.assertAlmostEqual(float(stream._all_chunks[1].max()), 0.7)

    def test_level_callback_receives_zeroed_chunk_when_muted(self):
        received = []
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(
            device_index=None, sample_rate=16000, channels=1,
            level_callback=lambda c: received.append(c),
        )
        stream._recording = True
        stream._paused = False
        stream.set_muted(True)
        stream._audio_callback(
            np.ones((64, 1), dtype=np.float32), 64, None, None
        )
        self.assertEqual(len(received), 1)
        self.assertEqual(float(received[0].max()), 0.0)


class TestDualAudioCaptureMute(unittest.TestCase):
    """DualAudioCapture.set_muted propagates to both mic streams."""

    def _fake_stream(self):
        """Return an AudioStream instance that is not backed by a real device."""
        from app.recording.audio_capture import AudioStream
        s = AudioStream(device_index=None, sample_rate=16000, channels=1)
        return s

    def test_set_muted_single_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.set_muted(True)
        self.assertTrue(cap.mic_stream._muted)
        self.assertTrue(cap.is_muted)

    def test_set_muted_propagates_to_second_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.mic_stream_2 = self._fake_stream()
        cap.set_muted(True)
        self.assertTrue(cap.mic_stream._muted)
        self.assertTrue(cap.mic_stream_2._muted)

    def test_unmute_propagates(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.mic_stream_2 = self._fake_stream()
        cap.set_muted(True)
        cap.set_muted(False)
        self.assertFalse(cap.mic_stream._muted)
        self.assertFalse(cap.mic_stream_2._muted)
        self.assertFalse(cap.is_muted)

    def test_set_muted_with_no_streams_does_not_raise(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        # mic_stream and mic_stream_2 are both None
        cap.set_muted(True)
        self.assertTrue(cap.is_muted)

    def test_default_is_not_muted(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        self.assertFalse(cap.is_muted)


if __name__ == "__main__":
    unittest.main()
