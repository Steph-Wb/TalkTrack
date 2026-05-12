---
name: Code weakness backlog
description: Prioritised list of weaknesses found during 2026-05-07 audit of TalkTrack; tracks which are done
type: project
---

Audit date: 2026-05-07. Weaknesses found by static + dynamic review.

**Why:** Ongoing quality improvement. Apply this list whenever the user asks to fix weaknesses or work through the backlog.
**How to apply:** Pick the next open item, write a failing test, implement, verify.

## High severity

- [x] **#1 Race condition — silence detection** (`audio_capture.py:569,583`): `_last_mic_active_time` written by mic callback thread, read by system thread with no lock. Fixed 2026-05-07 with `threading.Lock`.
- [x] **#5 Unbounded `_all_chunks` RAM** (`audio_capture.py:28,43` + `process_audio_capture.py:337`): every audio frame buffered forever in RAM; 700 MB for 3-hour call. Fixed 2026-05-07 by streaming chunks to a temp soundfile during recording.
- [ ] **#2 Non-atomic file writes** (`main_window.py:984,998,1017`): transcript/speaker/metadata JSON written directly; crash mid-write corrupts file. Fix: write-to-temp + `os.replace()`.
- [ ] **#3 Config.save() on every set()** (`config.py:92-99`): each slider drag flushes full JSON to disk. Fix: debounce saves.
- [ ] **#4 No fallback on corrupt config** (`config.py:73-75`): `json.load` raises `JSONDecodeError` on corrupt file; app crashes at startup. Fix: catch + fall back to defaults.
- [ ] **#6 Silent FFmpeg failure** (`recorder.py:193-194`): MP3 conversion errors swallowed with bare `pass`. Fix: `logger.warning`.

## Medium severity

- [ ] **#7 Bare KeyError on missing config key** (`config.py:88-89`): `Config.get()` raises with no context. Fix: wrap with a helpful message.
- [ ] **#8 No error handling in `_save_transcript` / `_save_speaker_names`** (`main_window.py:984,998`): `OSError` on disk-full crashes signal handler. Fix: add try/except with user-visible error.
- [ ] **#9 Foreign keys silently merged in config** (`config.py:106-111`): unknown keys from saved file merge into `_data`. Fix: strip unknown keys in `_deep_merge`.
- [ ] **#10 Plaintext secrets in config**: `hf_token` and API keys stored unprotected at `~/.talktrack/settings.json`. Low urgency (single-user desktop), but noted.

## Low severity

- [ ] **#11 `print()` instead of logger** (`main_window.py:1020`): metadata save failure emits to stdout. Fix: `logger.error`.
- [ ] **#12 No max silence duration** (`audio_capture.py:328`): user can set silence_duration to 99999. Fix: clamp in `set_silence_detection`.
- [ ] **#13 Wrong loopback fallback** (`audio_capture.py`): if named device not matched, picks first loopback arbitrarily. Fix: raise or return None.
