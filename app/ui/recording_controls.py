from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QPushButton, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

from app.recording.recorder import RecordingState


class RecordingControls(QWidget):
    """Recording control buttons and timer — compact two-row layout.

    Row 1: [● Rec] [⏸ Pause] [■ Stop] [🎤 Mute]
    Row 2: ● 00:12:34
    """

    record_clicked = pyqtSignal()
    pause_clicked = pyqtSignal()
    stop_clicked = pyqtSignal()
    mute_clicked = pyqtSignal()
    # Emitted when the user toggles the Test Mic button. True = enable live
    # mic monitor (no recording); False = disable. Off by default every launch.
    test_mic_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._muted = False
        self._blink_state = True
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._toggle_indicator)
        self.set_state(RecordingState.IDLE)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 4, 0, 4)
        layout.setSpacing(4)

        # Row 1: Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(6)

        self.record_btn = QPushButton("\u25cf Rec")
        self.record_btn.setObjectName("recordButton")
        self.record_btn.clicked.connect(self.record_clicked.emit)
        btn_row.addWidget(self.record_btn)

        self.pause_btn = QPushButton("\u23f8 Pause")
        self.pause_btn.setObjectName("pauseButton")
        self.pause_btn.clicked.connect(self.pause_clicked.emit)
        btn_row.addWidget(self.pause_btn)

        self.stop_btn = QPushButton("\u25a0 Stop")
        self.stop_btn.setObjectName("stopButton")
        self.stop_btn.clicked.connect(self.stop_clicked.emit)
        btn_row.addWidget(self.stop_btn)

        self.mute_btn = QPushButton("\U0001f3a4 Mute")
        self.mute_btn.setObjectName("muteButton")
        self.mute_btn.setToolTip(
            "Mute the microphone while keeping system/app audio recording."
        )
        self.mute_btn.clicked.connect(self.mute_clicked.emit)
        btn_row.addWidget(self.mute_btn)

        self.test_mic_btn = QPushButton("\U0001f399 Test")
        self.test_mic_btn.setObjectName("testMicButton")
        self.test_mic_btn.setCheckable(True)
        self.test_mic_btn.setToolTip(
            "Open the mic and drive the meters without recording. "
            "Resets off every launch."
        )
        self.test_mic_btn.toggled.connect(self._update_test_mic_style)
        self.test_mic_btn.toggled.connect(self.test_mic_toggled.emit)
        btn_row.addWidget(self.test_mic_btn)

        layout.addLayout(btn_row)

        # Row 2: Indicator + timer
        status_row = QHBoxLayout()
        status_row.setSpacing(6)

        self.recording_indicator = QLabel("")
        self.recording_indicator.setObjectName("recordingIndicator")
        self.recording_indicator.setFixedWidth(14)
        self.recording_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        status_row.addWidget(self.recording_indicator)

        self.timer_label = QLabel("00:00:00")
        self.timer_label.setObjectName("timerLabel")
        status_row.addWidget(self.timer_label)

        status_row.addStretch()

        layout.addLayout(status_row)

    def set_state(self, state):
        if state == RecordingState.IDLE:
            self.record_btn.setEnabled(True)
            self.record_btn.setText("\u25cf Rec")
            self.pause_btn.setEnabled(False)
            self.pause_btn.setText("\u23f8 Pause")
            self.stop_btn.setEnabled(False)
            self.mute_btn.setEnabled(False)
            self.set_muted(False)
            self.test_mic_btn.setEnabled(True)
            self.recording_indicator.setText("")
            self._blink_timer.stop()
        elif state == RecordingState.RECORDING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("\u23f8 Pause")
            self.stop_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.test_mic_btn.setEnabled(False)
            self._blink_timer.start(500)
        elif state == RecordingState.PAUSED:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(True)
            self.pause_btn.setText("\u25b6 Resume")
            self.stop_btn.setEnabled(True)
            self.mute_btn.setEnabled(True)
            self.test_mic_btn.setEnabled(False)
            self.recording_indicator.setText("\u23f8")
            self._blink_timer.stop()
        elif state == RecordingState.STOPPING:
            self.record_btn.setEnabled(False)
            self.pause_btn.setEnabled(False)
            self.stop_btn.setEnabled(False)
            self.mute_btn.setEnabled(False)
            self.test_mic_btn.setEnabled(False)
            self.recording_indicator.setText("")
            self._blink_timer.stop()

    def update_time(self, seconds):
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        self.timer_label.setText(f"{h:02d}:{m:02d}:{s:02d}")

    def _update_test_mic_style(self, checked):
        if checked:
            self.test_mic_btn.setText("\U0001f399 Testing")
            self.test_mic_btn.setStyleSheet(
                "QPushButton#testMicButton { "
                "background-color: #a6e3a1; color: #1e1e2e; "
                "border: 1px solid #a6e3a1; font-weight: bold; }"
            )
        else:
            self.test_mic_btn.setText("\U0001f399 Test")
            self.test_mic_btn.setStyleSheet("")

    def clear_test_mic(self):
        """Uncheck the Test Mic button without emitting test_mic_toggled.

        Used when MainWindow has already torn down the monitor (e.g. before
        starting a recording) and just needs the visual state to match.
        """
        self.test_mic_btn.blockSignals(True)
        self.test_mic_btn.setChecked(False)
        self.test_mic_btn.blockSignals(False)
        self._update_test_mic_style(False)

    def set_muted(self, muted):
        """Update the mute button visual state."""
        self._muted = bool(muted)
        if self._muted:
            self.mute_btn.setText("\U0001f3a4 Muted")
            self.mute_btn.setStyleSheet(
                "QPushButton#muteButton { "
                "background-color: #f38ba8; color: #1e1e2e; "
                "border: 1px solid #f38ba8; font-weight: bold; }"
            )
        else:
            self.mute_btn.setText("\U0001f3a4 Mute")
            self.mute_btn.setStyleSheet("")

    def _toggle_indicator(self):
        self._blink_state = not self._blink_state
        self.recording_indicator.setText("\u25cf" if self._blink_state else "")

    def reset_timer(self):
        self.timer_label.setText("00:00:00")
