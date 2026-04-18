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


class TestResampler(unittest.TestCase):
    def test_48k_to_16k_sine_frequency_preserved(self):
        """The chipmunk-bug guard: 440 Hz in must be 440 Hz out, not 1320."""
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=48000, target_rate=16000)
        t = np.linspace(0, 1.0, 48000, endpoint=False)
        sine = np.sin(2 * np.pi * 440 * t).astype(np.float32)
        out = rs.push(sine)
        self.assertEqual(len(out), 16000)  # 1 second at 16 kHz
        # FFT peak
        fft = np.abs(np.fft.rfft(out))
        peak_bin = int(np.argmax(fft))
        peak_hz = peak_bin * (16000 / len(out))
        self.assertAlmostEqual(peak_hz, 440, delta=2)

    def test_non_multiple_length_carries_residual(self):
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=48000, target_rate=16000)
        # 100 samples at 48 kHz is not a multiple of down=3 → residual of 1
        first = rs.push(np.zeros(100, dtype=np.float32))
        # next push of 200 samples: buffer holds 1 + 200 = 201 → 67 output frames, 0 residual
        second = rs.push(np.zeros(200, dtype=np.float32))
        self.assertEqual(len(first), 33)   # 99 / 3
        self.assertEqual(len(second), 67)  # 201 / 3

    def test_passthrough_when_rates_match(self):
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=16000, target_rate=16000)
        data = np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        out = rs.push(data)
        np.testing.assert_array_almost_equal(out, data)

    def test_empty_push_returns_empty(self):
        from app.recording.process_audio_capture import _Resampler
        rs = _Resampler(native_rate=48000, target_rate=16000)
        out = rs.push(np.array([], dtype=np.float32))
        self.assertEqual(len(out), 0)


if __name__ == "__main__":
    unittest.main()
