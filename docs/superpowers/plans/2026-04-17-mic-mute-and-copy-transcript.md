# Mic Mute and Copy Transcript Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mic-mute toggle that silences mic capture mid-recording (with visual indicators and a "start muted" setting), and replace the JSON transcript export with a clipboard "Copy All" button.

**Architecture:** Mute is a flag on `AudioStream` / `DualAudioCapture` that zeros the chunk in the audio callback — preserves timeline alignment. UI state (mute button, waveform overlay) is kept in sync from `MainWindow` when the mute button is toggled. Copy All adds a clipboard write backed by a new `TranscriptResult.to_plain_text()` helper.

**Tech Stack:** Python 3, PyQt6, sounddevice, numpy, unittest + pytest.

**Spec:** `docs/superpowers/specs/2026-04-17-mic-mute-and-copy-transcript-design.md`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `app/utils/config.py` | modify | Add `audio.mic_mute_on_start` default |
| `app/recording/audio_capture.py` | modify | `AudioStream._muted` flag + `set_muted()`; `DualAudioCapture.set_muted()` propagates to both mic streams |
| `app/ui/recording_controls.py` | modify | Add Mute button, `mute_clicked` signal, `set_muted(bool)` visual state |
| `app/ui/waveform_display.py` | modify | `_mic_muted` flag, `set_mic_muted(bool)`, red overlay in `paintEvent` |
| `app/transcription/transcriber.py` | modify | New `TranscriptResult.to_plain_text(speaker_names)` |
| `app/ui/transcript_viewer.py` | modify | Add Copy All button + handler; remove Export JSON button + branch |
| `app/ui/settings_dialog.py` | modify | Add `mic_mute_on_start` checkbox in General tab |
| `app/main_window.py` | modify | Wire mute button → capture + waveform; apply setting on start; reset on stop |
| `tests/test_dual_audio_capture.py` | modify | Add mute propagation + zeroing tests |
| `tests/test_transcriber.py` | modify | Add `to_plain_text` tests |

---

## Task 1: Config default for `mic_mute_on_start`

**Files:**
- Modify: `app/utils/config.py`

- [ ] **Step 1: Add the default key**

Edit `app/utils/config.py`, in `DEFAULT_CONFIG["audio"]` (currently ends with `"mic_count": 1,`), add a new key right after `mic_count`:

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
},
```

- [ ] **Step 2: Verify via quick import check**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.utils.config import Config; c = Config(); print(c.get('audio', 'mic_mute_on_start'))"
```

Expected output: `False`

- [ ] **Step 3: Commit**

```bash
git add app/utils/config.py
git commit -m "config: add audio.mic_mute_on_start default"
```

---

## Task 2: AudioStream mute — failing test

**Files:**
- Test: `tests/test_dual_audio_capture.py`

- [ ] **Step 1: Write the failing test**

Add this test class to the bottom of `tests/test_dual_audio_capture.py` (just before the `if __name__ == "__main__":` block). If that block is present, place the new class above it.

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py::TestAudioStreamMute -v
```

Expected: All four tests FAIL because `AudioStream.set_muted` does not exist (`AttributeError: 'AudioStream' object has no attribute 'set_muted'`).

---

## Task 3: AudioStream mute — implementation

**Files:**
- Modify: `app/recording/audio_capture.py`

- [ ] **Step 1: Add `_muted` flag to `AudioStream.__init__`**

Edit `app/recording/audio_capture.py`. In `AudioStream.__init__` (after `self._all_chunks = []` around line 26), add:

```python
        self._muted = False
```

The full init block becomes:

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
```

- [ ] **Step 2: Zero the chunk when muted in `_audio_callback`**

Replace the existing `_audio_callback` (around lines 28-36) with:

```python
    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("Audio stream status: %s", status)
        if self._recording and not self._paused:
            chunk = indata.copy()
            if self._muted:
                chunk.fill(0.0)
            self._buffer.put(chunk)
            self._all_chunks.append(chunk)
            if self._level_callback is not None:
                self._level_callback(chunk)
```

- [ ] **Step 3: Add `set_muted` method**

Right after the `resume` method in `AudioStream` (around line 61), add:

```python
    def set_muted(self, muted):
        """Mute or unmute the mic. Muted streams keep recording but write silence."""
        self._muted = bool(muted)
```

