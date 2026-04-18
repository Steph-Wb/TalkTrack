# Per-App Audio Capture (Windows 11)

**Date:** 2026-04-18
**Status:** Approved, ready for implementation plan
**Scope:** Finish the scaffolded per-process audio capture pipeline so "Selected apps" mode records (and previews during Test) only the selected apps' audio.

---

## Problem

`DualAudioCapture.start()` today ignores `capture_mode` and `app_pids`. Regardless of the user's selection in the Audio Sources panel, it always opens a `LoopbackStream`, which captures *all* system audio via WASAPI loopback. The scaffolded `ProcessCaptureStream._read_audio_packets()` is a placeholder (`while self._recording: sleep(0.01)`); no COM objects are created. Users who pick "Teams" in per-app mode believe they are recording only Teams, but any other audio playing (Spotify, browser tabs, Windows notifications) lands in the recording.

The fix is to implement real Windows 11 process-loopback capture and dispatch on `capture_mode`.

## Goals

- When the user is in per-app mode with N apps selected, only those apps' audio reaches the system track and the system meter during Test.
- Record mode and Test mode use the *same* capture path so the meter is an honest preview of what will be recorded.
- Partial failures surface to the user without blocking the recording (K of N semantics).
- Legacy "All system audio" mode behaves identically to today.

## Non-goals

1. Event-driven capture loop — polling at 10 ms is adequate for 16 kHz speech; event mode is an internal optimization if ever needed.
2. Live PID add/remove during recording — the set locks at record start. `add_pid`/`remove_pid` scaffolding will be deleted.
3. `PROCESS_LOOPBACK_MODE_EXCLUDE_TARGET_PROCESS_TREE` (inverse selection). No UI for it.
4. Per-PID gain or ducking. Mixer uses equal-weight mean.
5. Variable sample rate. Target remains 16 kHz mono.
6. Retry logic on activation failure. Fail fast, surface status.
7. Silent loopback fallback when per-app activation fails. Per Q1 answer C we hard-error instead, because silent fallback recreates the bug this work is fixing.
8. Rewriting `LoopbackStream`. Legacy mode is untouched.
9. New Settings dialog controls.

## Decisions (captured during brainstorm)

| Question | Decision |
|---|---|
| Fallback when per-app activation fails | **C** — per-PID tolerance. Record from the PIDs that activate; error only if zero succeed. |
| Test Mic behavior in per-app mode | **A** — Test uses per-app capture too, matching the record path. Accept the ~200–400 ms per-PID activation latency. |
| Live PID add/remove mid-recording | **A** — lock at start. Simpler, matches the assumption that users don't re-pick sources mid-call. |

## Architecture

Three layers, duck-typed interfaces so the mixer and dispatch don't care about implementation details.

### `ProcessCaptureStream` (one per PID)

Owns COM objects for a single process. No thread of its own.

Public surface:
```
activate() -> bool                 # sync; blocks up to 5s; returns success
read_available() -> list[np.ndarray]  # non-blocking; drains ready packets
put_back_tail(arr: np.ndarray)     # mixer hands back post-resample residue to prepend next tick
release()                          # stop + close COM
is_active: bool
pid: int
native_rate: int                   # set at activate
native_channels: int
native_format: str                 # "float32" | "s16" | "s24"
last_error: str | None
```

Internal state (not read by the mixer):
```
_pre_resample_buf: np.ndarray      # raw-rate sample accumulator for resample_poly alignment
_post_mix_tail: np.ndarray         # 16 kHz samples handed back by mixer's trim-to-shortest
```

`_post_mix_tail` is prepended to the output of the next `read_available()`. `put_back_tail()` is the only way the mixer writes this field — no field-poking across the abstraction.

### `ProcessAudioCapture` (one per session)

Mixer. Owns the single polling thread.

```
__init__(pids, sample_rate, level_callback, enable_buffer=True)
set_level_callback(fn)
start() -> dict                    # activates streams in parallel; returns status
pause()
resume()
stop() -> dict                     # returns {"mixed_audio": ndarray, "duration": float, "active_pids": [...]}
save_to_file(path) -> str | None
is_active: bool
capture_status: dict               # {"total": N, "active": K, "failures": {pid: hresult_name}}
```

Signals (or callbacks — exact emission style decided at implementation):
- `pid_lost(pid, error)` — a single stream went inactive mid-session.
- `capture_lost()` — all streams have gone inactive.

