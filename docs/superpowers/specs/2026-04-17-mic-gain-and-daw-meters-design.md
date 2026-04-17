# Mic Gain and DAW-Style Meters — Design

Date: 2026-04-17

## Overview

Two related UX improvements to help users get healthy mic levels relative to system/app audio:

1. **Mic gain control:** A live-adjustable multiplier applied to mic capture. Boosts quiet mic signals without requiring OS-level changes. Exposed on the main UI as a slider for mid-call adjustment.
2. **DAW-style level meters:** Replace the current thin horizontal level bars with prominent vertical meters that have a proper dB scale, color zones, peak hold, and clip indicators. Makes it obvious whether mic levels are healthy.

## Non-Goals

- **No soft-limit/compressor.** Hard-clip post-gain samples to `[-1, 1]`. A proper limiter is out of scope.
- **No per-mic gain.** Both mics share the same gain (consistent with mute scoping).
- **No system-audio gain.** System audio is at the user's chosen app volume; the issue being solved is specifically about mic levels.
- **No per-recording gain.** Gain is a device preference that persists in config, not a recording property.
- **No auto-gain / AGC.** Manual control only — predictable behavior.
- **No dB-scale slider.** Linear multiplier (`0.5×` to `5.0×`) because it's the simplest mental model.
- **No custom horizontal `LevelBar` removal from other parts of the app.** If `LevelBar` is reused elsewhere, it stays.

## Mic Gain

### Behavior

- Scope lives on `DualAudioCapture._mic_gain`, pushed down to both `AudioStream._gain` via `set_gain(float)`.
- Applied in `AudioStream._audio_callback`:
  1. `chunk = indata.copy()`
  2. If `_gain != 1.0`: multiply chunk by `_gain`, then `np.clip(chunk, -1.0, 1.0, out=chunk)` to prevent wraparound.
  3. If `_muted`: `chunk.fill(0.0)` (overrides gain — mute wins).
  4. Write to `_all_chunks`, call `_level_callback`.
- Order ensures the level meter reflects the *recorded* signal (post-gain, post-mute).
- `set_gain()` is thread-safe-enough for a single float write from the UI thread while the audio callback reads it; atomic on all supported platforms for float32 in practice. No lock needed.

### Config

- New key `audio.mic_gain` (float, default `1.0`). Range `0.5` to `5.0`.
- Persistence: **debounced writes.** Slider change triggers a 500ms timer; when the timer fires (no further changes), the value is written to config. Also flushed on `closeEvent` of the main window.

### UI control

- Horizontal slider in `MetersPanel`, placed directly below the mic meter (aligned with the mic column).
- Range: `5` to `50` (slider integer), maps to `0.5×` to `5.0×` via divide-by-10.
- Numeric readout to the right: `"1.5×"` (one decimal place).
- Tooltip: `"Boost microphone volume. 1.0× = no change. Higher values are hard-clipped to prevent distortion."`
- Value range rationale: `0.5×` gives headroom to attenuate a hot mic; `5.0×` is enough to rescue a very quiet USB mic. Above 5.0× is nearly always clipping — omitted to discourage bad use.

## DAW-Style Level Meters

### New widget: `MetersPanel` (`app/ui/meters_panel.py`)

A composite widget containing two vertical meters + gain slider + clip indicators.

**Layout:**

```
┌──────────────────────────────────┐
│  dB   MIC         SYS            │
│  0 ─  ▓▓▓─ ●CLIP  ▓▓▓─ ○          │
│ -6 ─  ▓▓▓         ▓▓▓             │
│-18 ─  ▓▓▓         ▓▓▓             │
│-40 ─  ▓▓▓         ▓▓▓             │
│-60 ─  ▓▓▓         ▓▓▓             │
│       -14 dB      -6 dB            │
│       MIC         SYS              │
│   Gain: [─────|────] 1.5×          │
└──────────────────────────────────┘
```

Meters are ~24px wide × 80px tall, side by side with ~16px horizontal gap. dB scale markers `0, -6, -18, -40, -60` on the left with tick marks.

### Color zones (painted top-to-bottom per bar)

- `-60` to `-18` dB: **green** (`#a6e3a1`) — healthy range
- `-18` to `-6` dB: **yellow** (`#f9e2af`) — target upper bound
- `-6` to `0` dB: **red** (`#f38ba8`) — hot / close to clip
- Above `0` dB: bright red clip line (`#f38ba8` solid)

### Peak hold indicator

- A 2px horizontal line per bar at the most-recent peak level.
- Holds for `1500ms`, then decays linearly to current level over `500ms`.
- Reset on `stop()`.

### Clip indicator

- A small red LED (`●`) next to each meter.
- Lights up when any sample in the last chunk has `abs(sample) >= 0.99`.
- Stays lit for `2000ms` after the last clipping chunk (sticky — ensures you see it even if clipping was brief).
- Reset on `stop()`.

### Numeric dB readout

- Below each meter: e.g., `-14 dB`. One integer decimal place for stability.
- Updates at the same ~10fps cadence as the bar paint.
- Uses existing `compute_rms_db` from `level_meter.py` (reused, not duplicated).

### Methods and signals