- [ ] **Step 4: Run the tests**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py::TestAudioStreamMute -v
```

Expected: All four tests PASS.

- [ ] **Step 5: Commit**

```bash
git add app/recording/audio_capture.py tests/test_dual_audio_capture.py
git commit -m "audio: AudioStream.set_muted zeros chunks while preserving length"
```

---

## Task 4: DualAudioCapture mute — failing test

**Files:**
- Test: `tests/test_dual_audio_capture.py`

- [ ] **Step 1: Add the failing test**

Add this test class to `tests/test_dual_audio_capture.py` below `TestAudioStreamMute`:

```python
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
```

- [ ] **Step 2: Run test to verify failure**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py::TestDualAudioCaptureMute -v
```

Expected: All five tests FAIL (`AttributeError: 'DualAudioCapture' object has no attribute 'set_muted'` and `...no attribute 'is_muted'`).

---

## Task 5: DualAudioCapture mute — implementation

**Files:**
- Modify: `app/recording/audio_capture.py`

- [ ] **Step 1: Add `_muted` to `DualAudioCapture.__init__`**

In `DualAudioCapture.__init__`, after the line `self._silence_fired = False  # only fire once per silence stretch` (around line 251), add:

```python
        self._muted = False
```

- [ ] **Step 2: Add `set_muted` and `is_muted` methods**

Add these two methods anywhere inside `DualAudioCapture` — a good spot is just after `set_level_callbacks` (around line 256):

```python
    def set_muted(self, muted):
        """Mute or unmute all microphone streams in this capture session."""
        self._muted = bool(muted)
        if self.mic_stream is not None:
            self.mic_stream.set_muted(self._muted)
        if self.mic_stream_2 is not None:
            self.mic_stream_2.set_muted(self._muted)

    @property
    def is_muted(self):
        return self._muted
```

- [ ] **Step 3: Apply mute to newly-created mic streams in `start()`**

In `DualAudioCapture.start()`, after the `self.mic_stream.start()` call (currently on line 291), add:

```python
            if self._muted:
                self.mic_stream.set_muted(True)
```

And after the `self.mic_stream_2.start()` call (currently line 304), add:

```python
            if self._muted:
                self.mic_stream_2.set_muted(True)
```

Placement context — the first block becomes:

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
            logger.info("Mic stream started on device %s", self.mic_device)
```

The second block becomes:

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
            logger.info("Mic stream 2 started on device %s", self.mic_device_2)
```

- [ ] **Step 4: Run the tests**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_dual_audio_capture.py -v
```

Expected: All `TestDualAudioCaptureMute` and `TestAudioStreamMute` tests PASS, and the existing `TestDualAudioCaptureMode` tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add app/recording/audio_capture.py tests/test_dual_audio_capture.py
git commit -m "audio: DualAudioCapture.set_muted propagates to both mic streams"
```

---

## Task 6: RecordingControls — mute button

**Files:**
- Modify: `app/ui/recording_controls.py`

- [ ] **Step 1: Add the `mute_clicked` signal**

In `app/ui/recording_controls.py`, add a new signal line after the existing `stop_clicked` signal (around line 20):

```python
    record_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    mute_clicked = pyqtSignal()
```

- [ ] **Step 2: Add the Mute button in `_setup_ui`**

In `_setup_ui` (around line 49-52, just after `self.stop_btn` is added to `btn_row`), add:

```python
        self.mute_btn = QPushButton("\U0001f3a4 Mute")
        self.mute_btn.setObjectName("muteButton")
        self.mute_btn.setToolTip(
            "Mute the microphone while keeping system/app audio recording."
        )
        self.mute_btn.clicked.connect(self.mute_clicked.emit)
        btn_row.addWidget(self.mute_btn)
```

(`\U0001f3a4` is the microphone emoji 🎤.)

The button row then looks like: `[● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]`.

- [ ] **Step 3: Add `_muted` state + `set_muted` method**

In `__init__`, just above the `self._blink_state = True` line (around line 25), add:

```python
        self._muted = False
```

Then add this method near the bottom of the class (e.g., above `_toggle_indicator`):

