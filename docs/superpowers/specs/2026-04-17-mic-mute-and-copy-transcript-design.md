# Mic Mute and Copy Transcript — Design

Date: 2026-04-17

## Overview

Two related UX improvements to TalkTrack:

1. **Mic mute:** Allow the user to mute the microphone(s) during a recording without pausing/stopping it. Useful when the user wants to stay recording system audio but stop picking up their own voice (coughing, side conversation, listening-only mode). A persistent setting controls whether new recordings start muted.
2. **Copy all transcript:** A one-click button that copies the entire transcript to the clipboard as plain text (speaker + text, no timestamps) for pasting into external AI tools. The existing Export JSON button is removed as unused.

## Non-Goals

- **No hotkey.** Muting requires the TalkTrack window. A global hotkey was considered and rejected for simplicity.
- **No per-mic mute.** When dual mics are configured, both mute together via a single toggle.
- **No mute-state persistence across recordings.** Each new recording starts muted or unmuted based solely on the `mic_mute_on_start` setting.
- **No transcript marking of muted ranges.** Muted audio is silent, so Whisper produces no segments for those ranges — nothing to mark.
- **No JSON export replacement.** The JSON export is removed outright; power users who need structured data can read `transcript.json` directly from the recording directory.

## Mic Mute

### Behavior

- **Scope of mute flag:** Lives on `DualAudioCapture` as the single source of truth, pushed down to both `AudioStream` instances (`mic_stream`, `mic_stream_2`).
- **Semantics (Option A — zeroed chunks, preserved timeline):** When muted, each `AudioStream._audio_callback` continues to receive audio from the device, but before writing to `_all_chunks` (and before calling `_level_callback`), the chunk is zeroed. This means:
  - The saved `mic_audio.wav` length still equals the system audio length — timeline alignment preserved.
  - Whisper transcribes silence, so muted stretches contribute no transcript segments.
  - Level meter and waveform naturally render as zero because they're fed the zeroed chunk.
- **When mute is respected:** Only during `RECORDING` state. When `PAUSED`, the callback already skips writing, so mute is a no-op. When `IDLE`, there is no stream.

### UI — Mute button on recording controls

- New button added to `RecordingControls` button row: `[● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]`
- States:
  - **Recording + unmuted:** Label "🎤 Mute", default button style, enabled.
  - **Recording + muted:** Label "🎤 Muted", red-tinted border/background using `#f38ba8` (Catppuccin red), enabled.
  - **Paused:** Button remains enabled and toggleable (user can pre-set mute state for when they resume).
  - **Idle / Stopping:** Disabled, default style.
- New signal: `mute_clicked = pyqtSignal()`.
- New method: `set_muted(bool)` to update the button's visual state from `MainWindow`.

### UI — Visual indicators (dual purpose)

Three indicators reinforce the muted state so the user can't forget:

1. **Mute button state** (above): text + red tint.
2. **Mic level meter:** Automatically flat because it receives zeroed chunks. No code changes in `LevelBar`.
3. **Waveform "MIC MUTED" overlay:**
   - New `WaveformDisplay.set_mic_muted(bool)` method stores the flag.
   - In `paintEvent`, after drawing the mic half (top), if `_mic_muted` is True:
     - Paint a semi-transparent red rectangle (`QColor(243, 139, 168, 80)`) covering the mic half.
     - Draw the text "MIC MUTED" centered in that region in bright red (`#f38ba8`), bold, ~14px.
   - System half unaffected.
   - Rationale for the overlay (vs just a flat line): a flat line is ambiguous (could mean unplugged mic, dead device, silence). The red "MIC MUTED" label makes the state unambiguous — muted by the user, on purpose.

### Settings

- New config key: `audio.mic_mute_on_start` (bool, default `False`).
- Added to General tab of settings dialog (near `auto_record` / `silence_auto_stop`):
  ```
  [ ] Start recordings with microphone muted
      When checked, new recordings begin with the mic muted.
      Toggle mute anytime during recording via the Mute button.
  ```
- Single setting applies to both mics when dual-mic mode is configured.

### Orchestration in MainWindow

- When `capture.start()` succeeds and `config.get("audio", "mic_mute_on_start")` is True:
  - Call `capture.set_muted(True)`.
  - Call `recording_controls.set_muted(True)`.
  - Call `waveform_display.set_mic_muted(True)`.
- When the Mute button is clicked (signal `mute_clicked`):
  - Toggle a `_mic_muted` state on `MainWindow`.
  - Call `capture.set_muted(new_state)`, `recording_controls.set_muted(new_state)`, `waveform_display.set_mic_muted(new_state)` in sync.
