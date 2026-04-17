# Mic Gain and DAW-Style Meters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a live-adjustable mic gain multiplier and replace the thin inline level bars with prominent DAW-style vertical meters (dB scale, color zones, peak hold, clip indicators), plus a gain slider.

**Architecture:** Gain lives on `AudioStream` / `DualAudioCapture` as a float multiplier, applied in the audio callback before mute. A new `MetersPanel` widget owns the vertical meters + clip/peak state + gain slider; it replaces the inline meters previously in `RecordingControls`. `MainWindow` debounces config writes on slider drag.

**Tech Stack:** Python 3, PyQt6 (`QPainter`, `QSlider`, `QTimer`), numpy, sounddevice, unittest + pytest.

**Spec:** `docs/superpowers/specs/2026-04-17-mic-gain-and-daw-meters-design.md`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `app/utils/config.py` | modify | Add `audio.mic_gain: 1.0` default |
| `app/recording/audio_capture.py` | modify | `AudioStream._gain` + `set_gain()`, multiply + clip in callback before mute. `DualAudioCapture.set_gain()` propagates to both mic streams. |
| `app/ui/meters_panel.py` | **create** | DAW-style vertical meters + clip/peak state + gain slider. Pure helpers at module scope for unit testing. |
| `app/ui/recording_controls.py` | modify | Remove inline `LevelBar` meters, the Mic/Sys labels, and the related methods. |
| `app/main_window.py` | modify | Instantiate `MetersPanel`, reconnect level signals, wire gain handler with 500ms debounce, reset on IDLE, flush on close. |
| `tests/test_dual_audio_capture.py` | modify | Add `TestAudioStreamGain` + `TestDualAudioCaptureGain`. |
| `tests/test_meters_panel.py` | **create** | Tests for pure helpers: RMS dB, clip detection, peak-hold decay, slider ↔ multiplier mapping. |

---

## Task 1: Config default for `mic_gain`

**Files:**
- Modify: `app/utils/config.py`

- [ ] **Step 1: Add the default key**

In `app/utils/config.py`, in `DEFAULT_CONFIG["audio"]`, add a new key immediately after `"mic_mute_on_start": False,`:

```python
"audio": {
    "sample_rate": 16000,
    "channels": 1,
    "mic_device": None,
    "loopback_device": None,
    "last_mic": "",
    "last_mic2": "",
    "capture_mode": "legacy",
    "selected_apps": [],
    "hidden_devices": [],
    "mic_count": 1,
    "mic_mute_on_start": False,
    "mic_gain": 1.0,
},
```

- [ ] **Step 2: Verify via quick import check**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.utils.config import Config; c = Config(); print(c.get('audio', 'mic_gain'))"
```

Expected output: `1.0`

- [ ] **Step 3: Commit**

```bash
git add app/utils/config.py
git commit -m "config: add audio.mic_gain default"
```

---

## Task 2: AudioStream gain — failing tests

**Files:**
- Test: `tests/test_dual_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append this test class to `tests/test_dual_audio_capture.py` (below `TestDualAudioCaptureMute`, above the `if __name__ == "__main__":` block if present):

```python
class TestAudioStreamGain(unittest.TestCase):
    """AudioStream.set_gain multiplies samples and clips to [-1, 1]."""

    def _make_stream(self, gain=None):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        stream._recording = True
        stream._paused = False
        if gain is not None:
            stream.set_gain(gain)
        return stream

    def test_default_gain_is_1(self):
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(device_index=None, sample_rate=16000, channels=1)
        self.assertEqual(stream._gain, 1.0)

    def test_gain_1_does_not_change_samples(self):
        stream = self._make_stream(gain=1.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.3
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._all_chunks[0].max()), 0.3, places=5)

    def test_gain_multiplies_samples(self):
        stream = self._make_stream(gain=2.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.3
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._all_chunks[0].max()), 0.6, places=5)

    def test_gain_clips_at_positive_one(self):
        stream = self._make_stream(gain=3.0)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 64, None, None)
        # 0.5 * 3.0 = 1.5, must clip to 1.0
        self.assertEqual(float(stream._all_chunks[0].max()), 1.0)

    def test_gain_clips_at_negative_one(self):
        stream = self._make_stream(gain=3.0)
        chunk = np.ones((64, 1), dtype=np.float32) * -0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._all_chunks[0].min()), -1.0)

    def test_gain_below_one_attenuates(self):
        stream = self._make_stream(gain=0.5)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.8
        stream._audio_callback(chunk, 64, None, None)
        self.assertAlmostEqual(float(stream._all_chunks[0].max()), 0.4, places=5)

    def test_mute_beats_gain(self):
        stream = self._make_stream(gain=5.0)
        stream.set_muted(True)
        chunk = np.ones((64, 1), dtype=np.float32) * 0.5
        stream._audio_callback(chunk, 64, None, None)
        self.assertEqual(float(stream._all_chunks[0].max()), 0.0)

    def test_set_gain_coerces_to_float(self):
        stream = self._make_stream()
        stream.set_gain(2)
        self.assertEqual(stream._gain, 2.0)
        self.assertIsInstance(stream._gain, float)

    def test_level_callback_receives_gained_chunk(self):
        received = []
        from app.recording.audio_capture import AudioStream
        stream = AudioStream(
            device_index=None, sample_rate=16000, channels=1,
            level_callback=lambda c: received.append(c),
        )
        stream._recording = True
        stream._paused = False
        stream.set_gain(2.0)
        stream._audio_callback(
            np.ones((32, 1), dtype=np.float32) * 0.3, 32, None, None
        )
        self.assertEqual(len(received), 1)
        self.assertAlmostEqual(float(received[0].max()), 0.6, places=5)
```