```python
    def set_muted(self, muted):
        """Update the mute button visual state."""
        self._muted = bool(muted)
        if self._muted:
            self.mute_btn.setText("\U0001f3a4 Muted")
            self.mute_btn.setStyleSheet(
                "QPushButton#muteButton { "
                "background-color: #f38ba8; color: #1e1e2e; "
                "border: 1px solid #f38ba8; font-weight: bold; }"
            )
        else:
            self.mute_btn.setText("\U0001f3a4 Mute")
            self.mute_btn.setStyleSheet("")
```

- [ ] **Step 4: Enable/disable the button in `set_state`**

Update `set_state` so the mute button is enabled only during RECORDING or PAUSED. Replace the method with:

```python
    def set_state(self, state):
        if state == RecordingState.IDLE:
            self.record_btn.setEnabled(True)
            self.record_btn.setText("\u25cf Rec")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("\u23f8 Pause")
            self.stop_btn.setEnabled(False)
            self.mute_btn.setEnabled(False)
            self.set_muted(False)
            self.recording_indicator.setText("")
            self._blink_timer.stop()
        elif state == RecordingState.RECORDING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("\u23f8 Pause")
            self.stop_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self._blink_timer.start(500)
        elif state == RecordingState.PAUSED:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("\u25b6 Resume")
            self.stop_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.recording_indicator.setText("\u23f8")
            self._blink_timer.stop()
        elif state == RecordingState.STOPPING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.mute_btn.setEnabled(False)
            self.recording_indicator.setText("")
            self._blink_timer.stop()
```

Note: the `self.set_muted(False)` call on IDLE also resets visual state for the next recording.

- [ ] **Step 5: Smoke-test import**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.ui.recording_controls import RecordingControls; print('ok')"
```

Expected output: `ok`

- [ ] **Step 6: Commit**

```bash
git add app/ui/recording_controls.py
git commit -m "ui: add Mute button to recording controls"
```

---

## Task 7: WaveformDisplay — mic-muted overlay

**Files:**
- Modify: `app/ui/waveform_display.py`

- [ ] **Step 1: Add `_mic_muted` state + setter**

In `WaveformDisplay.__init__` (around line 79, after `self.setVisible(False)`), add:

```python
        self._mic_muted = False
```

Then add this method (good placement: after `append_system_audio`):

```python
    def set_mic_muted(self, muted):
        """Show a 'MIC MUTED' overlay on the mic (top) half of the waveform."""
        self._mic_muted = bool(muted)
        self.update()
```

- [ ] **Step 2: Reset `_mic_muted` in `stop()`**

In `stop()` (around line 92-96), add a reset line. Replace `stop` with:

```python
    def stop(self):
        self._paint_timer.stop()
        self.setVisible(False)
        self._mic_buffer.clear()
        self._sys_buffer.clear()
        self._mic_muted = False
```

- [ ] **Step 3: Paint the overlay in `paintEvent`**

In `paintEvent`, after drawing the mic waveform (around line 155, right after `self._draw_waveform(painter, mic_data, mic_color, label_w, 0, wave_w, half_h - gap,)`), add:

```python
        if self._mic_muted:
            overlay_x = label_w
            overlay_y = 0
            overlay_w = wave_w
            overlay_h = int(half_h - gap)
            painter.fillRect(
                overlay_x, overlay_y, overlay_w, overlay_h,
                QColor(243, 139, 168, 90),  # Catppuccin red, semi-transparent
            )
            overlay_font = QFont()
            overlay_font.setPixelSize(14)
            overlay_font.setBold(True)
            painter.setFont(overlay_font)
            painter.setPen(QColor("#f38ba8"))
            painter.drawText(
                overlay_x, overlay_y, overlay_w, overlay_h,
                Qt.AlignmentFlag.AlignCenter,
                "MIC MUTED",
            )
```

- [ ] **Step 4: Smoke-test import**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.ui.waveform_display import WaveformDisplay; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
git add app/ui/waveform_display.py
git commit -m "ui: show 'MIC MUTED' overlay on waveform when mic is muted"
```

---

## Task 8: TranscriptResult.to_plain_text — failing tests

**Files:**
- Test: `tests/test_transcriber.py`

- [ ] **Step 1: Add the failing test class**

Append this class to `tests/test_transcriber.py` (below the last test class, above `if __name__ == "__main__":` if present):

