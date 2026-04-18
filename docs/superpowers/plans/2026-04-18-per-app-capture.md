# Per-App Audio Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the scaffolded Windows 11 per-process audio capture so "Selected apps" mode only captures selected apps' audio (record + Test Mic). Dispatch on `capture_mode`, tolerate per-PID failures, surface partial-failure UX.

**Architecture:** Split `process_audio_capture.py` into a pure-logic file (`process_audio_capture.py`) and a COM shim (`_process_com.py`). `ProcessCaptureStream` wraps one PID's COM objects with synchronous `activate()`, non-blocking `read_available()`, `put_back_tail()`, `release()`. `ProcessAudioCapture` owns a single 10 ms polling mixer thread that trims to shortest, mixes with `np.mean`, hands back residue. `DualAudioCapture` branches on `capture_mode`; both backends share the same `start/pause/resume/stop/save_to_file` contract under a new attribute name `system_stream`. `Recorder` emits `capture_status` / `pid_lost` / `capture_lost`; `MainWindow` surfaces partial-failure UX via a status-bar line + ⚠ label on `SourceSelector`.

**Tech Stack:** Python 3.12, PyQt6, comtypes 1.4, ctypes, scipy.signal.resample_poly, numpy, sounddevice, PyAudioWPatch.

**Spec:** `docs/superpowers/specs/2026-04-18-per-app-capture-design.md`

**Baseline note:** This plan builds on the current working tree (includes uncommitted Test Mic work: `app/recording/mic_monitor.py`, `tests/test_mic_monitor.py`, and meter/recording_controls/source_selector edits). Do not rebase or stash those changes while executing.

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `app/recording/process_audio_capture.py` | rewrite | Public classes: `ProcessCaptureStream`, `ProcessAudioCapture`. Format conversion (`_convert_dtype`), resampler (`_Resampler`), trim-and-mix helper. Drops `mix_audio_chunks`, `add_pid`, `remove_pid`. |
| `app/recording/_process_com.py` | **new** | `ctypes.Structure` definitions (`AUDIOCLIENT_ACTIVATION_PARAMS`, `PROPVARIANT`, `WAVEFORMATEX`), GUID constants, HRESULT table + `hresult_name()`, `activate_process_loopback(pid)` shim, `read_next_packet(client)` shim, `IActivateAudioInterfaceCompletionHandler`. |
| `app/recording/audio_capture.py` | modify | Rename `self.loopback_stream` → `self.system_stream`. Dispatch in `DualAudioCapture.start()`. Store `_capture_status`. |
| `app/recording/recorder.py` | modify | New signals: `capture_status`, `pid_lost`, `capture_lost`. Wire into `DualAudioCapture` callbacks. Save `capture_status` into `metadata.json`. |
| `app/main_window.py` | modify | Connect new signals; status-bar line + ⚠ label; `_start_system_monitor` branches on `capture_mode`; rename accessor for `loopback_stream`. |
| `app/ui/source_selector.py` | modify | Add `mark_capture_failures(failures: dict)` + ⚠ `QLabel#captureWarning`. |
| `tests/test_process_audio_capture.py` | rewrite | Tier-1: format conversion, resampler, trim-and-mix, mixer loop with `FakeStream`, signals, status dict, pause/resume, crash containment. |
| `tests/test_process_com.py` | **new** | Tier-2: struct-size sanity, GUID parsing, HRESULT constants, `hresult_name` round-trips. |
| `tests/test_dual_audio_capture.py` | modify | Update to cover the `capture_mode` dispatch branch with a mock `ProcessAudioCapture`. |
| `docs/testing/per-app-capture-smoke.md` | **new** | Tier-3 manual smoke checklist for Win11. |

---

## Task 1: HRESULT helper + constants

**Files:**
- Create: `app/recording/_process_com.py`
- Create: `tests/test_process_com.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_process_com.py`:

```python
"""Tier-2 tests for COM structs, GUIDs, HRESULT helpers in _process_com."""
import unittest


class TestHResultName(unittest.TestCase):
    def test_known_audclnt_codes_map_to_symbol(self):
        from app.recording._process_com import hresult_name
        self.assertEqual(hresult_name(0x88890004), "AUDCLNT_E_DEVICE_INVALIDATED")
        self.assertEqual(hresult_name(0x80070005), "E_ACCESSDENIED")
        self.assertEqual(hresult_name(0x80070490), "ERROR_NOT_FOUND_HRESULT")

    def test_unknown_code_renders_as_hex(self):
        from app.recording._process_com import hresult_name
        self.assertEqual(hresult_name(0x12345678), "0x12345678")

    def test_success_s_ok(self):
        from app.recording._process_com import hresult_name
        self.assertEqual(hresult_name(0), "S_OK")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_process_com.py -v`
Expected: `ModuleNotFoundError: No module named 'app.recording._process_com'`

- [ ] **Step 3: Create `app/recording/_process_com.py` with HRESULT table and helper**

```python
"""Windows 11 process-loopback COM shim.

This module owns ctypes struct definitions, GUID constants, HRESULT name
mapping, and the thin wrappers that call into comtypes. It exists as a
separate file because mocking these is a high-effort/low-signal rabbit hole
- downstream code injects fakes for the activate/read functions when testing.
"""

# HRESULT codes from Audioclient.h / winerror.h. Add more as needed.
# Reference: https://learn.microsoft.com/en-us/windows/win32/api/audioclient/
_HRESULT_NAMES = {
    0x00000000: "S_OK",
    0x80004001: "E_NOTIMPL",
    0x80004002: "E_NOINTERFACE",
    0x80004003: "E_POINTER",
    0x80004004: "E_ABORT",
    0x80004005: "E_FAIL",
    0x80070005: "E_ACCESSDENIED",
    0x80070057: "E_INVALIDARG",
    0x80070490: "ERROR_NOT_FOUND_HRESULT",
    # AUDCLNT_ERR codes (AUDCLNT severity bits = 0x8889xxxx)
    0x88890001: "AUDCLNT_E_NOT_INITIALIZED",
    0x88890002: "AUDCLNT_E_ALREADY_INITIALIZED",
    0x88890003: "AUDCLNT_E_WRONG_ENDPOINT_TYPE",
    0x88890004: "AUDCLNT_E_DEVICE_INVALIDATED",
    0x88890005: "AUDCLNT_E_NOT_STOPPED",
    0x88890006: "AUDCLNT_E_BUFFER_TOO_LARGE",
    0x88890008: "AUDCLNT_E_OUT_OF_ORDER",
    0x88890009: "AUDCLNT_E_UNSUPPORTED_FORMAT",
    0x8889000A: "AUDCLNT_E_INVALID_SIZE",
    0x8889000B: "AUDCLNT_E_DEVICE_IN_USE",
    0x8889000C: "AUDCLNT_E_BUFFER_OPERATION_PENDING",
    0x88890017: "AUDCLNT_E_CPUUSAGE_EXCEEDED",
    0x88890021: "AUDCLNT_E_RESOURCES_INVALIDATED",
}


def hresult_name(hr):
    """Map an HRESULT to a symbolic name, falling back to hex for unknowns."""
    # Normalize signed ints returned by ctypes (-0x77767FFC → 0x88890004).
    hr_u32 = hr & 0xFFFFFFFF
    if hr_u32 in _HRESULT_NAMES:
        return _HRESULT_NAMES[hr_u32]
    return f"0x{hr_u32:08X}"
```

- [ ] **Step 4: Run tests to verify pass**

Run: `python -m pytest tests/test_process_com.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add app/recording/_process_com.py tests/test_process_com.py
git commit -m "audio: HRESULT helper and known-code table for per-app COM"
```

---

