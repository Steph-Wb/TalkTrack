"""DAW-style vertical level meters with peak hold, clip indicators, and gain slider."""

import time
from typing import Tuple

import numpy as np
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QSlider, QVBoxLayout, QWidget

from app.ui.level_meter import DB_FLOOR, compute_rms_db


# dB reference points shown as tick marks on the scale
DB_TICKS = [0, -6, -18, -40, -60]

# Peak/clip timing
PEAK_HOLD_SECONDS = 1.5
PEAK_DECAY_SECONDS = 0.5
CLIP_HOLD_SECONDS = 2.0
CLIP_THRESHOLD = 0.99

# Gain slider range (integer). Divide by 10 to get multiplier.
SLIDER_MIN = 5    # 0.5x
SLIDER_MAX = 50   # 5.0x
SLIDER_DEFAULT = 10  # 1.0x


def chunk_max_abs(chunk: np.ndarray) -> float:
    """Return the peak absolute sample value in a chunk."""
    if chunk.size == 0:
        return 0.0
    return float(np.max(np.abs(chunk)))


def is_clipping(chunk: np.ndarray) -> bool:
    """Return True if any sample in the chunk is at or above the clip threshold."""
    if chunk.size == 0:
        return False
    return bool(np.max(np.abs(chunk)) >= CLIP_THRESHOLD)


def peak_hold_value(
    current: float,
    peak: float,
    peak_ts: float,
    now: float,
    hold_seconds: float = PEAK_HOLD_SECONDS,
    decay_seconds: float = PEAK_DECAY_SECONDS,
) -> Tuple[float, float]:
    """Compute the new peak value and peak timestamp.

    If current >= peak: peak jumps to current, timestamp refreshed.
    Else within hold window: peak and timestamp unchanged.
    Else decaying: linear fall from peak to current over decay_seconds.
    """
    if current >= peak:
        return current, now
    elapsed = now - peak_ts
    if elapsed < hold_seconds:
        return peak, peak_ts
    decay_elapsed = elapsed - hold_seconds
    if decay_elapsed >= decay_seconds:
        return current, peak_ts
    frac = decay_elapsed / decay_seconds
    return peak - (peak - current) * frac, peak_ts


def slider_to_gain(slider_value: int) -> float:
    """Map integer slider value to float gain multiplier."""
    return slider_value / 10.0


def gain_to_slider(gain: float) -> int:
    """Map float gain multiplier to integer slider value, clamping to valid range."""
    return max(SLIDER_MIN, min(SLIDER_MAX, int(round(gain * 10))))


def _db_to_y(db: float, height: int) -> int:
    """Map a dB value to a y-coordinate (0 = top = 0dB, height = bottom = DB_FLOOR)."""
    if db >= 0:
        return 0
    if db <= DB_FLOOR:
        return height
    return int(height * (db / DB_FLOOR))