```python
class TestToPlainText(unittest.TestCase):
    """TranscriptResult.to_plain_text: clipboard-friendly, no timestamps."""

    def _make_result(self, segs):
        return TranscriptResult(segments=segs, language="en", duration=10.0)

    def test_empty_transcript_returns_empty_string(self):
        r = self._make_result([])
        self.assertEqual(r.to_plain_text(), "")

    def test_uses_raw_speaker_id_when_no_name_mapping(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi there.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "SPEAKER_00: Hi there.")

    def test_uses_friendly_name_when_provided(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi there.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": "Alice"})
        self.assertEqual(out, "Alice: Hi there.")

    def test_empty_friendly_name_falls_back_to_raw_id(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": ""})
        self.assertEqual(out, "SPEAKER_00: Hi.")

    def test_segment_without_speaker_has_no_prefix(self):
        segs = [TranscriptSegment(0.0, 1.0, "Unidentified line.")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "Unidentified line.")

    def test_blank_line_between_speaker_changes(self):
        segs = [
            TranscriptSegment(0.0, 1.0, "One.", speaker="SPEAKER_00"),
            TranscriptSegment(1.0, 2.0, "Two.", speaker="SPEAKER_00"),
            TranscriptSegment(2.0, 3.0, "Three.", speaker="SPEAKER_01"),
            TranscriptSegment(3.0, 4.0, "Four.", speaker="SPEAKER_00"),
        ]
        r = self._make_result(segs)
        names = {"SPEAKER_00": "Alice", "SPEAKER_01": "Bob"}
        out = r.to_plain_text(speaker_names=names)
        expected = (
            "Alice: One.\n"
            "Alice: Two.\n"
            "\n"
            "Bob: Three.\n"
            "\n"
            "Alice: Four."
        )
        self.assertEqual(out, expected)

    def test_no_timestamps_in_output(self):
        segs = [
            TranscriptSegment(0.0, 1.5, "Hello.", speaker="SPEAKER_00"),
            TranscriptSegment(1.5, 3.0, "World.", speaker="SPEAKER_00"),
        ]
        r = self._make_result(segs)
        out = r.to_plain_text(speaker_names={"SPEAKER_00": "Alice"})
        # No digits-colon-digits timestamps and no square brackets
        self.assertNotIn("[", out)
        self.assertNotIn("]", out)
        self.assertNotIn("->", out)

    def test_no_trailing_newline(self):
        segs = [TranscriptSegment(0.0, 1.0, "Hi.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        out = r.to_plain_text()
        self.assertFalse(out.endswith("\n"))

    def test_text_is_stripped_of_leading_whitespace(self):
        """Whisper often emits leading spaces on segment text."""
        segs = [TranscriptSegment(0.0, 1.0, " Hello.", speaker="SPEAKER_00")]
        r = self._make_result(segs)
        self.assertEqual(r.to_plain_text(), "SPEAKER_00: Hello.")
```

- [ ] **Step 2: Run tests to verify failure**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_transcriber.py::TestToPlainText -v
```

Expected: All 9 tests FAIL (`AttributeError: 'TranscriptResult' object has no attribute 'to_plain_text'`).

---

## Task 9: TranscriptResult.to_plain_text — implementation

**Files:**
- Modify: `app/transcription/transcriber.py`

- [ ] **Step 1: Add the `to_plain_text` method**

In `app/transcription/transcriber.py`, inside `TranscriptResult`, add this method right after the existing `to_text` method (around line 70):

```python
    def to_plain_text(self, speaker_names=None):
        """Clipboard-friendly plain text: '{speaker}: {text}' per line, blank line between speaker changes, no timestamps."""
        if not self.segments:
            return ""
        lines = []
        prev_speaker = None
        for seg in self.segments:
            display = self._display_speaker(seg, speaker_names)
            if prev_speaker is not None and seg.speaker != prev_speaker:
                lines.append("")
            text = seg.text.strip()
            if display:
                lines.append(f"{display}: {text}")
            else:
                lines.append(text)
            prev_speaker = seg.speaker
        return "\n".join(lines)
```

- [ ] **Step 2: Run the tests**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_transcriber.py::TestToPlainText -v
```

Expected: All 9 tests PASS.

