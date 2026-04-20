"""Always-on mic stream for level metering while idle.

Opens an `sd.InputStream` on a chosen device and forwards each chunk to a
level callback. No buffering, no recording, no gain/mute — those live on
DualAudioCapture and are recording-scope. This monitor's only job is to
keep the meters alive so the user can verify their mic before pressing
Record. The monitor stops while a real recording is running so the
recorder can claim the device.
"""

import logging

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


class MicMonitor:
    def __init__(self, sample_rate=16000, channels=1, level_callback=None):
        self.sample_rate = sample_rate
        self.channels = channels
        self._level_callback = level_callback
        self._stream = None
        self._device_index = None
        self._gain = 1.0

    def set_gain(self, gain):
        """Set the gain multiplier applied before the level callback.

        Mirrors AudioStream's gain semantics so the meter during a Test Mic
        session reads the same dB as the eventual recording would.
        """
        self._gain = float(gain)

    def _callback(self, indata, frames, time_info, status):
        if status:
            logger.debug("Mic monitor status: %s", status)
        if self._level_callback is None:
            return
        # Detach from the device buffer before handing to the UI thread.
        chunk = indata.copy()
        if self._gain != 1.0:
            chunk *= self._gain
            np.clip(chunk, -1.0, 1.0, out=chunk)
        self._level_callback(chunk)

    def start(self, device_index):
        """Open a fresh stream on device_index. Safe to call when already running.

        A None device_index is treated as "no mic selected" and leaves the
        monitor stopped without raising.
        """
        self.stop()
        if device_index is None:
            return
        try:
            self._stream = sd.InputStream(
                device=device_index,
                samplerate=self.sample_rate,
                channels=self.channels,
                callback=self._callback,
                dtype="float32",
            )
            self._stream.start()
            self._device_index = device_index
            logger.info("Mic monitor started on device %s", device_index)
        except Exception as e:
            logger.warning("Mic monitor failed on device %s: %s", device_index, e)
            self._stream = None
            self._device_index = None

    def stop(self):
        """Close the current stream. Safe to call when already stopped."""
        if self._stream is None:
            return
        try:
            self._stream.stop()
            self._stream.close()
        except Exception as e:
            logger.debug("Mic monitor stop error: %s", e)
        finally:
            self._stream = None
            self._device_index = None

    @property
    def is_active(self):
        return self._stream is not None

    @property
    def device_index(self):
        return self._device_index
