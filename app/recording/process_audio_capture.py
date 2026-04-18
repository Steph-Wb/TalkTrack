"""Per-process audio capture using Windows 11 COM API.

Windows 11 (Build 22000+) introduced per-process audio loopback capture
via ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_PARAMS.
This module provides a pipeline for capturing audio from specific PIDs
and mixing the results into a single output stream.
"""
import logging
import threading
import time
from math import gcd
import numpy as np
import soundfile as sf
from scipy.signal import resample_poly

from app.utils.platform_info import is_windows_11

logger = logging.getLogger(__name__)


def stereo_to_mono(data):
    """Downmix multi-channel audio to mono by averaging channels.

    Args:
        data: numpy array of shape (samples, channels)

    Returns:
        numpy array of shape (samples,) with averaged channels
    """
    if data.ndim == 1:
        return data
    return data.mean(axis=1).astype(np.float32)


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


class ProcessCaptureStream:
    """Captures audio from a single process by PID using Win11 COM API.

    Uses ActivateAudioInterfaceAsync with AUDIOCLIENT_ACTIVATION_PARAMS
    to capture loopback audio from a specific process. The actual COM
    capture loop (_read_audio_packets) is a placeholder until the
    full COM interop is implemented.
    """

    def __init__(self, pid, sample_rate=16000, channels=1):
        self.pid = pid
        self.sample_rate = sample_rate
        self.channels = channels
        self._recording = False
        self._paused = False
        self._all_chunks = []
        self._thread = None
        self._lock = threading.Lock()

    def start(self):
        """Start capturing audio from the target process."""
        if not is_windows_11():
            raise RuntimeError(
                "Per-process audio capture requires Windows 11 (Build 22000+)"
            )
        self._recording = True
        self._paused = False
        self._all_chunks = []
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def pause(self):
        """Pause audio capture (stops storing chunks)."""
        self._paused = True

    def resume(self):
        """Resume audio capture after pause."""
        self._paused = False

    def stop(self):
        """Stop capturing and wait for background thread to finish."""
        self._recording = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def get_audio_data(self):
        """Return all captured audio as a mono numpy array."""
        with self._lock:
            if not self._all_chunks:
                return np.array([], dtype=np.float32)
            data = np.concatenate(self._all_chunks, axis=0)
        if data.ndim > 1:
            data = stereo_to_mono(data)
        return data

    def save_to_file(self, filepath):
        """Save captured audio to a WAV file."""
        data = self.get_audio_data()
        if data.size == 0:
            return None
        sf.write(str(filepath), data, self.sample_rate)
        return str(filepath)

    @property
    def is_active(self):
        """Whether the capture stream is currently recording."""
        return self._recording


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