- [ ] **Step 3: Run the full transcriber test file**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/test_transcriber.py -v
```

Expected: All existing tests still PASS.

- [ ] **Step 4: Commit**

```bash
git add app/transcription/transcriber.py tests/test_transcriber.py
git commit -m "transcriber: add TranscriptResult.to_plain_text for clipboard copy"
```

---

## Task 10: TranscriptViewer — add Copy All, remove Export JSON

**Files:**
- Modify: `app/ui/transcript_viewer.py`

- [ ] **Step 1: Add `QApplication` and `QToolTip` imports**

At the top of `app/ui/transcript_viewer.py`, change the existing PyQt6 widgets import (around line 5-8):

```python
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QProgressBar, QFileDialog, QScrollArea, QCheckBox,
    QApplication, QToolTip,
)
```

- [ ] **Step 2: Replace the export row buttons**

In `_setup_ui`, find the export row block (around lines 161-174) and replace this section:

```python
        self.export_txt_btn = QPushButton("Export TXT")
        self.export_txt_btn.setEnabled(False)
        self.export_txt_btn.clicked.connect(lambda: self._export("txt"))
        export_row.addWidget(self.export_txt_btn)

        self.export_srt_btn = QPushButton("Export SRT")
        self.export_srt_btn.setEnabled(False)
        self.export_srt_btn.clicked.connect(lambda: self._export("srt"))
        export_row.addWidget(self.export_srt_btn)

        self.export_json_btn = QPushButton("Export JSON")
        self.export_json_btn.setEnabled(False)
        self.export_json_btn.clicked.connect(lambda: self._export("json"))
        export_row.addWidget(self.export_json_btn)
```

with:

```python
        self.copy_all_btn = QPushButton("Copy All")
        self.copy_all_btn.setEnabled(False)
        self.copy_all_btn.setToolTip(
            "Copy the entire transcript to the clipboard as plain text\n"
            "(speakers + text, no timestamps)."
        )
        self.copy_all_btn.clicked.connect(self._on_copy_all_clicked)
        export_row.addWidget(self.copy_all_btn)

        self.export_txt_btn = QPushButton("Export TXT")
        self.export_txt_btn.setEnabled(False)
        self.export_txt_btn.clicked.connect(lambda: self._export("txt"))
        export_row.addWidget(self.export_txt_btn)

        self.export_srt_btn = QPushButton("Export SRT")
        self.export_srt_btn.setEnabled(False)
        self.export_srt_btn.clicked.connect(lambda: self._export("srt"))
        export_row.addWidget(self.export_srt_btn)
```

- [ ] **Step 3: Update `display_transcript` button-enable block**

In `display_transcript`, replace this block (around lines 267-270):

```python
        # Enable export and playback buttons
        self.export_txt_btn.setEnabled(True)
        self.export_srt_btn.setEnabled(True)
        self.export_json_btn.setEnabled(True)
        self.play_all_btn.setEnabled(self._audio_path is not None)
```

with:

```python
        # Enable export and playback buttons
        self.copy_all_btn.setEnabled(True)
        self.export_txt_btn.setEnabled(True)
        self.export_srt_btn.setEnabled(True)
        self.play_all_btn.setEnabled(self._audio_path is not None)
```

- [ ] **Step 4: Update `clear` button-disable block**

In `clear`, replace this block (around lines 299-302):

```python
        # Disable export, playback, and transcribe buttons
        self.export_txt_btn.setEnabled(False)
        self.export_srt_btn.setEnabled(False)
        self.export_json_btn.setEnabled(False)
        self.play_all_btn.setEnabled(False)
        self.transcribe_btn.setEnabled(False)
```

with:

```python
        # Disable export, playback, and transcribe buttons
        self.copy_all_btn.setEnabled(False)
        self.export_txt_btn.setEnabled(False)
        self.export_srt_btn.setEnabled(False)
        self.play_all_btn.setEnabled(False)
        self.transcribe_btn.setEnabled(False)
