"""Tests for ProcessAudioCapture."""
import unittest
import numpy as np


class TestProcessAudioMixer(unittest.TestCase):

    def test_mix_single_stream(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        chunk = np.array([0.5, -0.5, 0.3], dtype=np.float32)
        result = mix_audio_chunks([chunk])
        np.testing.assert_array_almost_equal(result, chunk)

    def test_mix_two_streams_averages(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        a = np.array([1.0, 0.0], dtype=np.float32)
        b = np.array([0.0, 1.0], dtype=np.float32)
        result = mix_audio_chunks([a, b])
        np.testing.assert_array_almost_equal(result, [0.5, 0.5])

    def test_mix_empty_returns_empty(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        result = mix_audio_chunks([])
        self.assertEqual(len(result), 0)

    def test_mix_different_lengths_pads_shorter(self):
        from app.recording.process_audio_capture import mix_audio_chunks
        a = np.array([1.0, 1.0, 1.0], dtype=np.float32)
        b = np.array([1.0], dtype=np.float32)
        result = mix_audio_chunks([a, b])
        self.assertEqual(len(result), 3)

    def test_stereo_to_mono_downmix(self):
        from app.recording.process_audio_capture import stereo_to_mono
        stereo = np.array([[0.8, 0.2], [0.6, 0.4]], dtype=np.float32)
        mono = stereo_to_mono(stereo)
        np.testing.assert_array_almost_equal(mono, [0.5, 0.5])

    def test_process_capture_stream_init(self):
        from app.recording.process_audio_capture import ProcessCaptureStream
        stream = ProcessCaptureStream(pid=12345, sample_rate=16000)
        self.assertEqual(stream.pid, 12345)
        self.assertEqual(stream.sample_rate, 16000)
        self.assertFalse(stream.is_active)


class TestConvertDtype(unittest.TestCase):
    def test_float32_passthrough(self):
        from app.recording.process_audio_capture import _convert_dtype
        raw = np.array([0.5, -0.25, 0.0, 1.0], dtype=np.float32).tobytes()
        arr = _convert_dtype(raw, format_tag="float32", bits_per_sample=32)
        np.testing.assert_array_almost_equal(arr, [0.5, -0.25, 0.0, 1.0])
        self.assertEqual(arr.dtype, np.float32)

    def test_s16_scaled_to_float32(self):
        from app.recording.process_audio_capture import _convert_dtype
        raw = np.array([0, 16384, -32768, 32767], dtype=np.int16).tobytes()
        arr = _convert_dtype(raw, format_tag="s16", bits_per_sample=16)
        # 16384/32768 = 0.5 ; -32768/32768 = -1.0 ; 32767/32768 ≈ 0.99997
        self.assertAlmostEqual(float(arr[0]), 0.0, places=5)
        self.assertAlmostEqual(float(arr[1]), 0.5, places=5)
        self.assertAlmostEqual(float(arr[2]), -1.0, places=5)
        self.assertAlmostEqual(float(arr[3]), 0.99997, places=4)
        self.assertEqual(arr.dtype, np.float32)

    def test_s24_in_32bit_container_shifted_and_scaled(self):
        from app.recording.process_audio_capture import _convert_dtype
        # s24 in 32-bit container: high 24 bits hold the sample.
        # Value 4194304 (0x400000) in the high 24 bits → 0.5 full scale.
        raw = np.array([0, 0x400000 << 8, -0x800000 << 8], dtype=np.int32).tobytes()
        arr = _convert_dtype(raw, format_tag="s24", bits_per_sample=32)
        self.assertAlmostEqual(float(arr[0]), 0.0, places=5)
        self.assertAlmostEqual(float(arr[1]), 0.5, places=5)
        self.assertAlmostEqual(float(arr[2]), -1.0, places=5)
        self.assertEqual(arr.dtype, np.float32)

    def test_unknown_format_raises(self):
        from app.recording.process_audio_capture import _convert_dtype
        with self.assertRaises(ValueError):
            _convert_dtype(b"\x00", format_tag="mu-law", bits_per_sample=8)


if __name__ == "__main__":
    unittest.main()