- When recording stops: reset `_mic_muted = False`, clear waveform overlay (`stop()` already hides the widget).

## Copy All Transcript

### UI change

Current export row:
```
[▶ Play All] [Continue playing]    [Export TXT] [Export SRT] [Export JSON]
```

New export row:
```
[▶ Play All] [Continue playing]    [Copy All] [Export TXT] [Export SRT]
```

- `Export JSON` button and its enable/disable calls removed.
- `_export("json")` branch in `_export()` removed.
- New `Copy All` button:
  - Enabled/disabled in lockstep with Export TXT / Export SRT (same `setEnabled` calls in `display_transcript()` and `clear()`).
  - On click: call `_on_copy_all_clicked()`.

### Copy-text format

```
Alice: Hey everyone, let's get started.
Bob: Sure, I have the report ready.

Alice: Great, go ahead.
```

Rules:
- One segment per line: `{speaker}: {text}`
- Speaker resolution: `self._speaker_names.get(seg.speaker)` if present and non-empty, else raw `seg.speaker` (e.g., `SPEAKER_00`), else the text alone (no prefix) for segments with no speaker.
- Blank line inserted when the speaker changes between consecutive segments (improves readability when pasting into an LLM).
- No timestamps.
- No trailing newline.

### Implementation

- New method on `TranscriptResult` (`app/transcription/transcriber.py`): `to_plain_text(speaker_names=None)` — implements the format above. Separate from existing `to_text()` (which keeps timestamps and is used by Export TXT).
- `_on_copy_all_clicked()` in `TranscriptViewer`:
  - Guard: if no transcript, return.
  - Build text via `self._transcript.to_plain_text(speaker_names=self._speaker_names)`.
  - Call `QApplication.clipboard().setText(text)`.
  - Show brief feedback: a 2-second temporary status message near the button ("Copied N segments to clipboard"). Use a `QLabel` that appears briefly and fades, or a transient tooltip. Simplest: `QToolTip.showText(button.mapToGlobal(...), "Copied N segments", ...)`.

## Files Touched

| File | Change |
|---|---|
| `app/recording/audio_capture.py` | Add `_muted` flag + `set_muted(bool)` on `AudioStream` and `DualAudioCapture`; zero chunk in `_audio_callback` when muted |
| `app/ui/recording_controls.py` | Add Mute button, `mute_clicked` signal, `set_muted(bool)` method; update `set_state()` to enable/disable appropriately |
| `app/ui/waveform_display.py` | Add `_mic_muted` flag, `set_mic_muted(bool)`; paint red overlay on mic half in `paintEvent` when muted |
| `app/ui/transcript_viewer.py` | Add `Copy All` button, `_on_copy_all_clicked()`; remove Export JSON button and branch |
| `app/ui/settings_dialog.py` | Add `mic_mute_on_start_cb` in General tab; load/save |
| `app/utils/config.py` | Add `audio.mic_mute_on_start: False` default |
| `app/main_window.py` | Wire mute signal through to capture + waveform; apply `mic_mute_on_start` on recording start; reset on stop |
| `app/transcription/transcriber.py` | Add `TranscriptResult.to_plain_text(speaker_names=None)` |

## Tests

| Test file | Coverage |
|---|---|
| `tests/test_dual_audio_capture.py` | New test: `set_muted(True)` on `DualAudioCapture` propagates to both mic streams. `AudioStream._audio_callback` with `_muted=True` zeros the written chunk but preserves length. |
| `tests/test_transcriber.py` | New tests for `TranscriptResult.to_plain_text`: speaker name resolution (friendly name → raw ID → no-prefix); blank line on speaker change; no timestamps; no trailing newline; empty transcript returns empty string. |
| `tests/test_recording_header.py`-style helpers | No test needed for pure-visual overlay; pure helper `set_mic_muted` just toggles a flag. Covered by smoke verification. |

## Risks and Edge Cases

- **Mute during silence-auto-stop window:** Silence auto-stop monitors system audio, not mic. Mute affects mic only. No interaction — silence auto-stop continues to work correctly whether mic is muted or not.
- **Mute persisted into next recording:** Not wanted. `MainWindow._mic_muted` is reset to False on stop, so the next recording honors the `mic_mute_on_start` setting cleanly.
- **Level callback during mute:** The level callback receives the zeroed chunk, so meters show flat. This is the desired effect (reinforces the muted state visually). No separate path needed.
- **Waveform paintEvent performance:** The overlay adds one `fillRect` + one `drawText` per repaint (~15fps). Negligible cost.
- **Pyqt clipboard availability:** `QApplication.clipboard()` is available whenever the Qt app is running. No fallback needed for the Copy All path.