```

- [ ] **Step 5: Remove the `json` branch from `_export`**

In `_export` (around lines 487-516), remove the `"json"` key from the `filters` dict and the `elif format_type == "json":` branch. The method becomes:

```python
    def _export(self, format_type):
        if not self._transcript:
            return

        filters = {
            "txt": "Text Files (*.txt)",
            "srt": "SRT Subtitle Files (*.srt)",
        }

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Transcript", "", filters[format_type]
        )

        if not path:
            return

        names = self._speaker_names

        if format_type == "txt":
            content = self._transcript.to_text(speaker_names=names)
        elif format_type == "srt":
            content = self._transcript.to_srt(speaker_names=names)

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
```

Also remove the unused `import json` at the top of the file (currently line 2) — no other code in this file uses it.

- [ ] **Step 6: Add `_on_copy_all_clicked` handler**

Add this method at the bottom of the `TranscriptViewer` class (after `_export`):

```python
    def _on_copy_all_clicked(self):
        if not self._transcript or not self._transcript.segments:
            return
        text = self._transcript.to_plain_text(speaker_names=self._speaker_names)
        QApplication.clipboard().setText(text)
        count = len(self._transcript.segments)
        pos = self.copy_all_btn.mapToGlobal(self.copy_all_btn.rect().bottomLeft())
        QToolTip.showText(pos, f"Copied {count} segments to clipboard", self.copy_all_btn, self.copy_all_btn.rect(), 2000)
```

- [ ] **Step 7: Smoke-test import**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.ui.transcript_viewer import TranscriptViewer; print('ok')"
```

Expected output: `ok`

- [ ] **Step 8: Commit**

```bash
git add app/ui/transcript_viewer.py
git commit -m "ui: add Copy All to transcript viewer, remove Export JSON"
```

---

## Task 11: Settings dialog — mic_mute_on_start

**Files:**
- Modify: `app/ui/settings_dialog.py`

- [ ] **Step 1: Add the checkbox widget in the General tab**

In `app/ui/settings_dialog.py`, in the General tab setup. After the block that adds `self.silence_auto_stop_cb` / `self.silence_duration_spin` (look for the line `recording_form.addRow(self.silence_auto_stop_cb)` around line 56, and the spin row just after it). Immediately after the silence-duration row is added to `recording_form`, add:

```python
        self.mic_mute_on_start_cb = QCheckBox("Start recordings with microphone muted")
        self.mic_mute_on_start_cb.setToolTip(
            "When checked, new recordings begin with the mic muted.\n"
            "Toggle mute anytime during recording via the Mute button.\n"
            "Applies to both mics when dual-mic mode is configured."
        )
        recording_form.addRow(self.mic_mute_on_start_cb)
```

To find the exact insertion point, search for `silence_duration_spin` — insert after its `recording_form.addRow(...)` line.

- [ ] **Step 2: Load the setting**

In `_load_settings`, after the line `self.silence_auto_stop_cb.setChecked(self.config.get("general", "silence_auto_stop"))` (around line 336), add:

```python
        self.mic_mute_on_start_cb.setChecked(self.config.get("audio", "mic_mute_on_start"))
```

- [ ] **Step 3: Save the setting**

In `_save_and_close`, after the line `self.config.set("general", "silence_auto_stop", self.silence_auto_stop_cb.isChecked())` (around line 421), add:

```python
        self.config.set("audio", "mic_mute_on_start", self.mic_mute_on_start_cb.isChecked())
```

- [ ] **Step 4: Smoke-test import**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.ui.settings_dialog import SettingsDialog; print('ok')"
```

Expected output: `ok`

- [ ] **Step 5: Commit**

```bash
git add app/ui/settings_dialog.py
git commit -m "settings: add 'start recordings muted' toggle in General tab"
```

---

## Task 12: MainWindow — wire mute through the pipeline

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1: Add mute signal connection**

In `_connect_signals`, after the line `self.recording_controls.stop_clicked.connect(self._stop_recording)` (around line 196), add:

```python
        self.recording_controls.mute_clicked.connect(self._toggle_mute)
```

- [ ] **Step 2: Initialize `_mic_muted` state**

In `MainWindow.__init__`, find the existing line `self._diarization_worker = None` (around line 41). Immediately after it, add:

```python
        self._mic_muted = False
```

Context — the block becomes:

```python
    def __init__(self):
        super().__init__()
        self.config = Config()
        self.recorder = Recorder(self.config)
        self._current_session = None
        self._transcription_worker = None
        self._diarization_worker = None
        self._mic_muted = False
```

- [ ] **Step 3: Apply `mic_mute_on_start` when starting a recording**

In `_start_recording`, after the `self.recorder.start_recording(...)` call (around line 262-268), add:

```python
        # Apply "start muted" setting
        start_muted = self.config.get("audio", "mic_mute_on_start")
        self._mic_muted = bool(start_muted)
        if self.recorder._capture is not None:
            self.recorder._capture.set_muted(self._mic_muted)
        self.recording_controls.set_muted(self._mic_muted)
        self.waveform.set_mic_muted(self._mic_muted)