- `update_mic_level(chunk: np.ndarray)` — receives audio chunks from `MainWindow`, updates RMS, peak hold, clip detection, triggers repaint.
- `update_system_level(chunk: np.ndarray)` — same for system audio.
- `gain_changed = pyqtSignal(float)` — emitted when slider moves.
- `set_gain(float)` — sets slider value programmatically (from config load). Does NOT re-emit.
- `reset()` — clears peaks, clip state, and dB readouts. Called when recording stops.

### Repaint strategy

- The panel keeps internal state (current RMS, peak hold, peak-hold timestamp, clip timestamp) updated synchronously in the `update_*_level()` methods.
- A `QTimer` at ~15fps (66ms) calls `self.update()` to trigger repaint. This avoids repainting once per audio chunk (which could be hundreds of times per second).

## Layout Changes in `RecordingControls`

Before:
```
Row 1: [● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]
Row 2: ● 00:12:34  Mic ▓▓▓▓  Sys ▓▓▓▓
```

After:
```
Row 1: [● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]
Row 2: ● 00:12:34
```

Changes:
- Remove `self._mic_bar` and `self._sys_bar` (inline `LevelBar` instances).
- Remove `update_mic_level`, `update_system_level`, `reset_levels` methods (migrated to `MetersPanel`).
- Remove inline "Mic" / "Sys" labels and their styling.
- Row 2 keeps only `recording_indicator` + `timer_label`.
- `set_state()` no longer needs level-related resets; those move to `MetersPanel.reset()`.

## Wiring in `MainWindow`

- Instantiate `MetersPanel` as a new widget, placed in the left panel layout **below `RecordingControls`** and **above `WaveformDisplay`**.
- Reconnect the recorder level signals:
  - `self.recorder.mic_level.connect(self.meters_panel.update_mic_level)` (replacing the old connection to `self.recording_controls.update_mic_level`)
  - `self.recorder.system_level.connect(self.meters_panel.update_system_level)`
  - Keep the existing waveform connections (`mic_level → waveform.append_audio`, `system_level → waveform.append_system_audio`).
- Wire gain changes: `self.meters_panel.gain_changed.connect(self._on_gain_changed)`.
- `_on_gain_changed(float)` handler:
  - If `recorder._capture is not None`: call `capture.set_gain(gain)` (live update during recording).
  - Start/restart a 500ms `QTimer` (single-shot) to debounce config writes. On fire: `self.config.set("audio", "mic_gain", gain); self.config.save()`.
- On `_start_recording`: after `capture.start()`, call `capture.set_gain(self.config.get("audio", "mic_gain"))` so a fresh capture picks up the current gain.
- On `__init__`, after building `MetersPanel`: call `self.meters_panel.set_gain(self.config.get("audio", "mic_gain"))` to reflect saved value in the slider.
- On `closeEvent`: flush any pending debounced gain write by stopping the timer and saving immediately if the timer was active.
- On `_on_state_changed(IDLE)`: call `self.meters_panel.reset()`.

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `app/utils/config.py` | modify | Add `audio.mic_gain` default `1.0` |
| `app/recording/audio_capture.py` | modify | `AudioStream._gain` + `set_gain()`; multiply + clip in callback (before mute). `DualAudioCapture.set_gain()` propagates to both mic streams. |
| `app/ui/meters_panel.py` | **create** | DAW-style vertical meters + gain slider |
| `app/ui/recording_controls.py` | modify | Remove inline meters; simplify row 2 to indicator + timer |
| `app/main_window.py` | modify | Instantiate `MetersPanel`, reconnect level signals, wire gain handler with debounce, reset on IDLE, flush on close |
| `tests/test_dual_audio_capture.py` | modify | Add `TestAudioStreamGain` + `TestDualAudioCaptureGain` |
| `tests/test_meters_panel.py` | **create** | Tests for pure helpers (peak dB, clip detection, peak-hold decay, slider ↔ multiplier mapping) |

## Risks and Edge Cases

- **Gain + mute interaction:** Mute wins. Even at `gain=3.0`, muting produces silence. Tested explicitly.
- **Float atomicity:** `AudioStream._gain` is read in the audio thread, written in the UI thread. A single float32 write is atomic on x86_64 Windows; no lock needed.
- **Clip detection vs audio callback rate:** Clip is computed per chunk in the audio callback thread. The `MetersPanel` reads the "last clip timestamp" in paint — simple atomic read. No race condition that affects correctness.
- **Peak hold decay with silent input:** After a peak, silence should allow the peak line to fall. The decay logic runs during repaint based on `time.monotonic() - peak_hold_timestamp`.
- **Persistence during recording:** The 500ms debounce means a rapid drag only writes config once after you settle. Config save is small (~1KB file), acceptable.
- **Slider → multiplier mapping:** Qt `QSlider` is integer-only. Map `5 → 0.5×`, `50 → 5.0×`, i.e., `multiplier = slider_value / 10.0`. Tick interval 5 (0.5× steps). Step resolution 1 (0.1× steps via arrow keys / click-jumps).
- **No `LevelBar` regression:** Existing horizontal `LevelBar` in `level_meter.py` is unchanged. The helpers `compute_rms_db` and `db_to_fraction` are reused by `MetersPanel`.
- **`RecordingControls` API breakage:** The removed methods (`update_mic_level`, `update_system_level`, `reset_levels`) are called from `MainWindow._connect_signals` and `_on_state_changed`. Both will be updated in the same task. No external callers.
