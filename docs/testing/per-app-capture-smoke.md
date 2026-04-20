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

## Diagnostic logging

`_process_com.activate_process_loopback` logs one INFO line per successful
activation (`"[PID X] per-app activation complete (48000 Hz x 2 ch, float32)"`)
and routes failures to WARNING with the HRESULT name + hex. For deeper
per-step traces (apartment type, raw pointer addresses, each COM call's
return), bump the logger to DEBUG:

```python
import logging
logging.getLogger("app.recording._process_com").setLevel(logging.DEBUG)
```

## History: gaps resolved during bring-up

Left here as a debugging reference — each bit us during Tier-3 validation
and the fix is worth knowing about.

1. **Completion handler must implement `IAgileObject`.** Without it,
   `ActivateAudioInterfaceAsync` fails synchronously with
   `E_ILLEGAL_METHOD_CALL (0x8000000E)` because the API can't marshal the
   callback across apartments. WRL samples get this for free via
   `RuntimeClass`; `comtypes.COMObject` doesn't unless you list
   `IAgileObject` in `_com_interfaces_`.

2. **Virtual device path is a plain string, not a GUID.** The correct
   value per `mmdeviceapi.h` is `L"VAD\\Process_Loopback"`. Passing a GUID
   string returns `0x8000000E` synchronously.

3. **ctypes arg coercion for interface pointers was unreliable.** Switched
   `ActivateAudioInterfaceAsync.argtypes` to `c_void_p` across the board
   and pass raw pointer addresses via `ctypes.cast`. Avoids silent coercion
   failures with COMObject-derived handlers.

4. **`_com_packet_iter` must not cache a generator.** A generator that
   returns once goes permanently dead. `_drain_real_source` re-enters
   `read_next_packet` on every `read_available()` call instead.

5. **Apartment log mapping off-by-one.** APTTYPE enum is `STA=0, MTA=1`;
   my initial dict had them shifted by one, so diagnostic output during
   bring-up was misleading. Fixed.

## Regression run

After any PR touching the capture files, run through checks 1–4 as a
minimum. Checks 5–7 are quarterly or for changes to activation/cleanup
paths.
