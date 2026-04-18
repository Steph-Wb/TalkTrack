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

## Known Tier-3 integration gaps (flagged during implementation)

These were deferred from the automated test phase and must be verified/fixed during smoke:

1. `activate_process_loopback` in `_process_com.py` returns a raw IAudioClient pointer but does not currently:
   - Call `GetMixFormat` to populate real native_rate/channels/format on the stream.
   - Call `IAudioClient::Initialize` with `AUDCLNT_STREAMFLAGS_LOOPBACK`.
   - Call `IAudioClient::GetService(IID_IAudioCaptureClient)`.
   - Call `IAudioClient::Start`.
   - Stash `_native_frame_bytes = nBlockAlign` on the capture client.
   - Set `_capture_client` on the owning `ProcessCaptureStream`.
   Without these, the real COM path will AttributeError the first time `read_available()` is called. Complete the wiring while validating checks #1 and #2.

2. `_CompletionHandler.ActivateCompleted` may not receive the `this` pointer correctly under current comtypes binding — verify activation actually fires by logging or breakpointing the handler during check #1.

3. `_com_packet_iter` in `ProcessCaptureStream` terminates permanently after the first "no more packets" tick. Once wired to real COM, it must be rebuilt per `read_available()` call OR yield a sentinel instead of returning. Fix during check #1/#2 debugging.

4. PROPVARIANT / AUDIOCLIENT_ACTIVATION_PARAMS lifetime: the Python objects must stay alive through the `ActivateAudioInterfaceAsync` call — verify no use-after-free under stress (check #5).

## Regression run

After any PR touching the capture files, run through checks 1–4 as a minimum. Checks 5–7 are quarterly or for changes to activation/cleanup paths.