class _VerticalMeter(QWidget):
    """A single vertical level bar with color zones, peak hold, and clip LED."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(28)
        self.setMinimumHeight(100)
        self._db = DB_FLOOR
        self._peak_abs = 0.0  # absolute linear peak (0..1+)
        self._peak_ts = 0.0
        self._clip_ts = 0.0

    def update_from_chunk(self, chunk: np.ndarray):
        now = time.monotonic()
        self._db = compute_rms_db(chunk)
        current = chunk_max_abs(chunk)
        self._peak_abs, self._peak_ts = peak_hold_value(
            current, self._peak_abs, self._peak_ts, now,
        )
        if is_clipping(chunk):
            self._clip_ts = now

    def reset(self):
        self._db = DB_FLOOR
        self._peak_abs = 0.0
        self._peak_ts = 0.0
        self._clip_ts = 0.0
        self.update()

    def is_clipping(self) -> bool:
        return (time.monotonic() - self._clip_ts) < CLIP_HOLD_SECONDS

    @property
    def current_db(self) -> float:
        return self._db

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        w = self.width()
        h = self.height()

        # Background
        painter.fillRect(0, 0, w, h, QColor("#1e1e2e"))

        # Paint color zones top-to-bottom
        # -6 to 0 dB: red
        y_6 = _db_to_y(-6, h)
        painter.fillRect(0, 0, w, y_6, QColor("#f38ba8"))
        # -18 to -6 dB: yellow
        y_18 = _db_to_y(-18, h)
        painter.fillRect(0, y_6, w, y_18 - y_6, QColor("#f9e2af"))
        # -60 to -18 dB: green
        painter.fillRect(0, y_18, w, h - y_18, QColor("#a6e3a1"))

        # Overlay black over the empty region above the current level
        # (bar fills upward from the bottom, DAW-style)
        current_y = _db_to_y(self._db, h)
        if current_y > 0:
            painter.fillRect(0, 0, w, current_y, QColor("#1e1e2e"))

        # Peak hold line (bright, 3px)
        peak_db = 20.0 * float(np.log10(max(self._peak_abs, 1e-10)))
        peak_db = max(peak_db, DB_FLOOR)
        peak_y = _db_to_y(peak_db, h)
        if peak_y < h and self._peak_abs > 0.001:
            painter.setPen(QPen(QColor("#f5e0dc"), 3))
            peak_y_draw = min(peak_y, h - 2)
            painter.drawLine(0, peak_y_draw, w, peak_y_draw)

        # 0 dB clip line
        painter.setPen(QPen(QColor("#f38ba8"), 1))
        painter.drawLine(0, 0, w, 0)

        painter.end()


class _DbScale(QWidget):
    """Small vertical widget drawing dB tick labels next to meters."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(26)
        self.setMinimumHeight(100)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(0, 0, self.width(), self.height(), QColor("#1e1e2e"))

        font = QFont()
        font.setPixelSize(9)
        painter.setFont(font)
        painter.setPen(QColor("#a6adc8"))

        h = self.height()
        for db in DB_TICKS:
            y = _db_to_y(db, h)
            label = str(db)
            painter.drawText(0, y - 1, self.width() - 2, 10,
                             Qt.AlignmentFlag.AlignRight, label)
        painter.end()


