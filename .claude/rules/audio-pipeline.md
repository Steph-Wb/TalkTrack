# Audio Pipeline: capture invariants and mute/gain semantics

## AudioStream callback processing order

`AudioStream._audio_callback` in `app/recording/audio_capture.py` processes each chunk in this exact order. Do not reorder — the tests encode this sequence:

1. `chunk = indata.copy()` (detach from device buffer)
2. If `_gain != 1.0`: multiply + `np.clip(chunk, -1.0, 1.0, out=chunk)` (pre-clip so downstream can't wrap)
3. If `_muted`: `chunk.fill(0.0)` (mute overrides gain — tested in `test_mute_beats_gain`)
4. Write to `_buffer` and `_all_chunks`
5. Call `_level_callback(chunk)` with the post-processed chunk

The level meter and waveform see the processed signal (what's actually being recorded), which is the intended UX.

## Mute and gain scoping

- Both live on `DualAudioCapture`: `_muted` + `set_muted(bool)` and `mic_gain` + `set_gain(float)`.
- Both propagate to `mic_stream` AND `mic_stream_2` (dual-mic-aware).
- Neither touches `loopback_stream` — system/app audio is **never** muted or gained. The "cough button" and "boost my mic" use cases are mic-only by design.
- `set_gain` always propagates; `start()` re-applies both after each mic stream is created.

## MainWindow → capture access pattern

- `MainWindow` reaches into `self.recorder._capture` directly for `set_muted`, `set_gain`, etc. This is the established pattern — do **not** add a `Recorder.set_muted`/`set_gain` passthrough. Recorder stays focused on state machine + session lifecycle.
- Debounced config writes (gain slider): 500ms single-shot `QTimer` on `MainWindow`, flushed on `closeEvent`. `_pending_gain` tracks value between drag and flush.