### `DualAudioCapture` dispatch

Rename `self.loopback_stream` → `self.system_stream`. At `start()`:

```
if capture_mode == "per_app" and app_pids:
    self.system_stream = ProcessAudioCapture(...)
    status = self.system_stream.start()
    if status["active"] == 0:
        raise RuntimeError(f"Per-app capture failed for all selected apps: {status['failures']}")
    self._capture_status = status
elif self.loopback_device is not None:
    self.system_stream = LoopbackStream(...)   # unchanged
    self.system_stream.start()
else:
    self.system_stream = None
```

Both backends expose `start/pause/resume/stop/save_to_file`. `pause`/`resume`/`stop` already iterate over the field; renaming is the only change.

### File split

`app/recording/process_audio_capture.py` will grow with COM plumbing. Split into:
- `process_audio_capture.py` — public `ProcessCaptureStream` / `ProcessAudioCapture` classes, mixer loop, format conversion.
- `_process_com.py` — `ctypes.Structure` definitions (`AUDIOCLIENT_ACTIVATION_PARAMS`, `PROPVARIANT`, `WAVEFORMATEX`), GUID constants, `IActivateAudioInterfaceCompletionHandler` implementation, `hresult_name()` helper. Tests mock this layer cleanly without touching COM.

## COM Integration

Happens inside `ProcessCaptureStream.activate()`, called from `ProcessAudioCapture.start()` (one call per PID, parallelized via `ThreadPoolExecutor`).

### Sequence

1. **MTA init.** `CoInitializeEx(NULL, COINIT_MULTITHREADED)` on the mixer thread at startup. Process-loopback activation silently misbehaves on STA threads.
2. **Build `AUDIOCLIENT_ACTIVATION_PARAMS`**:
   ```
   ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK  (= 1)
   ProcessLoopbackParams.TargetProcessId = pid (ULONG)
   ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE  (= 0)
   ```
   Wrap in a `PROPVARIANT` of type `VT_BLOB`.
3. **Activate.** `ActivateAudioInterfaceAsync(VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK, IID_IAudioClient, &params, completion_handler, &operation)`. `VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK` is the literal GUID string.
4. **Wait synchronously.** `CreateEventW` + completion handler calls `SetEvent` in `ActivateCompleted` + `WaitForSingleObject(event, 5000)`. On timeout or failure HRESULT, `last_error = "activation_failed: <hresult_name>"`, return `False`.
5. **Query result.** `operation.GetActivateResult(out hr, out punkActivatedInterface)`. Cast to `IAudioClient`.
6. **Initialize.**
   ```
   IAudioClient::Initialize(
       AUDCLNT_SHAREMODE_SHARED,
       AUDCLNT_STREAMFLAGS_LOOPBACK,
       bufferDuration = 2_000_000,    # 200 ms in 100ns units
       periodicity = 0,
       pFormat = WAVEFORMATEX{IEEE_FLOAT, 48000, 2, 32},
       sessionGuid = NULL,
   )
   ```
   Process-loopback is known to ignore the requested format and return its own. We capture the negotiated format from `GetMixFormat` and the `IAudioClient` state at init time, and feed those into the resampler.
7. **Get capture interface.** `IAudioClient::GetService(IID_IAudioCaptureClient, ...)`.
8. **Start.** `IAudioClient::Start()`.

### `read_available()` inner loop

Non-blocking; drains whatever is ready on the capture client:

```
while True:
    hr, num_frames = capture.GetNextPacketSize()
    if hr == AUDCLNT_E_DEVICE_INVALIDATED:
        self.is_active = False
        self.last_error = "device_invalidated"
        return chunks
    if num_frames == 0:
        return chunks
    hr, data_ptr, frames, flags = capture.GetBuffer()
    if flags & AUDCLNT_BUFFERFLAGS_SILENT:
        arr = np.zeros(frames * native_channels, dtype=np.float32)
    else:
        buf = ctypes.string_at(data_ptr, frames * native_frame_bytes)
        arr = np.frombuffer(buf, dtype=NATIVE_DTYPE).reshape(frames, native_channels)
    capture.ReleaseBuffer(frames)
    chunks.append(convert_to_target(arr))   # dtype + downmix + resample
```

### `release()`