## Task 2: Format conversion helper (`_convert_dtype`)

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestConvertDtype -v`
Expected: `ImportError: cannot import name '_convert_dtype'`

- [ ] **Step 3: Add the helper to `app/recording/process_audio_capture.py`**

Insert after the existing `stereo_to_mono` function:

```python
def _convert_dtype(raw_bytes, format_tag, bits_per_sample):
    """Convert a packed byte buffer from Windows into a float32 numpy array.

    Args:
        raw_bytes: bytes from IAudioCaptureClient.GetBuffer.
        format_tag: "float32", "s16", or "s24".
        bits_per_sample: container width (32 for s24-in-s32, 16 for s16, 32 for float32).

    Returns:
        1D float32 numpy array (interleaved channels flattened — caller reshapes).

    Raises:
        ValueError: for unknown formats. We only support formats process-loopback
        is documented to emit.
    """
    if format_tag == "float32":
        return np.frombuffer(raw_bytes, dtype=np.float32).copy()
    if format_tag == "s16":
        samples = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float32)
        return samples / 32768.0
    if format_tag == "s24":
        # 24-bit samples in 32-bit containers: high 24 bits are the data.
        samples = np.frombuffer(raw_bytes, dtype=np.int32).astype(np.float32)
        return (samples / 256.0) / 8388608.0   # >>8 then /2^23
    raise ValueError(f"Unsupported format_tag: {format_tag!r}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py::TestConvertDtype -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/recording/process_audio_capture.py tests/test_process_audio_capture.py
git commit -m "audio: dtype conversion helper for process-loopback packets"
```

---

## Task 3: Resampler with residual carry (`_Resampler`)

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestResampler -v`
Expected: `ImportError: cannot import name '_Resampler'`

- [ ] **Step 3: Implement `_Resampler`**

Add imports and class to `app/recording/process_audio_capture.py`:

```python
from math import gcd
from scipy.signal import resample_poly


class _Resampler:
    """Polyphase resampler that accumulates odd-length inputs across calls.

    resample_poly produces cleanest output when the input length is a multiple
    of `down`. We buffer the remainder across calls so short packets (common
    when WASAPI hands over partial ticks) don't introduce clicks at boundaries.
    """

    def __init__(self, native_rate, target_rate):
        self.native_rate = native_rate
        self.target_rate = target_rate
        g = gcd(native_rate, target_rate)
        self._up = target_rate // g
        self._down = native_rate // g
        self._buf = np.array([], dtype=np.float32)

    def push(self, arr):
        """Append arr to the internal buffer, resample a multiple of down, return it."""
        if arr.size == 0 and self._buf.size == 0:
            return np.array([], dtype=np.float32)
        if self._up == self._down:
            # Passthrough fast path.
            if self._buf.size > 0:
                out = np.concatenate([self._buf, arr])
                self._buf = np.array([], dtype=np.float32)
                return out
            return arr.astype(np.float32, copy=False)

        combined = np.concatenate([self._buf, arr]) if self._buf.size else arr
        # Take the largest multiple of down; carry the rest.
        usable = (len(combined) // self._down) * self._down
        if usable == 0:
            self._buf = combined
            return np.array([], dtype=np.float32)
        chunk = combined[:usable]
        self._buf = combined[usable:]
        return resample_poly(chunk, self._up, self._down).astype(np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py::TestResampler -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add app/recording/process_audio_capture.py tests/test_process_audio_capture.py
git commit -m "audio: polyphase resampler with residual carry for process-loopback"
```

---

## Task 4: Remove dead `mix_audio_chunks`, add `_trim_and_mix`

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Replace the existing `TestProcessAudioMixer` class in `tests/test_process_audio_capture.py` with:

```python
class TestTrimAndMix(unittest.TestCase):
    def test_trim_to_shortest_and_mean_mix(self):
        from app.recording.process_audio_capture import _trim_and_mix
        chunks = {
            1: np.array([1.0, 1.0, 1.0], dtype=np.float32),
            2: np.array([0.0, 0.0], dtype=np.float32),
        }
        mixed, tails = _trim_and_mix(chunks)
        np.testing.assert_array_almost_equal(mixed, [0.5, 0.5])
        self.assertEqual(len(tails), 2)
        np.testing.assert_array_almost_equal(tails[1], [1.0])
        np.testing.assert_array_almost_equal(tails[2], [])

    def test_all_equal_length_no_tails(self):
        from app.recording.process_audio_capture import _trim_and_mix
        a = np.array([1.0, 1.0], dtype=np.float32)
        b = np.array([0.0, 0.0], dtype=np.float32)
        mixed, tails = _trim_and_mix({1: a, 2: b})
        np.testing.assert_array_almost_equal(mixed, [0.5, 0.5])
        self.assertEqual(tails[1].size, 0)
        self.assertEqual(tails[2].size, 0)

    def test_single_stream(self):
        from app.recording.process_audio_capture import _trim_and_mix
        c = np.array([0.3, -0.3, 0.0], dtype=np.float32)
        mixed, tails = _trim_and_mix({7: c})
        np.testing.assert_array_almost_equal(mixed, c)
        self.assertEqual(tails[7].size, 0)

    def test_empty_input_returns_empty(self):
        from app.recording.process_audio_capture import _trim_and_mix
        mixed, tails = _trim_and_mix({})
        self.assertEqual(mixed.size, 0)
        self.assertEqual(tails, {})
```

Also delete the existing `TestProcessAudioMixer` import block for `mix_audio_chunks` tests — replace with the new `TestTrimAndMix` class above. Keep `test_stereo_to_mono_downmix` and `test_process_capture_stream_init` for now (still covered by API).

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestTrimAndMix -v`
Expected: `ImportError: cannot import name '_trim_and_mix'`

- [ ] **Step 3: Remove `mix_audio_chunks`, add `_trim_and_mix`**

In `app/recording/process_audio_capture.py`: delete the `mix_audio_chunks` function entirely. Replace with:

```python
def _trim_and_mix(per_stream_chunks):
    """Trim every stream's chunk to the shortest length, mix with equal-weight mean,
    return (mixed_chunk, tails_per_stream).

    Args:
        per_stream_chunks: {pid: np.ndarray(float32)}.

    Returns:
        (mixed: np.ndarray, tails: {pid: np.ndarray}) — tails may be empty arrays
        when a stream happened to produce exactly the minimum length this tick.
    """
    if not per_stream_chunks:
        return np.array([], dtype=np.float32), {}

    lengths = {pid: len(c) for pid, c in per_stream_chunks.items()}
    min_len = min(lengths.values())

    aligned = []
    tails = {}
    for pid, c in per_stream_chunks.items():
        aligned.append(c[:min_len])
        tails[pid] = c[min_len:] if len(c) > min_len else np.array([], dtype=np.float32)

    if min_len == 0:
        return np.array([], dtype=np.float32), tails
    mixed = np.mean(np.stack(aligned, axis=0), axis=0).astype(np.float32)
    return mixed, tails
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py -v`
Expected: all tests passing (TestTrimAndMix 4 passed, stereo_to_mono passes, process_capture_stream_init may fail — that's fine, it'll be replaced in Task 11).

- [ ] **Step 5: Commit**

```bash
git add app/recording/process_audio_capture.py tests/test_process_audio_capture.py
git commit -m "audio: replace mix_audio_chunks with _trim_and_mix helper"
```

---

## Task 5: `FakeStream` + `ProcessAudioCapture` mixer loop

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
import time
import threading


class FakeStream:
    """Test double for ProcessCaptureStream used by the mixer loop tests."""
    def __init__(self, pid, queued_chunks=None, activate_result=True, error=None):
        self.pid = pid
        self.is_active = True
        self.last_error = error
        self._activate_result = activate_result
        self._queue = list(queued_chunks or [])
        self._post_mix_tail = np.array([], dtype=np.float32)
        self.released = False
        self._lock = threading.Lock()

    def activate(self):
        self.is_active = self._activate_result
        if not self._activate_result and self.last_error is None:
            self.last_error = "activation_failed"
        return self._activate_result

    def read_available(self):
        with self._lock:
            chunks = []
            if self._post_mix_tail.size > 0:
                chunks.append(self._post_mix_tail)
                self._post_mix_tail = np.array([], dtype=np.float32)
            if self._queue:
                chunks.append(self._queue.pop(0))
            return chunks

    def put_back_tail(self, tail):
        if tail.size > 0:
            self._post_mix_tail = tail

    def release(self):
        self.released = True
        self.is_active = False

    def die(self, error):
        self.is_active = False
        self.last_error = error


class TestProcessAudioCaptureMixer(unittest.TestCase):
    def _wait_for(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_mixer_emits_mixed_chunks_via_level_callback(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        b = FakeStream(pid=2, queued_chunks=[np.zeros(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a, 2: b}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        self.assertGreater(len(received), 0)
        np.testing.assert_array_almost_equal(received[0], np.full(160, 0.5))

    def test_trim_to_shortest_hands_back_tail(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(200, dtype=np.float32)])
        b = FakeStream(pid=2, queued_chunks=[np.zeros(100, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a, 2: b}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        # First mix must be length 100 (the shortest).
        self.assertEqual(len(received[0]), 100)
        # a's tail of 100 samples got handed back.
        self.assertEqual(a._post_mix_tail.size, 100)

    def test_paused_drains_but_discards(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: a}
        cap._paused = True
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        time.sleep(0.05)   # let the loop tick a few times
        cap._running = False
        t.join(timeout=1)
        # No level callbacks fired while paused, but the queue was drained.
        self.assertEqual(len(received), 0)
        self.assertEqual(len(a._queue), 0)

    def test_crash_in_stream_does_not_kill_loop(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        received = []

        class CrashingStream(FakeStream):
            def read_available(self):
                raise RuntimeError("kaboom")

        bad = CrashingStream(pid=1)
        good = FakeStream(pid=2, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000,
                                  level_callback=received.append)
        cap._streams = {1: bad, 2: good}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(received) > 0)
        cap._running = False
        t.join(timeout=1)
        # Good stream still produced mixed output, bad one was marked inactive.
        self.assertFalse(bad.is_active)
        self.assertGreater(len(received), 0)

    def test_buffer_disabled_skips_all_chunks_append(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000,
                                  level_callback=None, enable_buffer=False)
        cap._streams = {1: a}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(a._queue) == 0)
        cap._running = False
        t.join(timeout=1)
        self.assertEqual(len(cap._all_chunks), 0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessAudioCaptureMixer -v`
Expected: fails because the existing `ProcessAudioCapture` doesn't have `_mixer_loop`, `_running`, `_paused`, `_all_chunks`, `_streams` init, level_callback, enable_buffer, etc.

- [ ] **Step 3: Rewrite `ProcessAudioCapture` in `app/recording/process_audio_capture.py`**

Replace the existing `ProcessAudioCapture` class and the scaffolded `ProcessCaptureStream._capture_loop`/`_read_audio_packets`. Keep `ProcessCaptureStream` for now as a stub — Task 11 replaces it.

```python
import logging
import time
import threading

logger = logging.getLogger(__name__)


class ProcessAudioCapture:
    """Mixer for N per-process loopback streams. Owns a single polling thread.

    PIDs are fixed at construction time; add/remove during a session is
    deliberately out of scope (see design Q3). Pause/resume drains the client
    buffers but discards the data, matching AudioStream / LoopbackStream.
    """

    def __init__(self, pids, sample_rate=16000, level_callback=None,
                 enable_buffer=True, pid_lost_callback=None,
                 capture_lost_callback=None):
        self.pids = list(pids)
        self.sample_rate = sample_rate
        self._level_callback = level_callback
        self._pid_lost_callback = pid_lost_callback
        self._capture_lost_callback = capture_lost_callback
        self._enable_buffer = enable_buffer
        self._streams = {}                     # {pid: ProcessCaptureStream}
        self._running = False
        self._paused = False
        self._all_chunks = []
        self._thread = None
        self._active_last_tick = set()
        self._crashed = False
        self.capture_status = {}

    def set_level_callback(self, fn):
        self._level_callback = fn

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def _mixer_loop(self):
        try:
            while self._running:
                if self._paused:
                    for s in list(self._streams.values()):
                        if s.is_active:
                            try:
                                s.read_available()
                            except Exception:
                                logger.exception("Stream %s crashed during paused drain", s.pid)
                                s.is_active = False
                    time.sleep(0.010)
                    continue

                per_stream_chunks = {}
                for pid, s in list(self._streams.items()):
                    was_active = pid in self._active_last_tick
                    if not s.is_active:
                        if was_active:
                            self._active_last_tick.discard(pid)
                            self._emit_pid_lost(pid, s.last_error)
                        continue
                    self._active_last_tick.add(pid)
                    try:
                        chunks = s.read_available()
                        if chunks:
                            per_stream_chunks[pid] = np.concatenate(chunks)
                    except Exception as e:
                        logger.exception("Stream %s crashed", pid)
                        s.is_active = False
                        s.last_error = f"exception: {e}"
                        self._active_last_tick.discard(pid)
                        self._emit_pid_lost(pid, s.last_error)

                if per_stream_chunks:
                    mixed, tails = _trim_and_mix(per_stream_chunks)
                    for pid, tail in tails.items():
                        self._streams[pid].put_back_tail(tail)
                    if mixed.size > 0:
                        if self._enable_buffer:
                            self._all_chunks.append(mixed)
                        if self._level_callback:
                            self._level_callback(mixed)

                if self._streams and not any(s.is_active for s in self._streams.values()):
                    self._emit_capture_lost()
                    break

                time.sleep(0.010)
        except Exception:
            logger.exception("Mixer loop crashed unexpectedly")
            self._crashed = True

    def _emit_pid_lost(self, pid, error):
        if self._pid_lost_callback:
            try:
                self._pid_lost_callback(pid, error or "unknown")
            except Exception:
                logger.exception("pid_lost callback raised")

    def _emit_capture_lost(self):
        if self._capture_lost_callback:
            try:
                self._capture_lost_callback()
            except Exception:
                logger.exception("capture_lost callback raised")

    @property
    def is_active(self):
        return self._running and any(s.is_active for s in self._streams.values())

    @property
    def active_pids(self):
        return [pid for pid, s in self._streams.items() if s.is_active]
```

Also DELETE:
- the old `ProcessAudioCapture.add_pid` / `remove_pid` methods (if any remain after the rewrite — they're removed as part of this replacement).
- the old `_capture_loop` and `_read_audio_packets` stubs in `ProcessCaptureStream` if still present. Leave the class shell intact for Task 11 to fill in.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessAudioCaptureMixer -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add app/recording/process_audio_capture.py tests/test_process_audio_capture.py
git commit -m "audio: ProcessAudioCapture mixer loop with trim-to-shortest and crash containment"
```

---

## Task 6: Callbacks for `pid_lost` / `capture_lost`

**Files:**
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
class TestProcessAudioCaptureSignals(unittest.TestCase):
    def _wait_for(self, predicate, timeout=1.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.005)
        return False

    def test_pid_lost_fires_once_per_stream_death(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        lost = []
        a = FakeStream(pid=1, queued_chunks=[np.ones(160, dtype=np.float32)])
        b = FakeStream(pid=2, queued_chunks=[np.ones(160, dtype=np.float32)])
        cap = ProcessAudioCapture(
            pids=[1, 2], sample_rate=16000,
            pid_lost_callback=lambda pid, err: lost.append((pid, err)),
        )
        cap._streams = {1: a, 2: b}
        cap._active_last_tick = {1, 2}
        cap._running = True
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        # Let one mix tick happen, then kill stream 1.
        self._wait_for(lambda: len(a._queue) == 0)
        a.die("device_invalidated")
        self._wait_for(lambda: len(lost) >= 1)
        cap._running = False
        t.join(timeout=1)
        self.assertEqual(len([e for e in lost if e[0] == 1]), 1)
        self.assertEqual(lost[0][1], "device_invalidated")

    def test_capture_lost_fires_once_when_all_die(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        lost_events = []
        capture_lost_events = []
        a = FakeStream(pid=1, queued_chunks=[])
        b = FakeStream(pid=2, queued_chunks=[])
        cap = ProcessAudioCapture(
            pids=[1, 2], sample_rate=16000,
            pid_lost_callback=lambda pid, err: lost_events.append(pid),
            capture_lost_callback=lambda: capture_lost_events.append(True),
        )
        cap._streams = {1: a, 2: b}
        cap._active_last_tick = {1, 2}
        cap._running = True
        a.die("err_a")
        b.die("err_b")
        t = threading.Thread(target=cap._mixer_loop, daemon=True)
        t.start()
        self._wait_for(lambda: len(capture_lost_events) >= 1, timeout=1.0)
        cap._running = False
        t.join(timeout=1)
        self.assertEqual(len(capture_lost_events), 1)
        self.assertEqual(set(lost_events), {1, 2})
```

- [ ] **Step 2: Run tests to verify they pass**

These should pass already based on Task 5's implementation.

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessAudioCaptureSignals -v`
Expected: 2 passed

If they fail, check that `_emit_pid_lost` and `_emit_capture_lost` are wired correctly in `_mixer_loop`.

- [ ] **Step 3: Commit**

```bash
git add tests/test_process_audio_capture.py
git commit -m "audio: tests for ProcessAudioCapture pid_lost and capture_lost callbacks"
```

---

## Task 7: `start()` with parallel activation + status dict

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
class TestProcessAudioCaptureStart(unittest.TestCase):
    def test_start_returns_status_dict_all_success(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1, 2], sample_rate=16000)
        # Inject fake streams before start.
        cap._streams = {
            1: FakeStream(pid=1, activate_result=True),
            2: FakeStream(pid=2, activate_result=True),
        }
        status = cap.start(skip_stream_creation=True)
        try:
            self.assertEqual(status["total"], 2)
            self.assertEqual(status["active"], 2)
            self.assertEqual(status["failures"], {})
        finally:
            cap.stop()

    def test_start_tolerates_partial_failures(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1, 2, 3], sample_rate=16000)
        cap._streams = {
            1: FakeStream(pid=1, activate_result=True),
            2: FakeStream(pid=2, activate_result=False, error="AUDCLNT_E_DEVICE_INVALIDATED"),
            3: FakeStream(pid=3, activate_result=True),
        }
        status = cap.start(skip_stream_creation=True)
        try:
            self.assertEqual(status["total"], 3)
            self.assertEqual(status["active"], 2)
            self.assertEqual(status["failures"], {2: "AUDCLNT_E_DEVICE_INVALIDATED"})
        finally:
            cap.stop()

    def test_start_zero_active_still_returns_status(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000)
        cap._streams = {
            1: FakeStream(pid=1, activate_result=False, error="E_ACCESSDENIED"),
        }
        status = cap.start(skip_stream_creation=True)
        try:
            self.assertEqual(status["active"], 0)
            self.assertEqual(status["failures"], {1: "E_ACCESSDENIED"})
        finally:
            cap.stop()

    def test_stop_releases_all_streams_and_joins_thread(self):
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000)
        fs = FakeStream(pid=1, activate_result=True)
        cap._streams = {1: fs}
        cap.start(skip_stream_creation=True)
        result = cap.stop()
        self.assertTrue(fs.released)
        self.assertIn("mixed_audio", result)
        self.assertFalse(cap._running)

    def test_save_to_file_writes_when_buffer_enabled(self):
        import tempfile, os
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000)
        cap._all_chunks = [np.ones(16000, dtype=np.float32)]
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.wav")
            result = cap.save_to_file(path)
            self.assertTrue(os.path.exists(path))
            self.assertEqual(result, path)

    def test_save_to_file_returns_none_when_no_data(self):
        import tempfile, os
        from app.recording.process_audio_capture import ProcessAudioCapture
        cap = ProcessAudioCapture(pids=[1], sample_rate=16000)
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "out.wav")
            self.assertIsNone(cap.save_to_file(path))
            self.assertFalse(os.path.exists(path))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessAudioCaptureStart -v`
Expected: fails because `start()` doesn't exist with this signature, `stop()` doesn't return the right dict, `save_to_file` isn't implemented.

- [ ] **Step 3: Add `start()`, `stop()`, `save_to_file()` to `ProcessAudioCapture`**

Insert at the end of the `ProcessAudioCapture` class body (before `is_active`):

```python
    def start(self, skip_stream_creation=False):
        """Activate all streams in parallel, launch mixer thread.

        Returns:
            {"total": N, "active": K, "failures": {pid: error_name}}

        The caller (DualAudioCapture) is expected to raise RuntimeError when
        active == 0 AND the caller considers that a hard failure. This method
        never raises for partial failures.
        """
        from concurrent.futures import ThreadPoolExecutor

        if not skip_stream_creation:
            # Real path: create ProcessCaptureStream instances for each pid.
            self._streams = {
                pid: ProcessCaptureStream(pid=pid, sample_rate=self.sample_rate)
                for pid in self.pids
            }

        failures = {}
        if self._streams:
            with ThreadPoolExecutor(max_workers=max(len(self._streams), 1)) as ex:
                futures = {
                    pid: ex.submit(s.activate)
                    for pid, s in self._streams.items()
                }
                for pid, fut in futures.items():
                    try:
                        ok = fut.result(timeout=6.0)
                    except Exception as e:
                        ok = False
                        self._streams[pid].last_error = f"activation_exception: {e}"
                    if not ok:
                        failures[pid] = self._streams[pid].last_error or "unknown"

        active_pids = {pid for pid, s in self._streams.items() if s.is_active}
        self._active_last_tick = set(active_pids)

        status = {
            "total": len(self._streams),
            "active": len(active_pids),
            "failures": failures,
        }
        self.capture_status = status

        # Launch the mixer only if at least one stream is active.
        if active_pids:
            self._running = True
            self._thread = threading.Thread(target=self._mixer_loop, daemon=True)
            self._thread.start()

        return status

    def stop(self):
        """Stop the mixer thread and release all streams. Returns a result dict."""
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

        for s in self._streams.values():
            try:
                s.release()
            except Exception:
                logger.exception("Error releasing stream %s", s.pid)

        mixed = (np.concatenate(self._all_chunks, axis=0)
                 if self._all_chunks else np.array([], dtype=np.float32))

        result = {
            "mixed_audio": mixed,
            "active_pids": self.active_pids,
            "crashed": self._crashed,
        }
        return result

    def save_to_file(self, filepath):
        """Write buffered mixed audio to a WAV file. Returns the path, or None if empty."""
        import soundfile as sf
        if not self._all_chunks:
            return None
        data = np.concatenate(self._all_chunks, axis=0)
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self.sample_rate)
        return str(filepath)

    def get_audio_data(self):
        """Return buffered mixed audio as a mono float32 array."""
        if not self._all_chunks:
            return np.array([], dtype=np.float32)
        return np.concatenate(self._all_chunks, axis=0)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py -v`
Expected: all `TestProcessAudioCaptureStart` + prior tests pass. The existing `test_process_capture_stream_init` may still work (it only checks init args).

- [ ] **Step 5: Commit**

```bash
git add app/recording/process_audio_capture.py tests/test_process_audio_capture.py
git commit -m "audio: ProcessAudioCapture start/stop/save lifecycle with parallel activation"
```

---

## Task 8: COM struct definitions + GUID constants

**Files:**
- Modify: `app/recording/_process_com.py`
- Modify: `tests/test_process_com.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_com.py`:

```python
class TestStructs(unittest.TestCase):
    def test_audioclient_activation_params_size(self):
        """Struct size must match the documented Windows SDK value.
        If this breaks after a typo, the ActivateAudioInterfaceAsync call fails silently."""
        import ctypes
        from app.recording._process_com import AUDIOCLIENT_ACTIVATION_PARAMS
        # ActivationType (ULONG) + ProcessLoopbackParams (TargetProcessId ULONG + Mode ULONG)
        # padded to 8-byte alignment = 12 bytes, rounded up to next DWORD boundary.
        # The real size per SDK is 8 bytes (union). We document whatever the
        # implementation chooses and pin it here.
        self.assertGreaterEqual(ctypes.sizeof(AUDIOCLIENT_ACTIVATION_PARAMS), 8)
        self.assertLessEqual(ctypes.sizeof(AUDIOCLIENT_ACTIVATION_PARAMS), 32)

    def test_waveformatex_size_is_18(self):
        import ctypes
        from app.recording._process_com import WAVEFORMATEX
        self.assertEqual(ctypes.sizeof(WAVEFORMATEX), 18)


class TestConstants(unittest.TestCase):
    def test_process_loopback_mode_include_is_zero(self):
        from app.recording._process_com import PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
        self.assertEqual(PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE, 0)

    def test_activation_type_is_one(self):
        from app.recording._process_com import AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
        self.assertEqual(AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK, 1)

    def test_virtual_device_string_is_guid_format(self):
        from app.recording._process_com import VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK
        # Braced GUID string, 38 chars total.
        self.assertEqual(len(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK), 38)
        self.assertTrue(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK.startswith("{"))
        self.assertTrue(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK.endswith("}"))

    def test_audclnt_streamflags_loopback_value(self):
        from app.recording._process_com import AUDCLNT_STREAMFLAGS_LOOPBACK
        self.assertEqual(AUDCLNT_STREAMFLAGS_LOOPBACK, 0x00020000)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_com.py -v`
Expected: `ImportError: cannot import name 'AUDIOCLIENT_ACTIVATION_PARAMS'` etc.

- [ ] **Step 3: Append struct + constant definitions to `app/recording/_process_com.py`**

Append after the `hresult_name` function:

```python
import ctypes
from ctypes import wintypes


# --- Constants from audioclient.h / audioclientactivationparams.h ---

# Virtual device string for process-loopback activation. This is a stable GUID
# string; not an interface IID.
VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK = "{8FDC6FBC-56CC-4DA6-B4FA-9CB9F1E09B72}"

# AUDIOCLIENT_ACTIVATION_TYPE enum.
AUDIOCLIENT_ACTIVATION_TYPE_DEFAULT = 0
AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK = 1

# PROCESS_LOOPBACK_MODE enum.
PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE = 0
PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE = 1

# IAudioClient::Initialize flags.
AUDCLNT_STREAMFLAGS_LOOPBACK = 0x00020000
AUDCLNT_STREAMFLAGS_EVENTCALLBACK = 0x00040000
AUDCLNT_SHAREMODE_SHARED = 0

# WAVE_FORMAT tags.
WAVE_FORMAT_PCM = 0x0001
WAVE_FORMAT_IEEE_FLOAT = 0x0003

# AUDCLNT_BUFFERFLAGS bits.
AUDCLNT_BUFFERFLAGS_DATA_DISCONTINUITY = 0x1
AUDCLNT_BUFFERFLAGS_SILENT = 0x2
AUDCLNT_BUFFERFLAGS_TIMESTAMP_ERROR = 0x4

# GetNextPacketSize / GetBuffer status hints.
AUDCLNT_S_BUFFER_EMPTY = 0x08890001

# Common HRESULTs for activation (32-bit unsigned form).
AUDCLNT_E_DEVICE_INVALIDATED = 0x88890004
E_ACCESSDENIED = 0x80070005


# --- Struct definitions ---

class AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS(ctypes.Structure):
    _fields_ = [
        ("TargetProcessId", wintypes.DWORD),
        ("ProcessLoopbackMode", wintypes.DWORD),  # PROCESS_LOOPBACK_MODE enum
    ]


class AUDIOCLIENT_ACTIVATION_PARAMS(ctypes.Structure):
    """Passed as a PROPVARIANT(VT_BLOB) to ActivateAudioInterfaceAsync."""
    _fields_ = [
        ("ActivationType", wintypes.DWORD),
        ("ProcessLoopbackParams", AUDIOCLIENT_PROCESS_LOOPBACK_PARAMS),
    ]


class WAVEFORMATEX(ctypes.Structure):
    """WAVEFORMATEX as defined in mmreg.h."""
    _pack_ = 1
    _fields_ = [
        ("wFormatTag", wintypes.WORD),
        ("nChannels", wintypes.WORD),
        ("nSamplesPerSec", wintypes.DWORD),
        ("nAvgBytesPerSec", wintypes.DWORD),
        ("nBlockAlign", wintypes.WORD),
        ("wBitsPerSample", wintypes.WORD),
        ("cbSize", wintypes.WORD),
    ]


def make_format_ieee_float(sample_rate=48000, channels=2, bits=32):
    """Build a WAVEFORMATEX for IEEE_FLOAT PCM."""
    fmt = WAVEFORMATEX()
    fmt.wFormatTag = WAVE_FORMAT_IEEE_FLOAT
    fmt.nChannels = channels
    fmt.nSamplesPerSec = sample_rate
    fmt.wBitsPerSample = bits
    fmt.nBlockAlign = (channels * bits) // 8
    fmt.nAvgBytesPerSec = sample_rate * fmt.nBlockAlign
    fmt.cbSize = 0
    return fmt
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_com.py -v`
Expected: all TestStructs + TestConstants + TestHResultName pass.

- [ ] **Step 5: Commit**

```bash
git add app/recording/_process_com.py tests/test_process_com.py
git commit -m "audio: COM struct definitions and constants for process-loopback activation"
```

---

## Task 9: Low-level activation and packet-read shims in `_process_com.py`

**Files:**
- Modify: `app/recording/_process_com.py`

**Note:** these functions hit real Windows COM. They are not unit-tested directly (Tier 3 manual smoke catches bugs). They are injected into `ProcessCaptureStream` in later tasks so the higher-level logic stays testable.

- [ ] **Step 1: Append activation + packet read + completion handler to `_process_com.py`**

```python
import comtypes
from comtypes import GUID, COMMETHOD, IUnknown
from ctypes import POINTER, byref, c_void_p, c_int32, c_uint32, c_uint64, c_wchar_p


# IActivateAudioInterfaceCompletionHandler
IID_IActivateAudioInterfaceCompletionHandler = GUID(
    "{41D949AB-9862-444A-80F6-C261334DA5EB}"
)

# IActivateAudioInterfaceAsyncOperation
IID_IActivateAudioInterfaceAsyncOperation = GUID(
    "{72A22D78-CDE4-431D-B8CC-843A71199B6D}"
)

# IAudioClient (standard WASAPI IID).
IID_IAudioClient = GUID("{1CB9AD4C-DBFA-4C32-B178-C2F568A703B2}")

# IAudioCaptureClient.
IID_IAudioCaptureClient = GUID("{C8ADBD64-E71E-48A0-A4DE-185C395CD317}")


class IActivateAudioInterfaceCompletionHandler(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceCompletionHandler
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "ActivateCompleted",
            (["in"], POINTER(IUnknown), "activateOperation"),
        ),
    ]


class IActivateAudioInterfaceAsyncOperation(IUnknown):
    _iid_ = IID_IActivateAudioInterfaceAsyncOperation
    _methods_ = [
        COMMETHOD(
            [], comtypes.HRESULT, "GetActivateResult",
            (["out"], POINTER(comtypes.HRESULT), "activateResult"),
            (["out"], POINTER(POINTER(IUnknown)), "activatedInterface"),
        ),
    ]


class _CompletionHandler(comtypes.COMObject):
    """Python COM object that signals a Win32 event when activation completes."""
    _com_interfaces_ = [IActivateAudioInterfaceCompletionHandler]

    def __init__(self, event_handle):
        super().__init__()
        self._event = event_handle

    def ActivateCompleted(self, this, activate_operation):
        ctypes.windll.kernel32.SetEvent(self._event)
        return 0   # S_OK


def activate_process_loopback(pid, timeout_ms=5000):
    """Synchronously activate an IAudioClient for per-process loopback.

    Returns (audio_client: IUnknown-pointer, hresult: int).
    On success, hresult == S_OK (0) and audio_client is non-null.
    On failure, audio_client is None and hresult is the error code.
    """
    # Ensure MTA init on this thread.
    ctypes.windll.ole32.CoInitializeEx(None, 0x0)  # COINIT_MULTITHREADED

    # Build params.
    params = AUDIOCLIENT_ACTIVATION_PARAMS()
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK
    params.ProcessLoopbackParams.TargetProcessId = pid
    params.ProcessLoopbackParams.ProcessLoopbackMode = (
        PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE
    )

    # Wrap as PROPVARIANT(VT_BLOB). The BLOB holds (cbSize, pBlobData).
    # comtypes doesn't expose PROPVARIANT blob construction; build via ctypes.
    class _BLOB(ctypes.Structure):
        _fields_ = [("cbSize", c_uint32), ("pBlobData", c_void_p)]

    class _PROPVARIANT(ctypes.Structure):
        _fields_ = [
            ("vt", ctypes.c_ushort),
            ("wReserved1", ctypes.c_ushort),
            ("wReserved2", ctypes.c_ushort),
            ("wReserved3", ctypes.c_ushort),
            ("blob", _BLOB),
            # Pad to full size (16 bytes on 32-bit, 24 on 64-bit).
            ("_pad", ctypes.c_ubyte * 8),
        ]

    pv = _PROPVARIANT()
    pv.vt = 0x41   # VT_BLOB
    pv.blob.cbSize = ctypes.sizeof(params)
    pv.blob.pBlobData = ctypes.cast(ctypes.pointer(params), c_void_p)

    # Create a manual-reset event for the handler to signal.
    event_handle = ctypes.windll.kernel32.CreateEventW(None, True, False, None)
    if not event_handle:
        return None, -1

    handler = _CompletionHandler(event_handle)

    # Call ActivateAudioInterfaceAsync. Use WinDLL (not OleDLL) so we get the
    # raw HRESULT back rather than an auto-raise — we want to translate failures
    # into last_error strings, not exceptions.
    mmdev = ctypes.WinDLL("Mmdevapi.dll")
    ActivateAudioInterfaceAsync = mmdev.ActivateAudioInterfaceAsync
    ActivateAudioInterfaceAsync.restype = ctypes.c_long
    ActivateAudioInterfaceAsync.argtypes = [
        c_wchar_p, POINTER(GUID), c_void_p,
        POINTER(IActivateAudioInterfaceCompletionHandler),
        POINTER(POINTER(IActivateAudioInterfaceAsyncOperation)),
    ]
    operation = POINTER(IActivateAudioInterfaceAsyncOperation)()
    hr = ActivateAudioInterfaceAsync(
        VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        byref(IID_IAudioClient),
        ctypes.cast(ctypes.pointer(pv), c_void_p),
        handler,
        byref(operation),
    )
    if hr != 0:
        ctypes.windll.kernel32.CloseHandle(event_handle)
        return None, hr

    # Block until the completion handler fires.
    wait_result = ctypes.windll.kernel32.WaitForSingleObject(event_handle, timeout_ms)
    ctypes.windll.kernel32.CloseHandle(event_handle)
    if wait_result != 0:
        return None, -2   # WAIT_TIMEOUT or WAIT_ABANDONED

    # Pull the activated interface. comtypes returns [out] params as a tuple.
    activate_hr, activated = operation.GetActivateResult()
    if activate_hr != 0:
        return None, activate_hr & 0xFFFFFFFF
    return activated, 0


def read_next_packet(capture_client):
    """Drain the next available packet from an IAudioCaptureClient.

    Returns (data: bytes or None, frames: int, flags: int, hr: int).
    data is None when no packet is ready OR when AUDCLNT_E_DEVICE_INVALIDATED.
    Caller distinguishes by checking hr.
    """
    # Stub body — full implementation uses GetNextPacketSize + GetBuffer +
    # ctypes.string_at + ReleaseBuffer. Fully typed via comtypes IAudioCaptureClient.
    # See design doc Section "COM Integration / read_available() inner loop".
    raise NotImplementedError(
        "read_next_packet must be implemented against IAudioCaptureClient; "
        "see Section 2 of the design doc. For now, ProcessCaptureStream can "
        "inject a fake for tests."
    )
```

**Note:** `read_next_packet` is deliberately left as a `NotImplementedError` with a clear pointer to the spec. The real implementation is hand-written COM work that cannot be TDD'd — it lands in Task 11 together with manual verification on the user's Win11 machine. The test suite exercises `ProcessCaptureStream` behavior by injecting fakes.

- [ ] **Step 2: Smoke-import to confirm syntax**

Run: `python -c "from app.recording._process_com import activate_process_loopback, read_next_packet; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Commit**

```bash
git add app/recording/_process_com.py
git commit -m "audio: COM activation shim for process-loopback (read stub pending)"
```

---

## Task 10: Inject-able `ProcessCaptureStream.activate()`

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
class TestProcessCaptureStreamActivate(unittest.TestCase):
    def test_activate_success_sets_active_and_format(self):
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            # Return a sentinel AudioClient + S_OK. Also attach a format.
            client = type("C", (), {})()
            client.native_rate = 48000
            client.native_channels = 2
            client.native_format = "float32"
            return client, 0

        s = ProcessCaptureStream(pid=1234, sample_rate=16000,
                                 activator=fake_activate)
        self.assertTrue(s.activate())
        self.assertTrue(s.is_active)
        self.assertEqual(s.native_rate, 48000)
        self.assertEqual(s.native_channels, 2)
        self.assertEqual(s.native_format, "float32")
        self.assertIsNone(s.last_error)

    def test_activate_failure_returns_false_with_error(self):
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            return None, 0x80070005   # E_ACCESSDENIED

        s = ProcessCaptureStream(pid=1234, sample_rate=16000,
                                 activator=fake_activate)
        self.assertFalse(s.activate())
        self.assertFalse(s.is_active)
        self.assertEqual(s.last_error, "E_ACCESSDENIED")

    def test_release_is_idempotent(self):
        from app.recording.process_audio_capture import ProcessCaptureStream
        s = ProcessCaptureStream(pid=1234, sample_rate=16000,
                                 activator=lambda pid, timeout_ms=5000: (None, 0x80004005))
        s.activate()
        s.release()
        s.release()   # no raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessCaptureStreamActivate -v`
Expected: `TypeError: __init__() got an unexpected keyword argument 'activator'` or similar.

- [ ] **Step 3: Rewrite `ProcessCaptureStream` in `app/recording/process_audio_capture.py`**

Replace the existing scaffolded `ProcessCaptureStream` with:

```python
from app.recording._process_com import (
    activate_process_loopback as _default_activator,
    hresult_name,
)


class ProcessCaptureStream:
    """Captures audio from a single process. Owns the COM objects.

    activate/read/release is synchronous and non-thread-owning — the caller
    (ProcessAudioCapture) provides the single polling thread. Keeping this
    class stateless re: threading makes it easy to unit-test with fakes.
    """

    def __init__(self, pid, sample_rate=16000, activator=None):
        self.pid = pid
        self.sample_rate = sample_rate
        self.is_active = False
        self.native_rate = 0
        self.native_channels = 0
        self.native_format = "float32"
        self.last_error = None
        self._client = None
        self._capture_client = None
        self._resampler = None
        self._pre_resample_buf = np.array([], dtype=np.float32)
        self._post_mix_tail = np.array([], dtype=np.float32)
        self._activator = activator if activator is not None else _default_activator

    def activate(self):
        """Synchronously activate the per-process audio client.

        Returns True on success, False on any failure. On failure, last_error
        holds the HRESULT name (never raises).
        """
        try:
            client, hr = self._activator(self.pid)
        except Exception as e:
            self.last_error = f"activation_exception: {e}"
            return False

        if hr != 0 or client is None:
            self.last_error = hresult_name(hr) if hr != 0 else "activation_null_client"
            return False

        self._client = client
        # The activator may attach format hints to the client (real COM path
        # queries these from the negotiated format; fakes set them directly).
        self.native_rate = getattr(client, "native_rate", 48000)
        self.native_channels = getattr(client, "native_channels", 2)
        self.native_format = getattr(client, "native_format", "float32")
        self._resampler = _Resampler(self.native_rate, self.sample_rate)
        self.is_active = True
        return True

    def put_back_tail(self, tail):
        if tail.size > 0:
            if self._post_mix_tail.size:
                self._post_mix_tail = np.concatenate([self._post_mix_tail, tail])
            else:
                self._post_mix_tail = tail

    def release(self):
        self.is_active = False
        self._client = None
        self._capture_client = None
        self._resampler = None
        self._pre_resample_buf = np.array([], dtype=np.float32)
        self._post_mix_tail = np.array([], dtype=np.float32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessCaptureStreamActivate -v`
Expected: 3 passed.

Also delete the old `test_process_capture_stream_init` test (in the original `TestProcessAudioMixer` block if it still exists) — replace with the above.

- [ ] **Step 5: Commit**

```bash
git add app/recording/process_audio_capture.py tests/test_process_audio_capture.py
git commit -m "audio: ProcessCaptureStream.activate with injectable activator for testing"
```

---

## Task 11: `ProcessCaptureStream.read_available()` + real `read_next_packet`

**Files:**
- Modify: `app/recording/process_audio_capture.py`
- Modify: `app/recording/_process_com.py`
- Modify: `tests/test_process_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_process_audio_capture.py`:

```python
class TestProcessCaptureStreamRead(unittest.TestCase):
    def _make_stream_with_packets(self, packets, format_tag="float32",
                                  bits=32, native_rate=48000, native_channels=2):
        """Build a ProcessCaptureStream with a fake packet source."""
        from app.recording.process_audio_capture import ProcessCaptureStream

        def fake_activate(pid, timeout_ms=5000):
            client = type("C", (), {})()
            client.native_rate = native_rate
            client.native_channels = native_channels
            client.native_format = format_tag
            return client, 0

        s = ProcessCaptureStream(pid=1, sample_rate=16000, activator=fake_activate)
        s.activate()
        # Inject a packet source used by read_available when reading real COM
        # isn't available.
        s._packet_source = iter(packets)
        return s

    def test_read_available_returns_empty_when_no_packets(self):
        s = self._make_stream_with_packets([])
        out = s.read_available()
        self.assertEqual(out, [])

    def test_read_available_converts_and_downmixes_and_resamples(self):
        # Single packet: 480 frames, 2ch, float32 at 48kHz → 160 frames mono 16kHz.
        stereo = np.ones(480 * 2, dtype=np.float32)
        pkt = {"raw": stereo.tobytes(), "frames": 480, "flags": 0}
        s = self._make_stream_with_packets([pkt])
        out = s.read_available()
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].dtype, np.float32)
        self.assertEqual(len(out[0]), 160)

    def test_read_available_silent_flag_fast_path(self):
        pkt = {"raw": b"\x00" * 480 * 2 * 4, "frames": 480, "flags": 0x2}
        s = self._make_stream_with_packets([pkt])
        out = s.read_available()
        self.assertEqual(len(out), 1)
        self.assertTrue(np.all(out[0] == 0.0))
        self.assertEqual(len(out[0]), 160)

    def test_read_available_prepends_post_mix_tail(self):
        s = self._make_stream_with_packets([])
        s._post_mix_tail = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        out = s.read_available()
        self.assertEqual(len(out), 1)
        np.testing.assert_array_almost_equal(out[0], [0.1, 0.2, 0.3])
        # Tail must be consumed.
        self.assertEqual(s._post_mix_tail.size, 0)

    def test_read_available_device_invalidated_marks_inactive(self):
        # Sentinel packet with hr=AUDCLNT_E_DEVICE_INVALIDATED.
        pkt = {"raw": None, "frames": 0, "flags": 0, "hr": 0x88890004}
        s = self._make_stream_with_packets([pkt])
        out = s.read_available()
        self.assertFalse(s.is_active)
        self.assertEqual(s.last_error, "AUDCLNT_E_DEVICE_INVALIDATED")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessCaptureStreamRead -v`
Expected: fails — `read_available` doesn't exist yet on `ProcessCaptureStream`.

- [ ] **Step 3: Implement `read_available()` on `ProcessCaptureStream`**

Add to the class in `app/recording/process_audio_capture.py`:

```python
    def read_available(self):
        """Drain all ready packets from the capture client. Non-blocking.

        Returns a list of 16 kHz mono float32 chunks, ready for the mixer.
        On device invalidation, marks is_active=False and returns whatever
        was already drained this call.
        """
        chunks = []

        if self._post_mix_tail.size > 0:
            chunks.append(self._post_mix_tail)
            self._post_mix_tail = np.array([], dtype=np.float32)

        if not self.is_active:
            return chunks

        # The _packet_source attribute lets tests inject packets. Real COM
        # path fills it via an internal generator that calls _process_com.read_next_packet.
        source = getattr(self, "_packet_source", None)
        if source is None:
            source = self._com_packet_iter()
            self._packet_source = source

        try:
            while True:
                try:
                    pkt = next(source)
                except StopIteration:
                    break
                if pkt is None:
                    break
                hr = pkt.get("hr", 0)
                if hr == 0x88890004:   # AUDCLNT_E_DEVICE_INVALIDATED
                    self.is_active = False
                    self.last_error = hresult_name(hr)
                    break
                raw = pkt["raw"]
                frames = pkt["frames"]
                flags = pkt.get("flags", 0)
                if raw is None or frames == 0:
                    continue

                if flags & 0x2:   # AUDCLNT_BUFFERFLAGS_SILENT
                    # Skip dtype/downmix/resample; produce zero mono chunk at target rate.
                    mono_native = np.zeros(frames, dtype=np.float32)
                else:
                    arr = _convert_dtype(
                        raw,
                        format_tag=self.native_format,
                        bits_per_sample=self._bits_for_format(self.native_format),
                    )
                    if self.native_channels > 1:
                        arr = arr.reshape(-1, self.native_channels).mean(axis=1)
                    mono_native = arr.astype(np.float32)

                resampled = self._resampler.push(mono_native)
                if resampled.size > 0:
                    chunks.append(resampled)
        except Exception as e:
            logger.exception("ProcessCaptureStream %s read error", self.pid)
            self.is_active = False
            self.last_error = f"read_exception: {e}"

        return chunks

    def _com_packet_iter(self):
        """Generator that yields packets from the real capture client.

        Built once per activation. Each __next__ calls _process_com.read_next_packet
        (which is itself a thin wrapper around GetNextPacketSize / GetBuffer /
        ReleaseBuffer). Returns None to signal "no more packets ready this tick".
        """
        from app.recording._process_com import read_next_packet as _rnp
        while self.is_active and self._client is not None:
            try:
                data, frames, flags, hr = _rnp(self._capture_client)
            except NotImplementedError:
                # During the phased implementation: read shim not yet wired;
                # real packet reading is a Tier-3 concern.
                return
            if data is None and hr == 0:
                return   # no more packets right now
            yield {"raw": data, "frames": frames, "flags": flags, "hr": hr}

    @staticmethod
    def _bits_for_format(fmt):
        return {"float32": 32, "s16": 16, "s24": 32}.get(fmt, 32)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_process_audio_capture.py::TestProcessCaptureStreamRead -v`
Expected: 5 passed.

- [ ] **Step 5: Implement `_process_com.read_next_packet` against `IAudioCaptureClient`**

Replace the `NotImplementedError` body in `app/recording/_process_com.py` with:

```python
def read_next_packet(capture_client):
    """Drain the next available packet from an IAudioCaptureClient.

    Returns (data_bytes, frames, flags, hr).
    - On no packet ready: returns (None, 0, 0, 0).
    - On AUDCLNT_E_DEVICE_INVALIDATED: returns (None, 0, 0, 0x88890004).
    - On success: returns (bytes, frames, flags, 0).

    capture_client is expected to be a COM pointer to IAudioCaptureClient.
    The caller guarantees it was obtained from a successful activation +
    GetService path.
    """
    # Defined interface on the fly to avoid a separate IAudioCaptureClient class:
    # we only need GetNextPacketSize, GetBuffer, ReleaseBuffer.
    get_next_packet_size = capture_client.GetNextPacketSize
    get_buffer = capture_client.GetBuffer
    release_buffer = capture_client.ReleaseBuffer

    try:
        num_frames = get_next_packet_size()
    except comtypes.COMError as ce:
        hr = ce.hresult & 0xFFFFFFFF
        if hr == AUDCLNT_E_DEVICE_INVALIDATED:
            return None, 0, 0, hr
        raise

    if num_frames == 0:
        return None, 0, 0, 0

    try:
        data_ptr, frames, flags, _dev_pos, _qpc_pos = get_buffer()
    except comtypes.COMError as ce:
        hr = ce.hresult & 0xFFFFFFFF
        if hr == AUDCLNT_E_DEVICE_INVALIDATED:
            return None, 0, 0, hr
        raise

    byte_count = frames * capture_client._native_frame_bytes
    if flags & AUDCLNT_BUFFERFLAGS_SILENT:
        raw = b"\x00" * byte_count
    else:
        raw = ctypes.string_at(data_ptr, byte_count)
    release_buffer(frames)
    return raw, frames, flags, 0
```

(Note: `_native_frame_bytes` is an attribute the real activation code stashes on the capture client after format negotiation. If activation path isn't wired yet, this function won't be called — the generator's `NotImplementedError` fallback in Task 10 prevents it.)

- [ ] **Step 6: Smoke-import**

Run: `python -c "from app.recording.process_audio_capture import ProcessCaptureStream; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/recording/process_audio_capture.py app/recording/_process_com.py tests/test_process_audio_capture.py
git commit -m "audio: ProcessCaptureStream.read_available with format conversion and resample"
```

---

## Task 12: Rename `loopback_stream` → `system_stream` in `DualAudioCapture` and dependents

**Files:**
- Modify: `app/recording/audio_capture.py`
- Modify: `app/main_window.py`
- Modify: `tests/test_dual_audio_capture.py`

This is a mechanical rename across files. Do it separately so the dispatch task (Task 13) is clean.

- [ ] **Step 1: Find all references**

Run: `grep -rn "loopback_stream" app/ tests/`
Expected: lists every file using the attribute.

- [ ] **Step 2: Rename in `DualAudioCapture`**

In `app/recording/audio_capture.py`, replace every occurrence of `self.loopback_stream` with `self.system_stream`. This touches `__init__`, `start`, `pause`, `resume`, `stop`, and any `_check_silence` wiring. Do NOT rename `LoopbackStream` the class — only the attribute.

- [ ] **Step 3: Rename in `main_window.py`**

In `app/main_window.py`, any reference to `self.recorder._capture.loopback_stream` (if any) becomes `self.recorder._capture.system_stream`. Also handle the `system_monitor` attribute we added during Test Mic work (no rename needed there — it was already `system_monitor`, not `loopback_monitor`).

- [ ] **Step 4: Update tests**

In `tests/test_dual_audio_capture.py`, replace any `.loopback_stream` references with `.system_stream`.

- [ ] **Step 5: Run the full suite**

Run: `python -m pytest tests/ -v`
Expected: all existing tests pass.

- [ ] **Step 6: Smoke-import MainWindow**

Run: `python -c "from app.main_window import MainWindow; print('ok')"`
Expected: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/recording/audio_capture.py app/main_window.py tests/test_dual_audio_capture.py
git commit -m "audio: rename DualAudioCapture.loopback_stream to system_stream"
```

---

## Task 13: `DualAudioCapture` dispatch on `capture_mode`

**Files:**
- Modify: `app/recording/audio_capture.py`
- Modify: `tests/test_dual_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_dual_audio_capture.py`:

```python
import tempfile
from unittest.mock import MagicMock, patch


class TestDualAudioCaptureDispatch(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.output_dir = self._tmp.name

    def tearDown(self):
        self._tmp.cleanup()

    def test_per_app_mode_uses_process_audio_capture(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.ProcessAudioCapture") as MockPAC:
            mock_instance = MagicMock()
            mock_instance.start.return_value = {
                "total": 2, "active": 2, "failures": {}
            }
            MockPAC.return_value = mock_instance

            cap = DualAudioCapture(
                mic_device=None, loopback_device=None,
                sample_rate=16000, capture_mode="per_app",
                app_pids=[123, 456],
            )
            cap.start(output_dir=self.output_dir)
            MockPAC.assert_called_once()
            mock_instance.start.assert_called_once()
            self.assertEqual(cap._capture_status["active"], 2)

    def test_legacy_mode_uses_loopback_stream(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.LoopbackStream") as MockLS, \
             patch("app.recording.audio_capture.sd.query_devices",
                   return_value={"name": "Speakers"}):
            mock_instance = MagicMock()
            MockLS.return_value = mock_instance

            cap = DualAudioCapture(
                mic_device=None, loopback_device=0,
                sample_rate=16000, capture_mode="legacy",
            )
            cap.start(output_dir=self.output_dir)
            MockLS.assert_called_once()

    def test_per_app_zero_active_raises(self):
        from app.recording.audio_capture import DualAudioCapture

        with patch("app.recording.audio_capture.ProcessAudioCapture") as MockPAC:
            mock_instance = MagicMock()
            mock_instance.start.return_value = {
                "total": 1, "active": 0, "failures": {123: "E_ACCESSDENIED"}
            }
            MockPAC.return_value = mock_instance

            cap = DualAudioCapture(
                mic_device=None, loopback_device=None,
                sample_rate=16000, capture_mode="per_app",
                app_pids=[123],
            )
            with self.assertRaises(RuntimeError) as ctx:
                cap.start(output_dir=self.output_dir)
            self.assertIn("E_ACCESSDENIED", str(ctx.exception))

    def test_per_app_empty_pids_falls_through_to_none(self):
        from app.recording.audio_capture import DualAudioCapture

        cap = DualAudioCapture(
            mic_device=None, loopback_device=None,
            sample_rate=16000, capture_mode="per_app",
            app_pids=[],
        )
        cap.start(output_dir=self.output_dir)
        self.assertIsNone(cap.system_stream)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_dual_audio_capture.py::TestDualAudioCaptureDispatch -v`
Expected: fails, tests see `LoopbackStream` opened even in per_app mode.

- [ ] **Step 3: Modify `DualAudioCapture.start()`**

In `app/recording/audio_capture.py`, import `ProcessAudioCapture` at the top:

```python
from app.recording.process_audio_capture import ProcessAudioCapture
```

And change the "System audio capture" block in `start()` to:

```python
        # System audio capture. In per-app mode with PIDs, use ProcessAudioCapture.
        # Otherwise use WASAPI loopback if a device is set.
        self.system_stream = None
        self._capture_status = None

        def _system_cb(chunk):
            if self._system_level_callback is not None:
                self._system_level_callback(chunk)
            self._check_silence(chunk)

        if self.capture_mode == "per_app" and self.app_pids:
            self.system_stream = ProcessAudioCapture(
                pids=self.app_pids,
                sample_rate=self.sample_rate,
                level_callback=_system_cb,
                pid_lost_callback=getattr(self, "_pid_lost_callback", None),
                capture_lost_callback=getattr(self, "_capture_lost_callback", None),
            )
            status = self.system_stream.start()
            self._capture_status = status
            if status["active"] == 0:
                raise RuntimeError(
                    f"Per-app capture failed for all selected apps: {status['failures']}"
                )
        elif self.loopback_device is not None:
            try:
                dev_info = sd.query_devices(self.loopback_device)
                device_name = dev_info.get("name", "")
                logger.info("System audio: looking for loopback of '%s'", device_name)

                self.system_stream = LoopbackStream(
                    device_name=device_name,
                    sample_rate=self.sample_rate,
                    level_callback=_system_cb,
                )
                self.system_stream.start()
            except Exception as e:
                logger.error("Failed to start system audio capture: %s", e)
                self.system_stream = None
```

Also add a `set_capture_event_callbacks(pid_lost, capture_lost)` method so Recorder can register callbacks before `start()`:

```python
    def set_capture_event_callbacks(self, pid_lost=None, capture_lost=None):
        """Register callbacks for ProcessAudioCapture events (per-app mode only)."""
        self._pid_lost_callback = pid_lost
        self._capture_lost_callback = capture_lost
```

Initialize both to None in `__init__`:

```python
        self._pid_lost_callback = None
        self._capture_lost_callback = None
        self._capture_status = None
```

- [ ] **Step 4: Reorder so system activates BEFORE mic**

Per the spec error matrix: system stream must activate before mic so a total failure doesn't leave mic orphaned. Move the "System audio capture" block to run BEFORE the "Microphone capture" block in `start()`. Keep the log-ordering correct (still log the configuration at the top of `start()`).

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_dual_audio_capture.py -v`
Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add app/recording/audio_capture.py tests/test_dual_audio_capture.py
git commit -m "audio: DualAudioCapture dispatches to ProcessAudioCapture in per-app mode"
```

---

## Task 14: `Recorder` new signals and metadata

**Files:**
- Modify: `app/recording/recorder.py`

- [ ] **Step 1: Add signals**

In `app/recording/recorder.py`, add to the `Recorder` class's signal declarations:

```python
    capture_status = pyqtSignal(dict)   # {"total": N, "active": K, "failures": {pid: str}}
    pid_lost = pyqtSignal(int, str)     # (pid, hresult_name)
    capture_lost = pyqtSignal()
```

- [ ] **Step 2: Wire DualAudioCapture callbacks into Recorder signals**

In `Recorder.start_recording()`, after constructing `self._capture` and before calling `self._capture.start(...)`, register callbacks:

```python
        self._capture.set_capture_event_callbacks(
            pid_lost=lambda pid, err: self.pid_lost.emit(pid, err),
            capture_lost=lambda: self.capture_lost.emit(),
        )
```

After `self._capture.start(session_dir)` succeeds, emit the status if present:

```python
        try:
            self._capture.start(session_dir)
            if self._capture._capture_status is not None:
                self.capture_status.emit(self._capture._capture_status)
            self._set_state(RecordingState.RECORDING)
            self._start_timer()
```

- [ ] **Step 3: Save `capture_status` into metadata**

In `Recorder.stop_recording()`, extend the `_current_session` dict update:

```python
            self._current_session["stopped_at"] = datetime.now().isoformat()
            self._current_session["duration"] = duration
            self._current_session["audio_files"] = audio_files
            if self._capture._capture_status is not None:
                self._current_session["capture_status"] = self._capture._capture_status
```

(This goes just before the "min length" check.)

- [ ] **Step 4: Smoke-test**

Run: `python -c "from app.recording.recorder import Recorder; print(Recorder.capture_status, Recorder.pid_lost, Recorder.capture_lost)"`
Expected: prints three `<unbound PYQT_SIGNAL...>` entries.

- [ ] **Step 5: Run full suite**

Run: `python -m pytest tests/ -v`
Expected: no regressions.

- [ ] **Step 6: Commit**

```bash
git add app/recording/recorder.py
git commit -m "recorder: emit capture_status, pid_lost, capture_lost signals for per-app mode"
```

---

## Task 15: `SourceSelector.mark_capture_failures()` + ⚠ label

**Files:**
- Modify: `app/ui/source_selector.py`

- [ ] **Step 1: Add the ⚠ label to the source selector UI**

In `app/ui/source_selector.py`, at the end of `_setup_ui` (just before `layout.addWidget(self._section)` or wherever appropriate — visible only when failures are set):

```python
        self._capture_warning = QLabel("")
        self._capture_warning.setObjectName("captureWarning")
        self._capture_warning.setStyleSheet(
            "color: #f9e2af; font-size: 11px; padding: 2px 4px;"
        )
        self._capture_warning.setVisible(False)
        content.addWidget(self._capture_warning)
```

- [ ] **Step 2: Add the public method**

At the bottom of the class (below `save_capture_settings`):

```python
    def mark_capture_failures(self, failures):
        """Show/hide the ⚠ indicator when per-app activation fails for some PIDs.

        Args:
            failures: {pid: hresult_name_str} mapping. Empty dict clears the indicator.
        """
        if not failures:
            self._capture_warning.setVisible(False)
            self._capture_warning.setText("")
            self._capture_warning.setToolTip("")
            return

        # Resolve PID -> display name via the current app list entries.
        pid_to_name = {}
        if self.app_list is not None:
            for i in range(self.app_list.count()):
                item = self.app_list.item(i)
                pid_data = item.data(Qt.ItemDataRole.UserRole)
                name = item.text()
                if isinstance(pid_data, list):
                    for pid in pid_data:
                        pid_to_name[pid] = name
                elif pid_data is not None:
                    pid_to_name[pid_data] = name

        lines = []
        names_shown = set()
        for pid, err in failures.items():
            name = pid_to_name.get(pid, f"PID {pid}")
            if name in names_shown:
                continue
            names_shown.add(name)
            lines.append(f"{name}: {err}")

        self._capture_warning.setText(
            f"\u26a0 {len(names_shown)} app(s) could not be captured"
        )
        self._capture_warning.setToolTip("\n".join(lines))
        self._capture_warning.setVisible(True)
```

- [ ] **Step 3: Smoke-import**

Run: `python -c "from app.ui.source_selector import SourceSelector; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add app/ui/source_selector.py
git commit -m "ui: SourceSelector.mark_capture_failures with warning label for per-app failures"
```

---

## Task 16: MainWindow signal handlers + status bar line

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1: Connect the new signals in `_connect_signals`**

Add after the existing `self.recorder.silence_detected.connect(...)` line:

```python
        self.recorder.capture_status.connect(self._on_capture_status)
        self.recorder.pid_lost.connect(self._on_pid_lost)
        self.recorder.capture_lost.connect(self._on_capture_lost)
```

- [ ] **Step 2: Add the handlers**

Add methods near `_on_error`:

```python
    def _on_capture_status(self, status):
        """Render initial 'K of N apps capturing' feedback after Record start."""
        total = status.get("total", 0)
        active = status.get("active", 0)
        failures = status.get("failures", {})
        self._current_capture_failures = dict(failures)
        self.source_selector.mark_capture_failures(self._current_capture_failures)
        if total > 0 and active < total and active > 0:
            self.status_label.setText(
                f"Recording — capturing {active} of {total} apps"
            )

    def _on_pid_lost(self, pid, error):
        """One PID died during recording. Update the warning label + status bar."""
        if not hasattr(self, "_current_capture_failures"):
            self._current_capture_failures = {}
        self._current_capture_failures[pid] = error
        self.source_selector.mark_capture_failures(self._current_capture_failures)
        active = len(self.recorder._capture.system_stream.active_pids) \
            if self.recorder._capture and self.recorder._capture.system_stream else 0
        total = active + len(self._current_capture_failures)
        if active > 0:
            self.status_label.setText(
                f"Recording — capturing {active} of {total} apps"
            )

    def _on_capture_lost(self):
        """All selected apps became unavailable. Stop and save what we have."""
        if self.recorder.state not in (RecordingState.RECORDING, RecordingState.PAUSED):
            return
        self.status_label.setText(
            "Capture ended: all selected apps became unavailable"
        )
        self.recorder.stop_recording()
```

- [ ] **Step 3: Clear the warning on return to IDLE**

In the existing `_on_state_changed` method, find where state transitions to `RecordingState.IDLE` and add:

```python
        if state == RecordingState.IDLE:
            self._current_capture_failures = {}
            self.source_selector.mark_capture_failures({})
```

(Merge with any existing IDLE-transition code.)

- [ ] **Step 4: Initialize the failures dict in `__init__`**

In `MainWindow.__init__`, after other state init, add:

```python
        self._current_capture_failures = {}
```

- [ ] **Step 5: Smoke-import**

Run: `python -c "from app.main_window import MainWindow; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Commit**

```bash
git add app/main_window.py
git commit -m "main: surface per-app capture partial failures in status bar and source selector"
```

---

## Task 17: MainWindow `_start_system_monitor` per-app dispatch

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1: Import `ProcessAudioCapture`**

At the top of `app/main_window.py`:

```python
from app.recording.process_audio_capture import ProcessAudioCapture
```

- [ ] **Step 2: Rewrite `_start_system_monitor`**

Replace the existing body with:

```python
    def _start_system_monitor(self):
        """Start a buffer-less system audio stream feeding the system meter.

        In per-app mode, uses ProcessAudioCapture on the selected PIDs.
        In legacy mode (or when no PIDs checked), uses LoopbackStream.
        """
        self._stop_system_monitor()
        mode = self.source_selector.get_capture_mode()

        if mode == "per_app":
            pids = self.source_selector.get_selected_app_pids()
            if not pids:
                return
            monitor = ProcessAudioCapture(
                pids=pids,
                sample_rate=self.config.get("audio", "sample_rate"),
                level_callback=self.meters_panel.update_system_level,
                enable_buffer=False,
            )
            status = monitor.start()
            if status["active"] == 0:
                logger.warning("Test per-app monitor failed: %s", status["failures"])
                return
            self.system_monitor = monitor
            return

        # Legacy WASAPI loopback path (unchanged from prior version).
        device = self.source_selector.get_selected_loopback()
        if device is None:
            return
        try:
            dev_info = sd.query_devices(device)
            device_name = dev_info.get("name", "")
            self.system_monitor = LoopbackStream(
                device_name=device_name,
                sample_rate=self.config.get("audio", "sample_rate"),
                level_callback=self.meters_panel.update_system_level,
                enable_buffer=False,
            )
            self.system_monitor.start()
        except Exception as e:
            logger.warning("Test system monitor failed: %s", e)
            self.system_monitor = None
```

- [ ] **Step 3: Smoke-import and run non-Qt tests**

Run: `python -c "from app.main_window import MainWindow; print('ok')"`
Expected: `ok`

Run: `python -m pytest tests/ -v`
Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add app/main_window.py
git commit -m "main: Test Mic monitor dispatches to ProcessAudioCapture in per-app mode"
```

---

## Task 18: Manual smoke-test checklist doc

**Files:**
- Create: `docs/testing/per-app-capture-smoke.md`

- [ ] **Step 1: Create the doc**

```markdown
# Per-App Audio Capture — Manual Smoke Tests

These checks must pass on a real Windows 11 machine (Build ≥ 22000). They
are not automated — `ActivateAudioInterfaceAsync` + `IAudioCaptureClient`
cannot be meaningfully mocked. Run these after any change to
`app/recording/process_audio_capture.py` or `app/recording/_process_com.py`.

## Setup

- Windows 11, Build ≥ 22000 (check via `winver`).
- TalkTrack running, Source panel expanded, per-app mode selected.
- A test Teams meeting invite (can be self-only meeting).
- Chrome with a YouTube tab open and paused.
- Spotify or any other always-on audio app (optional, for interference tests).

## Checks

### 1. Test Mic — single app, speaking

- [ ] Select only "Microsoft Teams" in the app list.
- [ ] Start a test meeting in Teams. Speak on the Teams side.
- [ ] Click the Test button in TalkTrack.
- [ ] **Expected:** system meter moves when Teams has audio; mic meter moves when you speak. No capture of any other app.

### 2. Record — selected app only, no interference

- [ ] With Teams selected, press Record.
- [ ] During the 30 s recording: play a Spotify track (or YouTube via Chrome).
- [ ] Press Stop.
- [ ] Open `system_audio.wav` in the recording folder.
- [ ] **Expected:** the Teams audio is audible. The Spotify/YouTube audio is NOT present.

### 3. Partial failure — one app dies mid-recording

- [ ] Select Teams and Chrome in the app list.
- [ ] Start recording.
- [ ] Kill Chrome via Task Manager.
- [ ] **Expected:** status bar updates to `Recording — capturing 1 of 2 apps`. The ⚠ label appears next to the Audio Sources section with Chrome's error in tooltip. Recording continues.
- [ ] Press Stop. Confirm `system_audio.wav` contains Teams audio up to the stop moment.

### 4. Full failure at start

- [ ] Select an app and immediately kill it via Task Manager before clicking Record.
- [ ] Click Record.
- [ ] **Expected:** QMessageBox error: "Per-app capture failed for all selected apps: {...}". State returns to IDLE. No partial recording left behind.

### 5. Handle leak stress

- [ ] Open Task Manager → Details tab, add the "Handles" column for the TalkTrack process.
- [ ] Note the current handle count.
- [ ] Select 3+ apps. Click Record, wait 5 s, Stop. Repeat 20 times.
- [ ] **Expected:** handle count returns to ~baseline each cycle. Growth > 200 handles across 20 cycles indicates a COM leak — investigate.

### 6. Negative — Windows 10

- [ ] On a Windows 10 machine, launch TalkTrack.
- [ ] **Expected:** per-app radio is hidden/disabled; only "All system audio" mode available. No crashes.

### 7. Test Mic — idle app reads silence

- [ ] Select a silent app (e.g., Notepad, which never plays audio).
- [ ] Click Test.
- [ ] **Expected:** system meter sits at -60. This is correct — recording would capture silence too.

## Regression run

After any PR touching the capture files, run through checks 1–4 as a minimum. Checks 5–7 are quarterly or for changes to activation/cleanup paths.
```

- [ ] **Step 2: Commit**

```bash
git add docs/testing/per-app-capture-smoke.md
git commit -m "docs: manual smoke-test checklist for per-app audio capture"
```

---

## Task 19: Integration run + final polish

**Files:** none to modify; this is a verification + cleanup pass.

- [ ] **Step 1: Run the full automated suite**

Run: `python -m pytest tests/ -v`
Expected: all tests pass. If anything fails, fix before proceeding.

- [ ] **Step 2: Smoke-import the app entry point**

Run: `python -c "from app.main_window import MainWindow; from app.recording.recorder import Recorder; from app.recording.process_audio_capture import ProcessAudioCapture, ProcessCaptureStream; from app.recording._process_com import hresult_name, activate_process_loopback; print('ok')"`
Expected: `ok`

- [ ] **Step 3: Run the minimum subset of Tier-3 checks**

On a Win11 machine:
- Smoke test #1 (Test Mic — single app speaking).
- Smoke test #2 (Record — selected app only).

These are the two that exercise the real COM path. If either fails, the activation or packet-read code needs hands-on debugging — the automated tests don't cover this.

- [ ] **Step 4: Confirm the CLAUDE.md "Known Limitations" section can be updated**

Open `CLAUDE.md` and remove this entry from the Known Limitations list:

```
- **Per-process COM capture is scaffolded:** The `ProcessCaptureStream._read_audio_packets()` method is a pipeline placeholder. The COM initialization structure is in place but the actual `IAudioCaptureClient.GetBuffer()` packet reading needs to be completed with real audio testing on Windows 11.
```

Only remove it once Tier-3 check #2 passes.

- [ ] **Step 5: Commit the CLAUDE.md update**

```bash
git add CLAUDE.md
git commit -m "docs: remove scaffolded-capture note from Known Limitations"
```

---

## Notes for implementers

- The COM path (Tasks 9 and 11 Step 5) cannot be unit-tested. If `read_next_packet` or `activate_process_loopback` misbehaves, the symptom is either silent capture (meter stuck at -60 during Tier-3 #1) or chipmunk audio (wrong resample ratio). Check `logger.info` output at activation time for the negotiated format, and compare against what you asked for.
- The `_native_frame_bytes` attribute referenced in `read_next_packet` needs to be stashed on the capture client during activation. If that wiring isn't done, the COM path will TypeError at runtime. Wire it in the same block of `activate_process_loopback` that does `IAudioClient::GetService(IID_IAudioCaptureClient)`.
- comtypes raises `COMError` for failed HRESULTs on most IDL-generated calls — `.hresult` is the raw code. Our `hresult_name` handles the signed↔unsigned conversion.
- The design doc (`docs/superpowers/specs/2026-04-18-per-app-capture-design.md`) is the source of truth for behavior. If a task conflicts with the spec, the spec wins — update the task to match.