class MetersPanel(QWidget):
    """DAW-style dual-channel meters with peak hold, clip indicators, and gain slider."""

    gain_changed = pyqtSignal(float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

        self._repaint_timer = QTimer(self)
        self._repaint_timer.timeout.connect(self._on_repaint_tick)
        self._repaint_timer.start(66)  # ~15fps

    def _setup_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 6, 8, 6)
        root.setSpacing(4)

        # Meter row: scale + mic meter + clip led + sys meter + clip led
        meter_row = QHBoxLayout()
        meter_row.setSpacing(6)

        meter_row.addStretch()

        self._scale = _DbScale()
        meter_row.addWidget(self._scale)

        # Mic column
        mic_col = QVBoxLayout()
        mic_col.setSpacing(2)
        mic_header = QHBoxLayout()
        mic_header.setSpacing(4)
        self._mic_clip_led = QLabel("\u25cf")  # filled circle
        self._mic_clip_led.setStyleSheet("color: #45475a; font-size: 12px;")
        self._mic_clip_led.setToolTip("Clip indicator - lights red on clipping")
        mic_header.addWidget(self._mic_clip_led)
        mic_header.addStretch()
        mic_col.addLayout(mic_header)

        self._mic_meter = _VerticalMeter()
        mic_col.addWidget(self._mic_meter, 0, Qt.AlignmentFlag.AlignHCenter)

        self._mic_db_label = QLabel("-- dB")
        self._mic_db_label.setStyleSheet("color: #cdd6f4; font-size: 10px;")
        self._mic_db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mic_col.addWidget(self._mic_db_label)

        mic_title = QLabel("MIC")
        mic_title.setStyleSheet("color: #a6adc8; font-size: 10px; font-weight: bold;")
        mic_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mic_col.addWidget(mic_title)

        meter_row.addLayout(mic_col)
        meter_row.addSpacing(8)

        # Sys column
        sys_col = QVBoxLayout()
        sys_col.setSpacing(2)
        sys_header = QHBoxLayout()
        sys_header.setSpacing(4)
        self._sys_clip_led = QLabel("\u25cf")
        self._sys_clip_led.setStyleSheet("color: #45475a; font-size: 12px;")
        self._sys_clip_led.setToolTip("Clip indicator - lights red on clipping")
        sys_header.addWidget(self._sys_clip_led)
        sys_header.addStretch()
        sys_col.addLayout(sys_header)

        self._sys_meter = _VerticalMeter()
        sys_col.addWidget(self._sys_meter, 0, Qt.AlignmentFlag.AlignHCenter)

        self._sys_db_label = QLabel("-- dB")
        self._sys_db_label.setStyleSheet("color: #cdd6f4; font-size: 10px;")
        self._sys_db_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sys_col.addWidget(self._sys_db_label)

        sys_title = QLabel("SYS")
        sys_title.setStyleSheet("color: #a6adc8; font-size: 10px; font-weight: bold;")
        sys_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sys_col.addWidget(sys_title)

        meter_row.addLayout(sys_col)
        meter_row.addStretch()

        root.addLayout(meter_row)

        # Gain slider row
        gain_row = QHBoxLayout()
        gain_row.setSpacing(6)
        gain_label = QLabel("Mic Gain:")
        gain_label.setStyleSheet("color: #a6adc8; font-size: 11px;")
        gain_row.addWidget(gain_label)

        self._gain_slider = QSlider(Qt.Orientation.Horizontal)
        self._gain_slider.setRange(SLIDER_MIN, SLIDER_MAX)
        self._gain_slider.setValue(SLIDER_DEFAULT)
        self._gain_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self._gain_slider.setTickInterval(5)
        self._gain_slider.setToolTip(
            "Boost microphone volume.\n1.0x = no change.\n"
            "Higher values are hard-clipped to prevent distortion."
        )
        self._gain_slider.valueChanged.connect(self._on_slider_changed)
        gain_row.addWidget(self._gain_slider, 1)

        self._gain_readout = QLabel("1.0x")
        self._gain_readout.setStyleSheet(
            "color: #cdd6f4; font-size: 11px; min-width: 34px;"
        )
        self._gain_readout.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        gain_row.addWidget(self._gain_readout)

        root.addLayout(gain_row)

    # --- Audio update hooks (called from MainWindow) ---

    def update_mic_level(self, chunk: np.ndarray):
        self._mic_meter.update_from_chunk(chunk)

    def update_system_level(self, chunk: np.ndarray):
        self._sys_meter.update_from_chunk(chunk)

    def reset(self):
        self._mic_meter.reset()
        self._sys_meter.reset()
        self._mic_db_label.setText("-- dB")
        self._sys_db_label.setText("-- dB")
        self._set_clip_led(self._mic_clip_led, False)
        self._set_clip_led(self._sys_clip_led, False)

    # --- Gain ---

    def set_gain(self, gain: float):
        """Set slider value from a float gain. Does NOT emit gain_changed."""
        slider_val = gain_to_slider(float(gain))
        self._gain_slider.blockSignals(True)
        self._gain_slider.setValue(slider_val)
        self._gain_slider.blockSignals(False)
        self._gain_readout.setText(f"{slider_to_gain(slider_val):.1f}x")

    def _on_slider_changed(self, value: int):
        gain = slider_to_gain(value)
        self._gain_readout.setText(f"{gain:.1f}x")
        self.gain_changed.emit(gain)

    # --- Repaint tick ---

    def _on_repaint_tick(self):
        self._mic_meter.update()
        self._sys_meter.update()
        self._mic_db_label.setText(f"{self._mic_meter.current_db:.0f} dB")
        self._sys_db_label.setText(f"{self._sys_meter.current_db:.0f} dB")
        self._set_clip_led(self._mic_clip_led, self._mic_meter.is_clipping())
        self._set_clip_led(self._sys_clip_led, self._sys_meter.is_clipping())

    def _set_clip_led(self, label: QLabel, active: bool):
        if active:
            label.setStyleSheet("color: #f38ba8; font-size: 12px;")
        else:
            label.setStyleSheet("color: #45475a; font-size: 12px;")