`Stop()`, release capture client + audio client (comtypes handles refcounts), close event handle, unregister completion handler. `CoUninitialize` only on owning thread teardown.

### Known risks (accepted)

1. `comtypes` has no type library for process-loopback activation. Struct and GUID definitions are hand-written against the Windows SDK headers. Mitigation: struct-size sanity tests in CI (Tier 2).
2. Negotiated format ≠ requested format. Mitigation: resampler reads the actually-negotiated format from the stream, not from a constant. Log the negotiated format at activation time.
3. Process-loopback flakiness on older Win11 builds. Mitigation: existing `is_windows_11()` build ≥ 22000 gate; log build number in activation errors.

## Mixer Loop

Single thread inside `ProcessAudioCapture`. Runs at 10 ms cadence. One responsibility: drain every active stream, mix, fire the level callback, append to the buffer list.

```
while self._running:
    if self._paused:
        # Drain clients so their ring buffers don't overflow; discard output.
        for s in list(self._streams.values()):
            if s.is_active:
                s.read_available()
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
        min_len = min(len(c) for c in per_stream_chunks.values())
        aligned = [c[:min_len] for c in per_stream_chunks.values()]
        for pid, c in per_stream_chunks.items():
            self._streams[pid].put_back_tail(c[min_len:])
        mixed = np.mean(np.stack(aligned, axis=0), axis=0).astype(np.float32)
        if self._enable_buffer:
            self._all_chunks.append(mixed)
        if self._level_callback:
            self._level_callback(mixed)

    if not any(s.is_active for s in self._streams.values()):
        self._emit_capture_lost()
        break

    time.sleep(0.010)
```

### Trim-to-shortest rationale

Process-loopback clients don't tick at identical rates. Mixing naively pads the shorter chunk with zeros, audible as ~0.6 ms dips per tick. Trimming to the shortest and carrying the tail keeps samples time-aligned.

### Parallelized activation at start

```
with ThreadPoolExecutor(max_workers=len(pids)) as ex:
    futures = {pid: ex.submit(s.activate) for pid, s in self._streams.items()}
    for pid, fut in futures.items():
        success = fut.result(timeout=6.0)    # matches the 5s activation wait + buffer
```

Total worst-case activation time is bounded at ~5 s regardless of N. Mixer thread starts only after activation completes. Returns `{"total": N, "active": K, "failures": {pid: error}}`.

### Crash containment

Per-stream block wrapped in `try/except`. The whole loop body is additionally wrapped in an outer `try/except` that sets `self._crashed = True` and breaks. `stop()` checks the flag and surfaces a distinct "capture crashed" error instead of pretending it was clean.

## Format Conversion & Resampling

Lives in `ProcessCaptureStream`, runs before `read_available()` returns. Mixer only ever sees 16 kHz mono float32.

Order:
1. **Dtype → float32.**
   - `IEEE_FLOAT32` (common case) — no conversion.
   - `PCM s16` — `arr.astype(np.float32) / 32768.0`.
   - `PCM s24 in 32-bit container` — `(arr >> 8).astype(np.float32) / 8388608.0`.
   Native format detected at activate time from `WAVEFORMATEX.wFormatTag + wBitsPerSample`.
2. **Downmix to mono.** `arr.mean(axis=1)` when `native_channels > 1`. Arithmetic mean is indistinguishable from ITU-R BS.775 weights for speech/meeting content.
3. **Resample to 16 kHz.** `scipy.signal.resample_poly(x, up, down)` where `(up, down) = (16000 // gcd, native_rate // gcd)`. Common 48 kHz case is `(1, 3)`. Polyphase is clean, no FFT ringing. Default Kaiser filter is fine for speech.

### Pre-resample sample carry (`_pre_resample_buf`)

`resample_poly` requires input length to be a multiple of `down` for clean output. When source packets don't align, `ProcessCaptureStream` accumulates raw-rate frames in `_pre_resample_buf`, resamples on multiples of `down`, and keeps the remainder for the next call (at most 2 samples at 48 kHz, ~42 µs — inaudible). This is *internal* to `read_available()`; the mixer never sees raw-rate samples.

Distinct from `_post_mix_tail`, which holds post-resample 16 kHz samples handed back by the mixer's trim-to-shortest step. `_post_mix_tail` is prepended to the output of the next `read_available()` call.

### Silence flag fast path