- [ ] **Step 2: Run tests to confirm they fail**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py::TestAudioStreamGain -v
```

Expected: All 9 tests FAIL — `AttributeError: 'AudioStream' object has no attribute 'set_gain'` / `'_gain'`.

---

## Task 3: AudioStream gain — implementation

**Files:**
- Modify: `app/recording/audio_capture.py`

- [ ] **Step 1: Add `_gain` to `AudioStream.__init__`**

In `AudioStream.__init__`, right after the existing line `self._muted = False`, add:

```python
        self._gain = 1.0
```

The init block becomes:

```python
    def __init__(self, device_index, sample_rate=16000, channels=1,
                 level_callback=None):
        self.device_index = device_index
        self.sample_rate = sample_rate
        self.channels = channels
        self._level_callback = level_callback
        self._stream = None
        self._buffer = queue.Queue()
        self._recording = False
        self._paused = False
        self._all_chunks = []
        self._muted = False
        self._gain = 1.0
```

- [ ] **Step 2: Update `_audio_callback` to apply gain before mute**

Replace the existing `_audio_callback` with:

```python
    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("Audio stream status: %s", status)
        if self._recording and not self._paused:
            chunk = indata.copy()
            if self._gain != 1.0:
                chunk *= self._gain
                np.clip(chunk, -1.0, 1.0, out=chunk)
            if self._muted:
                chunk.fill(0.0)
            self._buffer.put(chunk)
            self._all_chunks.append(chunk)
            if self._level_callback is not None:
                self._level_callback(chunk)
```

- [ ] **Step 3: Add `set_gain` method**

Right after the `set_muted` method (which is just after `resume`), add:

```python
    def set_gain(self, gain):
        """Set the mic gain multiplier. Values outside [-1, 1] after multiplication are hard-clipped."""
        self._gain = float(gain)
```

- [ ] **Step 4: Run the tests**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py::TestAudioStreamGain -v
```

Expected: All 9 tests PASS.