```

Note: accessing `self.recorder._capture` is a minor layering break but is consistent with existing patterns (silence detection and level callbacks are configured before start; here we need to reach in post-start). An alternative — adding a `Recorder.set_muted` proxy — is cleaner but out of scope for this plan unless the reviewer requests it.

- [ ] **Step 4: Add the `_toggle_mute` handler**

Add this method to `MainWindow` (near `_toggle_pause`, around line 273):

```python
    def _toggle_mute(self):
        """Toggle mic mute state mid-recording."""
        if self.recorder.state not in (RecordingState.RECORDING, RecordingState.PAUSED):
            return
        self._mic_muted = not self._mic_muted
        if self.recorder._capture is not None:
            self.recorder._capture.set_muted(self._mic_muted)
        self.recording_controls.set_muted(self._mic_muted)
        self.waveform.set_mic_muted(self._mic_muted)
        self.status_label.setText("Microphone muted" if self._mic_muted else "Recording...")
```

- [ ] **Step 5: Reset mute state on IDLE**

In `_on_state_changed` (around line 318), inside the `elif state == RecordingState.IDLE:` branch, add:

```python
        elif state == RecordingState.IDLE:
            self.recording_controls.reset_timer()
            self.recording_controls.reset_levels()
            self._mic_muted = False
            self.waveform.set_mic_muted(False)
            # ...existing code in this branch stays
```

To find the exact block, search for `reset_levels()` — add the two new lines right after.

- [ ] **Step 6: Smoke-test import**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -c "from app.main_window import MainWindow; print('ok')"
```

Expected output: `ok`

- [ ] **Step 7: Commit**

```bash
git add app/main_window.py
git commit -m "main: wire mute button to capture, waveform, and settings"
```

---

## Task 13: Full test + manual verification

**Files:**
- No code changes.

- [ ] **Step 1: Run full test suite**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python -m pytest tests/ -v
```

Expected: All tests PASS. If any pre-existing unrelated test was already failing before this plan, note it but don't fix it here.

- [ ] **Step 2: Manual verification — launch the app**

Run:
```bash
cd C:/Users/buddy/Claude-Projects/TalkTrack && python main.py
```

Verify in the UI:

1. **Settings dialog:** Open Settings. In the General tab, confirm "Start recordings with microphone muted" checkbox is present and unchecked by default. Toggle it off. Close.
2. **Mute button during recording:** Start a recording. Confirm the Mute button appears in the recording controls row and is enabled. Click it. Confirm:
   - Button label changes to "🎤 Muted" with a red background.
   - The mic level meter goes flat.
   - A red "MIC MUTED" overlay appears on the mic (top) half of the waveform.
   - The system (bottom) half of the waveform continues to animate if there is system audio.
3. **Unmute:** Click the button again. Confirm the button returns to "🎤 Mute" and the overlay disappears.
4. **Pause while muted:** Mute, then Pause. Confirm the mute button stays enabled and you can toggle it while paused. Resume and confirm state is preserved.
5. **Stop resets state:** Stop the recording. Confirm the mute button is disabled and the overlay is gone.
6. **Start muted setting:** Open Settings, check "Start recordings with microphone muted". Save. Start a new recording. Confirm the Mute button is already in the muted state and the overlay is visible from the start.
7. **Copy All button:** Load a past recording that has a transcript. In the transcript pane, confirm:
   - An "Export JSON" button is NOT present.
   - A "Copy All" button IS present (to the left of Export TXT).
   - Clicking it shows a tooltip "Copied N segments to clipboard".
   - Paste into a text editor and verify format: `{speaker}: {text}` per line, blank line between speaker changes, no timestamps.

- [ ] **Step 3: Final commit (only if any last tweaks were needed)**

If manual verification required any fixes, commit them:

```bash
git add -A
git commit -m "fix: address manual verification feedback"
```

If nothing needed to be tweaked, skip this step.

---

## Self-Review Checklist (for the implementer to run before declaring done)

- [ ] All tasks above checked off.
- [ ] `python -m pytest tests/ -v` passes.
- [ ] `python main.py` launches without errors.
- [ ] All seven manual verification steps above pass.
- [ ] `git status` is clean (no stray uncommitted changes).
- [ ] `git log --oneline` shows a clean sequence of commits, one per task.