`AUDCLNT_BUFFERFLAGS_SILENT` skips dtype/downmix/resample and returns `np.zeros(target_frames, dtype=np.float32)` directly.

## Dispatch in `DualAudioCapture`

See Architecture section. Changes:

- Rename `self.loopback_stream` → `self.system_stream` (and any `MainWindow` accessors).
- `start()` branches on `capture_mode`.
- `pause`/`resume`/`stop`/save stay identical (both backends expose the same methods).
- `_system_cb` wrapper (forwards to `self._system_level_callback` + calls `self._check_silence`) is unchanged; silence auto-stop works in both modes.
- `metadata.json` gains a `capture_status` field (activation result dict) so partial-failure sessions are diagnosable after the fact.
- Docstring update on `capture_mode` / `app_pids` fields: they are now live state, not scaffolding.

## Test Mode Wiring

`MainWindow._start_system_monitor()` dispatches on `capture_mode`:

```
if mode == "per_app":
    pids = self.source_selector.get_selected_app_pids()
    if not pids:
        return
    monitor = ProcessAudioCapture(
        pids=pids,
        sample_rate=..., level_callback=self.meters_panel.update_system_level,
        enable_buffer=False,
    )
    status = monitor.start()
    if status["active"] == 0:
        logger.warning("Test per-app monitor failed: %s", status["failures"])
        return
    self.system_monitor = monitor
else:
    # existing legacy-loopback path, unchanged
```

`enable_buffer=False` mirrors what was added to `LoopbackStream` previously: skip `self._all_chunks.append` while still firing the level callback. No memory growth during long tests.

`_stop_system_monitor()` stays generic — calls `self.system_monitor.stop()` regardless of type.

Idle-app behavior: if Teams is selected but silent, meter sits at -60. This is correct — recording would capture the same silence.

## Partial-Failure Status UX

### New signals on `Recorder`

```
capture_status = pyqtSignal(dict)   # fires once after start_recording
pid_lost = pyqtSignal(int, str)     # fires when an individual PID stream dies
capture_lost = pyqtSignal()         # fires when all PIDs are dead
```

### MainWindow handling

`_on_capture_status(status)`:
- `active == total` → nothing. Normal flow.
- `0 < active < total` → status-bar line: `"Recording — capturing {active} of {total} apps ({failed_names} unavailable)"`. Calls `source_selector.mark_capture_failures(failures)` to show a ⚠ label.
- `active == 0` → already turned into `error_occurred` upstream; standard error path (QMessageBox).

`_on_pid_lost(pid, error)` — updates the same "K of N" status; moves the affected app's name into the warning tooltip. No modal.

`_on_capture_lost()` — stops the recording (same path as silence auto-stop), saves what was captured, shows `"Capture ended: all selected apps became unavailable"`.

### Source selector warning label

`SourceSelector.mark_capture_failures(failures: dict[int, str])`:
- Maintains a small `QLabel#captureWarning` adjacent to the app list.
- Visible only when `failures` is non-empty.
- Text = `"\u26a0"` (⚠), color `#f9e2af` (Catppuccin yellow), inline style.
- Tooltip renders per-app breakdown (`Teams: AUDCLNT_E_DEVICE_INVALIDATED\nChrome: E_ACCESSDENIED`).
- Cleared on state transition to IDLE and on app-selection change.

### No modal at start

Recording proceeds with partial captures. User is informed non-blockingly via status bar + warning label. Modal mid-flow is worse UX than a persistent indicator.

## Error Handling Matrix

| Scenario | Behavior |
|---|---|
| Some PIDs fail activation (K < N, K > 0) | Status dict surfaces it. Recording proceeds. |
| All PIDs fail activation (K = 0) | `DualAudioCapture.start()` raises. `Recorder` emits `error_occurred`, returns to IDLE. Mic stream torn down first — activate system stream *before* mic stream. |
| Single PID dies mid-recording | Mixer catches `AUDCLNT_E_DEVICE_INVALIDATED`, emits `pid_lost`. Loop continues with the rest. |
| All PIDs die mid-recording | Mixer emits `capture_lost`, breaks. `DualAudioCapture.stop()` saves partial file, `Recorder.error_occurred` surfaces the message. Standard STOPPING → IDLE transition so auto-transcription still fires on the partial file. |
| Mixer thread unhandled exception | Outer `try/except` sets `_crashed = True`, breaks. `stop()` surfaces "capture crashed unexpectedly — see logs" (distinct from clean stop). |