- [ ] **Step 5: Confirm no regressions**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py -v
```

Expected: All tests in the file pass (existing 12 + 9 new = 21).

- [ ] **Step 6: Commit**

```bash
git add app/recording/audio_capture.py tests/test_dual_audio_capture.py
git commit -m "audio: AudioStream.set_gain multiplies and hard-clips samples"
```

---

## Task 4: DualAudioCapture gain — failing tests

**Files:**
- Test: `tests/test_dual_audio_capture.py`

- [ ] **Step 1: Write the failing tests**

Append this test class below `TestAudioStreamGain`:

```python
class TestDualAudioCaptureGain(unittest.TestCase):
    """DualAudioCapture.set_gain propagates to both mic streams."""

    def _fake_stream(self):
        from app.recording.audio_capture import AudioStream
        return AudioStream(device_index=None, sample_rate=16000, channels=1)

    def test_default_gain_is_1(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        self.assertEqual(cap.mic_gain, 1.0)

    def test_set_gain_single_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.set_gain(2.5)
        self.assertEqual(cap.mic_gain, 2.5)
        self.assertEqual(cap.mic_stream._gain, 2.5)

    def test_set_gain_propagates_to_second_mic(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.mic_stream = self._fake_stream()
        cap.mic_stream_2 = self._fake_stream()
        cap.set_gain(3.0)
        self.assertEqual(cap.mic_stream._gain, 3.0)
        self.assertEqual(cap.mic_stream_2._gain, 3.0)

    def test_set_gain_with_no_streams_does_not_raise(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.set_gain(2.0)
        self.assertEqual(cap.mic_gain, 2.0)

    def test_set_gain_coerces_to_float(self):
        from app.recording.audio_capture import DualAudioCapture
        cap = DualAudioCapture(mic_device=None, loopback_device=None)
        cap.set_gain(2)
        self.assertEqual(cap.mic_gain, 2.0)
        self.assertIsInstance(cap.mic_gain, float)
```

- [ ] **Step 2: Run tests to confirm failure**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py::TestDualAudioCaptureGain -v
```

Expected: All 5 tests FAIL — `AttributeError: 'DualAudioCapture' object has no attribute 'set_gain'` / `'mic_gain'`.

---

## Task 5: DualAudioCapture gain — implementation

**Files:**
- Modify: `app/recording/audio_capture.py`

- [ ] **Step 1: Add `mic_gain` attribute to `DualAudioCapture.__init__`**

In `DualAudioCapture.__init__`, right after the existing `self._muted = False` line, add:

```python
        self.mic_gain = 1.0
```

- [ ] **Step 2: Add `set_gain` method**

Add this method inside `DualAudioCapture`, just below `set_muted` (which is after `set_level_callbacks`):

```python
    def set_gain(self, gain):
        """Set the mic gain multiplier for all microphone streams in this capture session."""
        self.mic_gain = float(gain)
        if self.mic_stream is not None:
            self.mic_stream.set_gain(self.mic_gain)
        if self.mic_stream_2 is not None:
            self.mic_stream_2.set_gain(self.mic_gain)
```

- [ ] **Step 3: Apply gain to newly-created mic streams in `start()`**

Similar to how `_muted` is applied after `start()` is called on each mic stream: in `DualAudioCapture.start()`, after each `self.mic_stream.start()` / `self.mic_stream_2.start()` call (and in the same conditional block where `if self._muted: ...` already lives), add a gain application.

The mic1 block becomes:

```python
        if self.mic_device is not None:
            self.mic_stream = AudioStream(
                device_index=self.mic_device,
                sample_rate=self.sample_rate,
                channels=1,
                level_callback=self._mic_level_callback,
            )
            self.mic_stream.start()
            if self._muted:
                self.mic_stream.set_muted(True)
            if self.mic_gain != 1.0:
                self.mic_stream.set_gain(self.mic_gain)
            logger.info("Mic stream started on device %s", self.mic_device)
```

The mic2 block becomes:

```python
        if self.mic_device_2 is not None:
            self.mic_stream_2 = AudioStream(
                device_index=self.mic_device_2,
                sample_rate=self.sample_rate,
                channels=1,
                level_callback=self._mic_level_callback,
            )
            self.mic_stream_2.start()
            if self._muted:
                self.mic_stream_2.set_muted(True)
            if self.mic_gain != 1.0:
                self.mic_stream_2.set_gain(self.mic_gain)
            logger.info("Mic stream 2 started on device %s", self.mic_device_2)
```

- [ ] **Step 4: Run the tests**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py -v
```

Expected: All tests in the file pass (existing 21 + 5 new = 26).

- [ ] **Step 5: Commit**

```bash
git add app/recording/audio_capture.py tests/test_dual_audio_capture.py
git commit -m "audio: DualAudioCapture.set_gain propagates to both mic streams"
```

---

## Task 6: MetersPanel pure helpers — failing tests

**Files:**
- Create: `tests/test_meters_panel.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_meters_panel.py` with this content:

```python
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
    """Slider integer value ↔ float multiplier conversion."""

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
        # 1.54 → 15.4 → 15 (rounded)
        self.assertEqual(gain_to_slider(1.54), 15)

    def test_gain_to_slider_clamps_below(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(0.2), 5)

    def test_gain_to_slider_clamps_above(self):
        from app.ui.meters_panel import gain_to_slider
        self.assertEqual(gain_to_slider(10.0), 50)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to confirm failure**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_meters_panel.py -v
```

Expected: All tests FAIL at import (`ModuleNotFoundError: No module named 'app.ui.meters_panel'`).

---

## Task 7: MetersPanel widget + helpers — implementation

**Files:**
- Create: `app/ui/meters_panel.py`

- [ ] **Step 1: Create `app/ui/meters_panel.py` with helpers + widget**

Create `app/ui/meters_panel.py` with the following complete content:

```python
"""DAW-style vertical level meters with peak hold, clip indicators, and gain slider."""

import time
from typing import Tuple

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from app.ui.level_meter import DB_FLOOR, compute_rms_db


# dB reference points shown as tick marks on the scale
DB_TICKS = [0, -6, -18, -40, -60]

# Peak/clip timing
PEAK_HOLD_SECONDS = 1.5
PEAK_DECAY_SECONDS = 0.5
CLIP_HOLD_SECONDS = 2.0
CLIP_THRESHOLD = 0.99

# Gain slider range (integer). Divide by 10 to get multiplier.
SLIDER_MIN = 5    # 0.5x
SLIDER_MAX = 50   # 5.0x
SLIDER_DEFAULT = 10  # 1.0x


def chunk_max_abs(chunk: np.ndarray) -> float:
    """Return the peak absolute sample value in a chunk."""
    if chunk.size == 0:
        return 0.0
    return float(np.max(np.abs(chunk)))


def is_clipping(chunk: np.ndarray) -> bool:
    """Return True if any sample in the chunk is at or above the clip threshold."""
    if chunk.size == 0:
        return False
    return bool(np.max(np.abs(chunk)) >= CLIP_THRESHOLD)


def peak_hold_value(
    current: float,
    peak: float,
    peak_ts: float,
    now: float,
    hold_seconds: float = PEAK_HOLD_SECONDS,
    decay_seconds: float = PEAK_DECAY_SECONDS,
) -> Tuple[float, float]:
    """Compute the new peak value and peak timestamp.

    If current >= peak: peak jumps to current, timestamp refreshed.
    Else within hold window: peak and timestamp unchanged.
    Else decaying: linear fall from peak to current over decay_seconds.
    """
    if current >= peak:
        return current, now
    elapsed = now - peak_ts
    if elapsed < hold_seconds:
        return peak, peak_ts
    decay_elapsed = elapsed - hold_seconds
    if decay_elapsed >= decay_seconds:
        return current, peak_ts
    frac = decay_elapsed / decay_seconds
    return peak - (peak - current) * frac, peak_ts


def slider_to_gain(slider_value: int) -> float:
    """Map integer slider value to float gain multiplier."""
    return slider_value / 10.0


def gain_to_slider(gain: float) -> int:
    """Map float gain multiplier to integer slider value, clamping to valid range."""
    return max(SLIDER_MIN, min(SLIDER_MAX, int(round(gain * 10))))


def _db_to_y(db: float, height: int) -> int:
    """Map a dB value to a y-coordinate (0 = top = 0dB, height = bottom = DB_FLOOR)."""
    if db >= 0:
        return 0
    if db <= DB_FLOOR:
        return height
    return int(height * (db / DB_FLOOR))


class _VerticalMeter(QWidget):
    """A single vertical level bar with color zones, peak hold, and clip LED."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(28)
        self.setMinimumHeight(100)
        self._db = DB_FLOOR
        self._peak_abs = 0.0  # absolute linear peak (0..1+)
        self._peak_ts = 0.0
        self._clip_ts = 0.0

    def update_from_chunk(self, chunk: np.ndarray):
        now = time.monotonic()
        self._db = compute_rms_db(chunk)
        current = chunk_max_abs(chunk)
        self._peak_abs, self._peak_ts = peak_hold_value(
            current, self._peak_abs, self._peak_ts, now,
        )
        if is_clipping(chunk):
            self._clip_ts = now

    def reset(self):
        self._db = DB_FLOOR
        self._peak_abs = 0.0
        self._peak_ts = 0.0
        self._clip_ts = 0.0
        self.update()

    def is_clipping(self) -> bool:
        return (time.monotonic() - self._clip_ts) < CLIP_HOLD_SECONDS

    @property
    def current_db(self) -> float:
        return self._db

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        # Paint color zones top-to-bottom
        # -6 to 0 dB: red
        y_6 = _db_to_y(-6, h)
        painter.fillRect(0, 0, w, y_6, QColor("#f38ba8"))
        # -18 to -6 dB: yellow
        y_18 = _db_to_y(-18, h)
        painter.fillRect(0, y_6, w, y_18 - y_6, QColor("#f9e2af"))
        # -60 to -18 dB: green
        painter.fillRect(0, y_18, w, h - y_18, QColor("#a6e3a1"))

        # Overlay black to hide everything below current dB
        current_y = _db_to_y(self._db, h)
        if current_y < h:
            painter.fillRect(0, current_y, w, h - current_y, QColor("#1e1e2e"))

        # Peak hold line (white, 2px)
        peak_db = 20.0 * float(np.log10(max(self._peak_abs, 1e-10)))
        peak_db = max(peak_db, DB_FLOOR)
        peak_y = _db_to_y(peak_db, h)
        if peak_y < h and self._peak_abs > 0.001:
            painter.setPen(QPen(QColor("#cdd6f4"), 2))
            painter.drawLine(0, peak_y, w, peak_y)

        # 0 dB clip line
        painter.setPen(QPen(QColor("#f38ba8"), 1))
        painter.drawLine(0, 0, w, 0)

        painter.end()


class _DbScale(QWidget):
    """Small vertical widget drawing dB tick labels next to meters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(26)
        self.setMinimumHeight(100)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), QColor("#1e1e2e"))

        font = QFont()
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(QColor("#a6adc8"))

        h = self.height()
        for db in DB_TICKS:
            y = _db_to_y(db, h)
            label = str(db)
            painter.drawText(0, y - 1, self.width() - 2, 10,
                             Qt.AlignmentFlag.AlignRight, label)
        painter.end()


class MetersPanel(QWidget):
    """DAW-style dual-channel meters with peak hold, clip indicators, and gain slider."""

    gain_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        self._repaint_timer = QTimer(self)
        self._repaint_timer.timeout.connect(self._on_repaint_tick)
        self._repaint_timer.start(66)  # ~15fps

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # Meter row: scale + mic meter + clip led + sys meter + clip led
        meter_row = QHBoxLayout()
        meter_row.setSpacing(6)

        self._scale = _DbScale()
        meter_row.addWidget(self._scale)

        # Mic column
        mic_col = QVBoxLayout()
        mic_col.setSpacing(2)
        mic_header = QHBoxLayout()
        mic_header.setSpacing(4)
        self._mic_clip_led = QLabel("\u25cf")  # ●
        self._mic_clip_led.setStyleSheet("color: #45475a; font-size: 12px;")
        self._mic_clip_led.setToolTip("Clip indicator — lights red on clipping")
        mic_header.addWidget(self._mic_clip_led)
        mic_header.addStretch()
        mic_col.addLayout(mic_header)

        self._mic_meter = _VerticalMeter()
        mic_col.addWidget(self._mic_meter, 0, Qt.AlignmentFlag.AlignHCenter)

        self._mic_db_label = QLabel("-- dB")
        self._mic_db_label.setStyleSheet("color: #cdd6f4; font-size: 10px;")
        self._mic_db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mic_col.addWidget(self._mic_db_label)

        mic_title = QLabel("MIC")
        mic_title.setStyleSheet("color: #a6adc8; font-size: 10px; font-weight: bold;")
        mic_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mic_col.addWidget(mic_title)

        meter_row.addLayout(mic_col)
        meter_row.addSpacing(8)

        # Sys column
        sys_col = QVBoxLayout()
        sys_col.setSpacing(2)
        sys_header = QHBoxLayout()
        sys_header.setSpacing(4)
        self._sys_clip_led = QLabel("\u25cf")
        self._sys_clip_led.setStyleSheet("color: #45475a; font-size: 12px;")
        self._sys_clip_led.setToolTip("Clip indicator — lights red on clipping")
        sys_header.addWidget(self._sys_clip_led)
        sys_header.addStretch()
        sys_col.addLayout(sys_header)

        self._sys_meter = _VerticalMeter()
        sys_col.addWidget(self._sys_meter, 0, Qt.AlignmentFlag.AlignHCenter)

        self._sys_db_label = QLabel("-- dB")
        self._sys_db_label.setStyleSheet("color: #cdd6f4; font-size: 10px;")
        self._sys_db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sys_col.addWidget(self._sys_db_label)

        sys_title = QLabel("SYS")
        sys_title.setStyleSheet("color: #a6adc8; font-size: 10px; font-weight: bold;")
        sys_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sys_col.addWidget(sys_title)

        meter_row.addLayout(sys_col)
        meter_row.addStretch()

        root.addLayout(meter_row)

        # Gain slider row
        gain_row = QHBoxLayout()
        gain_row.setSpacing(6)
        gain_label = QLabel("Mic Gain:")
        gain_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        gain_row.addWidget(gain_label)

        self._gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._gain_slider.setRange(SLIDER_MIN, SLIDER_MAX)
        self._gain_slider.setValue(SLIDER_DEFAULT)
        self._gain_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._gain_slider.setTickInterval(5)
        self._gain_slider.setToolTip(
            "Boost microphone volume.\n1.0x = no change.\n"
            "Higher values are hard-clipped to prevent distortion."
        )
        self._gain_slider.valueChanged.connect(self._on_slider_changed)
        gain_row.addWidget(self._gain_slider, 1)

        self._gain_readout = QLabel("1.0x")
        self._gain_readout.setStyleSheet(
            "color: #cdd6f4; font-size: 11px; min-width: 34px;"
        )
        self._gain_readout.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gain_row.addWidget(self._gain_readout)

        root.addLayout(gain_row)

    # --- Audio update hooks (called from MainWindow) ---

    def update_mic_level(self, chunk: np.ndarray):
        self._mic_meter.update_from_chunk(chunk)

    def update_system_level(self, chunk: np.ndarray):
        self._sys_meter.update_from_chunk(chunk)

    def reset(self):
        self._mic_meter.reset()
        self._sys_meter.reset()
        self._mic_db_label.setText("-- dB")
        self._sys_db_label.setText("-- dB")
        self._set_clip_led(self._mic_clip_led, False)
        self._set_clip_led(self._sys_clip_led, False)

    # --- Gain ---

    def set_gain(self, gain: float):
        """Set slider value from a float gain. Does NOT emit gain_changed."""
        slider_val = gain_to_slider(float(gain))
        self._gain_slider.blockSignals(True)
        self._gain_slider.setValue(slider_val)
        self._gain_slider.blockSignals(False)
        self._gain_readout.setText(f"{slider_to_gain(slider_val):.1f}x")

    def _on_slider_changed(self, value: int):
        gain = slider_to_gain(value)
        self._gain_readout.setText(f"{gain:.1f}x")
        self.gain_changed.emit(gain)

    # --- Repaint tick ---

    def _on_repaint_tick(self):
        self._mic_meter.update()
        self._sys_meter.update()
        self._mic_db_label.setText(f"{self._mic_meter.current_db:.0f} dB")
        self._sys_db_label.setText(f"{self._sys_meter.current_db:.0f} dB")
        self._set_clip_led(self._mic_clip_led, self._mic_meter.is_clipping())
        self._set_clip_led(self._sys_clip_led, self._sys_meter.is_clipping())

    def _set_clip_led(self, label: QLabel, active: bool):
        if active:
            label.setStyleSheet("color: #f38ba8; font-size: 12px;")
        else:
            label.setStyleSheet("color: #45475a; font-size: 12px;")
```

- [ ] **Step 2: Run the helper tests**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_meters_panel.py -v
```

Expected: All tests PASS.

- [ ] **Step 3: Smoke-test widget import and instantiation**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "
import warnings; warnings.filterwarnings('ignore')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from app.ui.meters_panel import MetersPanel
p = MetersPanel()
print('ok')
print('has gain_changed signal:', hasattr(p, 'gain_changed'))
print('has set_gain:', hasattr(p, 'set_gain'))
print('has update_mic_level:', hasattr(p, 'update_mic_level'))
print('has update_system_level:', hasattr(p, 'update_system_level'))
print('has reset:', hasattr(p, 'reset'))
"
```

Expected: All `True` plus `ok`.

- [ ] **Step 4: Commit**

```bash
git add app/ui/meters_panel.py tests/test_meters_panel.py
git commit -m "ui: add MetersPanel with DAW-style meters and gain slider"
```

---

## Task 8: Remove inline meters from `RecordingControls`

**Files:**
- Modify: `app/ui/recording_controls.py`

- [ ] **Step 1: Remove the `LevelBar` import**

Change the top-of-file import (currently):

```python
from app.ui.level_meter import LevelBar, compute_rms_db, db_to_fraction
```

to:

*(delete the line entirely — `RecordingControls` no longer uses any symbols from `level_meter`)*

- [ ] **Step 2: Simplify row 2 in `_setup_ui`**

Find the block in `_setup_ui` that creates row 2 with indicator, timer, Mic label, mic bar, Sys label, sys bar. Replace the entire `status_row` construction block:

```python
        # Row 2: Indicator + timer + level meters
        status_row = QHBoxLayout()
        status_row.setSpacing(6)

        self.recording_indicator = QLabel("")
        self.recording_indicator.setObjectName("recordingIndicator")
        self.recording_indicator.setFixedWidth(14)
        self.recording_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(self.recording_indicator)

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timerLabel")
        status_row.addWidget(self.timer_label)

        # Level meters inline
        mic_label = QLabel("Mic")
        mic_label.setStyleSheet("color: #a6adc8; font-size: 10px;")
        status_row.addWidget(mic_label)
        self._mic_bar = LevelBar()
        status_row.addWidget(self._mic_bar, 1)

        sys_label = QLabel("Sys")
        sys_label.setStyleSheet("color: #a6adc8; font-size: 10px;")
        status_row.addWidget(sys_label)
        self._sys_bar = LevelBar()
        status_row.addWidget(self._sys_bar, 1)

        layout.addLayout(status_row)
```

with this simpler version:

```python
        # Row 2: Indicator + timer
        status_row = QHBoxLayout()
        status_row.setSpacing(6)

        self.recording_indicator = QLabel("")
        self.recording_indicator.setObjectName("recordingIndicator")
        self.recording_indicator.setFixedWidth(14)
        self.recording_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(self.recording_indicator)

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timerLabel")
        status_row.addWidget(self.timer_label)

        status_row.addStretch()

        layout.addLayout(status_row)
```

- [ ] **Step 3: Remove the meter update / reset methods**

Delete these three methods from `RecordingControls` (they're no longer needed; `MetersPanel` owns this responsibility):

```python
    def update_mic_level(self, audio_chunk):
        db = compute_rms_db(audio_chunk)
        self._mic_bar.set_level(db_to_fraction(db))

    def update_system_level(self, audio_chunk):
        db = compute_rms_db(audio_chunk)
        self._sys_bar.set_level(db_to_fraction(db))

    def reset_levels(self):
        self._mic_bar.reset()
        self._sys_bar.reset()
```

- [ ] **Step 4: Update class docstring**

Replace:

```python
class RecordingControls(QWidget):
    """Recording control buttons, timer, and level meters — compact two-row layout.

    Row 1: [● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]
    Row 2: ● 00:12:34  Mic ▓▓▓▓  Sys ▓▓▓▓
    """
```

with:

```python
class RecordingControls(QWidget):
    """Recording control buttons and timer — compact two-row layout.

    Row 1: [● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]
    Row 2: ● 00:12:34
    """
```

- [ ] **Step 5: Smoke-test import**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.ui.recording_controls import RecordingControls; print('ok')"
```

Expected output: `ok`

- [ ] **Step 6: Commit**

```bash
git add app/ui/recording_controls.py
git commit -m "ui: remove inline level meters from RecordingControls"
```

---

## Task 9: MainWindow wiring for MetersPanel and gain

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1: Add `MetersPanel` import**

Near the existing `from app.ui.recording_controls import RecordingControls` line, add:

```python
from app.ui.meters_panel import MetersPanel
```

- [ ] **Step 2: Add gain-debounce timer + pending state to `__init__`**

In `MainWindow.__init__`, right after the existing `self._mic_muted = False` line, add:

```python
        self._pending_gain = None  # holds latest slider value awaiting debounced save
        self._gain_save_timer = QTimer(self)
        self._gain_save_timer.setSingleShot(True)
        self._gain_save_timer.timeout.connect(self._flush_gain_to_config)
```

`QTimer` is already imported at the top of the file.

- [ ] **Step 3: Instantiate `MetersPanel` in `_setup_ui`**

Find the line in `_setup_ui` that adds `RecordingControls` to the left panel:

```python
        self.recording_controls = RecordingControls()
        left_layout.addWidget(self.recording_controls)
```

Immediately after that block, add:

```python
        self.meters_panel = MetersPanel()
        self.meters_panel.set_gain(self.config.get("audio", "mic_gain"))
        self.meters_panel.gain_changed.connect(self._on_gain_changed)
        left_layout.addWidget(self.meters_panel)
```

Confirm that this places `MetersPanel` above the waveform display in the layout (if the waveform `left_layout.addWidget(self.waveform)` comes after this, you're good — that's the intended order).

- [ ] **Step 4: Update level signal connections in `_connect_signals`**

Find this block in `_connect_signals`:

```python
        self.recorder.mic_level.connect(self.recording_controls.update_mic_level)
        self.recorder.mic_level.connect(self.waveform.append_audio)
        self.recorder.system_level.connect(self.recording_controls.update_system_level)
        self.recorder.system_level.connect(self.waveform.append_system_audio)
```

Replace `self.recording_controls.update_mic_level` and `self.recording_controls.update_system_level` with the `meters_panel` equivalents:

```python
        self.recorder.mic_level.connect(self.meters_panel.update_mic_level)
        self.recorder.mic_level.connect(self.waveform.append_audio)
        self.recorder.system_level.connect(self.meters_panel.update_system_level)
        self.recorder.system_level.connect(self.waveform.append_system_audio)
```

- [ ] **Step 5: Add `_on_gain_changed` handler**

Add this method near `_toggle_mute`:

```python
    def _on_gain_changed(self, gain):
        """Slider moved — apply live gain to capture, debounce config write."""
        self._pending_gain = float(gain)
        if self.recorder._capture is not None:
            self.recorder._capture.set_gain(gain)
        self._gain_save_timer.start(500)

    def _flush_gain_to_config(self):
        """Write pending gain value to config."""
        if self._pending_gain is None:
            return
        if self._pending_gain != self.config.get("audio", "mic_gain"):
            self.config.set("audio", "mic_gain", self._pending_gain)
            self.config.save()
        self._pending_gain = None
```

- [ ] **Step 6: Apply gain on recording start**

In `_start_recording`, find the existing mute block (added by the earlier feature):

```python
        # Apply "start muted" setting
        start_muted = self.config.get("audio", "mic_mute_on_start")
        self._mic_muted = bool(start_muted)
        if self.recorder._capture is not None:
            self.recorder._capture.set_muted(self._mic_muted)
        self.recording_controls.set_muted(self._mic_muted)
        self.waveform.set_mic_muted(self._mic_muted)
```

Immediately after that block, add:

```python
        # Apply saved mic gain
        mic_gain = self.config.get("audio", "mic_gain")
        if self.recorder._capture is not None:
            self.recorder._capture.set_gain(mic_gain)
```

- [ ] **Step 7: Reset meters on IDLE**

In `_on_state_changed`, the `elif state == RecordingState.IDLE:` branch currently contains (among other things):

```python
            self.recording_controls.reset_timer()
            self.recording_controls.reset_levels()
            self._mic_muted = False
            self.waveform.set_mic_muted(False)
```

Replace `self.recording_controls.reset_levels()` with `self.meters_panel.reset()` (since the `reset_levels` method was removed from `RecordingControls`):

```python
            self.recording_controls.reset_timer()
            self.meters_panel.reset()
            self._mic_muted = False
            self.waveform.set_mic_muted(False)
```

- [ ] **Step 8: Flush pending gain write on close**

If `MainWindow` already has a `closeEvent`, add the flush at the top. If it doesn't, add a new one. First, check whether it exists with grep — find `def closeEvent` in `app/main_window.py`.

If `closeEvent` exists, add at the top of its body:

```python
        if self._gain_save_timer.isActive():
            self._gain_save_timer.stop()
            self._flush_gain_to_config()
```

If `closeEvent` does NOT exist, add it near the other handler methods (e.g., below `_on_state_changed`):

```python
    def closeEvent(self, event):
        if self._gain_save_timer.isActive():
            self._gain_save_timer.stop()
            self._flush_gain_to_config()
        super().closeEvent(event)
```

- [ ] **Step 9: Smoke-test import and instantiation**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "
import warnings; warnings.filterwarnings('ignore')
from PyQt6.QtWidgets import QApplication
app = QApplication([])
from app.main_window import MainWindow
w = MainWindow()
print('ok')
print('meters_panel present:', hasattr(w, 'meters_panel'))
print('gain_save_timer present:', hasattr(w, '_gain_save_timer'))
print('_on_gain_changed present:', hasattr(w, '_on_gain_changed'))
print('_flush_gain_to_config present:', hasattr(w, '_flush_gain_to_config'))
"
```

Expected: `ok` and all four `True`.

- [ ] **Step 10: Commit**

```bash
git add app/main_window.py
git commit -m "main: wire MetersPanel and mic gain with debounced config save"
```

---

## Task 10: Full tests + manual verification

**Files:**
- No code changes.

- [ ] **Step 1: Run full test suite**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/ -v
```

Expected: All tests PASS (existing 119 + 9 `TestAudioStreamGain` + 5 `TestDualAudioCaptureGain` + `tests/test_meters_panel.py` tests).

- [ ] **Step 2: Launch the app**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python main.py
```

Verify in the UI:

1. **Meters panel layout:** Below the record/pause/stop/mute buttons, you should see two vertical meter bars labeled MIC and SYS, each with its own dB readout below and a small grey clip LED above. A horizontal gain slider labeled "Mic Gain:" with `1.0x` readout is below the meters.
2. **Recording controls simplified:** Row 2 should now be just the recording indicator + timer — no inline mic/sys bars.
3. **Start recording:** Mic meter should move when you speak. Sys meter should move when there is system audio (play a YouTube video). Both bars should jump, then peak-hold line should visibly hold briefly before decaying. dB readout next to each meter should update live.
4. **Clip indicator:** If mic audio clips (speak very loudly close to mic, or set gain to 5.0× and speak normally), the grey `●` next to MIC should light up red and stay red for ~2 seconds after the last clip.
5. **Gain slider — live:** During recording, drag the gain slider. The mic meter level should change immediately in response (louder bar at higher gain, quieter at lower). Readout shows current value (`0.5x` … `5.0x`).
6. **Gain clipping protection:** Set gain to `5.0x` and speak at normal volume. The mic meter should show red/yellow zone activity, the clip LED may flash, but playback (after stop) should not have audio wraparound/distortion — hard-clipped at full scale.
7. **Gain persists across sessions:** Drag gain to `2.0x`, wait a second, then close the app. Restart. Meter slider should come back at `2.0x`.
8. **Gain persists via close-before-debounce:** Drag to `3.0x` and immediately close the app within 500ms. Restart. Meter slider should be at `3.0x` (the close handler flushed the pending write).
9. **Stop resets:** Stop recording. Meters and peak holds should return to empty (`-- dB`, grey clip LEDs).
10. **Mute + gain still works:** Start recording at `3.0x` gain, click Mute. Mic meter should go flat (zeros override gain), MIC MUTED waveform overlay appears. Unmute — meter activity resumes.

- [ ] **Step 3: Final commit if any fixes were needed**

If manual verification required fixes, commit them:

```bash
git add -A
git commit -m "fix: address manual verification feedback"
```

Otherwise skip.

---

## Self-Review Checklist

- [ ] All 10 tasks above checked off.
- [ ] `python -m pytest tests/ -v` passes.
- [ ] `python main.py` launches without errors.
- [ ] All 10 manual verification steps pass.
- [ ] `git status` clean, `git log --oneline` shows a clean per-task commit sequence.