No retry logic. Windows activation is deterministic for a given (PID, build, audio session state); retrying within the same second doesn't change outcomes.

COM error translation: `_process_com.py` exposes `hresult_name(hr) -> str` — known codes map to symbols (`AUDCLNT_E_DEVICE_INVALIDATED`, `E_ACCESSDENIED`, `ERROR_NOT_FOUND`), unknown render as `0x%08X`. Symbols bubble into the status dict and user-facing tooltips.

All failure modes log at `WARNING` or higher to the `talktrack` logger.

## Testing Strategy

Three tiers.

### Tier 1 — pure-logic unit tests (CI, no hardware)

Extend `tests/test_process_audio_capture.py`:

- `mix_audio_chunks` residual-carry path.
- Format conversion per dtype (s16, s24, float32 bytes → float32 array).
- Resampling: synthetic 440 Hz sine at 48 kHz → 16 kHz; FFT the output; peak must remain at 440 Hz (not at 1320 Hz — the chipmunk-ratio bug).
- `hresult_name` symbol mapping for known codes.
- `ProcessAudioCapture` mixer loop with `ProcessCaptureStream` replaced by a `FakeStream` injecting canned chunks. Covers trim-to-shortest, residual carry, partial-failure handling, pause/resume (output discarded), crash-in-stream containment.
- Status dict shape for mixed successful/failed activates.
- Signal emission: `pid_lost` exactly once per death, `capture_lost` exactly once at total loss.

Target ~15–20 new tests.

### Tier 2 — COM struct/constants sanity (CI on Windows, no audio)

- `ctypes.sizeof(AUDIOCLIENT_ACTIVATION_PARAMS)` matches documented size.
- GUID constants parse as valid `comtypes.GUID`.
- `AUDCLNT_STREAMFLAGS_LOOPBACK` matches Windows SDK value.
- `is_windows_11()` build-number boundary.

Target ~5 tests.

### Tier 3 — manual smoke tests (Win11 machine required)

Documented as a checklist in `docs/testing/per-app-capture-smoke.md`:

1. Per-app mode, Teams selected, click Test. Speak on Teams side of a test meeting. Confirm meter moves.
2. Record 30 s with Teams selected. Play audio in Chrome during recording. `system_audio.wav` must contain Teams audio and *not* Chrome audio.
3. Teams + Chrome selected. Kill Chrome mid-recording. Status must update to "1 of 2". Recording continues. Final file contains Teams audio to the end.
4. Select an app that refuses activation (if one can be found — sandboxed UWP candidates). Partial-failure UX renders correctly.
5. Stress: 5+ apps, start/stop 20 cycles. Handle count stable in Task Manager.
6. Negative: Windows 10 VM. Per-app radio hidden/disabled as today.

This checklist is the "done" bar.

### Coverage gaps (accepted)

`ActivateAudioInterfaceAsync` call, completion handler plumbing, `GetBuffer` with real packets are not automated. Mocking `comtypes` COM pointers deeply is a high-effort/low-signal rabbit hole. A single manual smoke pass is more informative than 200 lines of mocks.

## Files Touched

- `app/recording/process_audio_capture.py` — major rewrite (scaffolding → real implementation).
- `app/recording/_process_com.py` — new; ctypes structs, GUIDs, completion handler.
- `app/recording/audio_capture.py` — rename `loopback_stream` → `system_stream`; dispatch on `capture_mode`; store `_capture_status`.
- `app/recording/recorder.py` — new signals (`capture_status`, `pid_lost`, `capture_lost`); wire activation status into error path; save `capture_status` to `metadata.json`.
- `app/main_window.py` — handle new signals; update status bar; `_start_system_monitor` dispatches on mode; rename `loopback_stream` references.
- `app/ui/source_selector.py` — `mark_capture_failures()` method; ⚠ warning label.
- `tests/test_process_audio_capture.py` — expand with Tier 1 coverage.
- `tests/test_process_com.py` — new; Tier 2 coverage.
- `tests/test_dual_audio_capture.py` — update for dispatch branch.
- `docs/testing/per-app-capture-smoke.md` — new; Tier 3 checklist.

## Open Questions (none)

All design questions resolved during brainstorming. Remaining uncertainty is implementation-level and will surface during coding.
