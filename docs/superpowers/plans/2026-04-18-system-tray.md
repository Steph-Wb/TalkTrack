# System Tray Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let TalkTrack minimize to the Windows system tray (configurable) and always-confirm on close (X). Tray icon gets a state-aware menu, tooltip, and colored overlay dots for success/error notifications while hidden.

**Architecture:** New `TrayIcon` widget wraps `QSystemTrayIcon` and owns base icon + overlay compositing + menu + action visibility. `MainWindow` overrides `changeEvent` and `closeEvent` to drive tray behavior. Popup suppression: when `isHidden()` is true, specific `QMessageBox` sites are swapped for tray overlays.

**Tech Stack:** Python 3, PyQt6, unittest + pytest.

**Spec:** `docs/superpowers/specs/2026-04-18-system-tray-design.md`

---

## File Structure

| File | Change | Responsibility |
|---|---|---|
| `app/utils/config.py` | modify | Add `general.minimize_to_tray` and `general.show_tray_hint` defaults |
| `app/ui/tray_icon.py` | **new** | `TrayIcon` widget + pure helpers (`format_tray_tooltip`, `tray_action_visibility`, `resolve_overlay`) |
| `app/ui/settings_dialog.py` | modify | Add "When minimized, hide to system tray" checkbox under General > Recording |
| `app/main_window.py` | modify | Instantiate tray, `changeEvent`, `closeEvent` rewrite, state→tray sync, popup suppression |
| `tests/test_tray_icon.py` | **new** | Unit tests for the pure helpers |

---

## Task 1: Config defaults

**Files:**
- Modify: `app/utils/config.py`

- [ ] **Step 1:** In `DEFAULT_CONFIG["general"]` (currently ending with `"silence_duration": 30`), add two keys:

```python
    "general": {
        "min_recording_length": 5,
        "auto_record": False,
        "silence_auto_stop": True,
        "silence_duration": 30,
        "minimize_to_tray": False,
        "show_tray_hint": True,
    },
```

- [ ] **Step 2:** Verify:

```bash
python -c "from app.utils.config import Config; c = Config(); print(c.get('general', 'minimize_to_tray'), c.get('general', 'show_tray_hint'))"
```

Expected: `False True`

- [ ] **Step 3:** Commit:

```bash
git add app/utils/config.py
git commit -m "config: add general.minimize_to_tray and show_tray_hint defaults"
```

---

## Task 2: Pure helpers — failing tests

**Files:**
- Test: `tests/test_tray_icon.py` (new)

- [ ] **Step 1:** Create `tests/test_tray_icon.py` with:

```python
"""Unit tests for tray icon pure helpers."""
import unittest

from app.ui.tray_icon import (
    format_tray_tooltip,
    tray_action_visibility,
    resolve_overlay,
)
from app.recording.recorder import RecordingState


class TestFormatTrayTooltip(unittest.TestCase):
    def test_idle_returns_plain_name(self):
        self.assertEqual(format_tray_tooltip(RecordingState.IDLE, 0), "TalkTrack")

    def test_recording_shows_elapsed(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.RECORDING, 754),
            "TalkTrack \u2014 Recording 00:12:34",
        )

    def test_paused_shows_elapsed(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.PAUSED, 65),
            "TalkTrack \u2014 Paused 00:01:05",
        )

    def test_stopping_falls_back_to_idle_form(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.STOPPING, 0), "TalkTrack"
        )

    def test_long_duration_hours(self):
        self.assertEqual(
            format_tray_tooltip(RecordingState.RECORDING, 3661),
            "TalkTrack \u2014 Recording 01:01:01",
        )


class TestTrayActionVisibility(unittest.TestCase):
    def test_idle_shows_record_only(self):
        vis = tray_action_visibility(RecordingState.IDLE)
        self.assertTrue(vis["record"])
        self.assertFalse(vis["pause"])
        self.assertFalse(vis["resume"])
        self.assertFalse(vis["stop"])

    def test_recording_shows_pause_and_stop(self):
        vis = tray_action_visibility(RecordingState.RECORDING)
        self.assertFalse(vis["record"])
        self.assertTrue(vis["pause"])
        self.assertFalse(vis["resume"])
        self.assertTrue(vis["stop"])

    def test_paused_shows_resume_and_stop(self):
        vis = tray_action_visibility(RecordingState.PAUSED)
        self.assertFalse(vis["record"])
        self.assertFalse(vis["pause"])
        self.assertTrue(vis["resume"])
        self.assertTrue(vis["stop"])

    def test_stopping_shows_nothing(self):
        vis = tray_action_visibility(RecordingState.STOPPING)
        self.assertFalse(vis["record"])
        self.assertFalse(vis["pause"])
        self.assertFalse(vis["resume"])
        self.assertFalse(vis["stop"])


class TestResolveOverlay(unittest.TestCase):
    """resolve_overlay(has_success, has_error) returns None | 'green' | 'red'."""

    def test_nothing_pending_returns_none(self):
        self.assertIsNone(resolve_overlay(False, False))

    def test_success_returns_green(self):
        self.assertEqual(resolve_overlay(True, False), "green")

    def test_error_returns_red(self):
        self.assertEqual(resolve_overlay(False, True), "red")

    def test_error_wins_when_both(self):
        self.assertEqual(resolve_overlay(True, True), "red")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2:** Verify tests fail:

```bash
python -m pytest tests/test_tray_icon.py -v
```

Expected: All 13 tests FAIL with `ImportError` / `ModuleNotFoundError` because `app/ui/tray_icon.py` doesn't exist yet.

---

## Task 3: Pure helpers — implementation

**Files:**
- New: `app/ui/tray_icon.py`

- [ ] **Step 1:** Create `app/ui/tray_icon.py` with ONLY the pure helpers for now (Qt-dependent `TrayIcon` class comes in Task 4):

```python
"""System tray icon for TalkTrack.

Pure helpers are module-level and unit-testable. The Qt widget class below
(`TrayIcon`) composes them with QSystemTrayIcon.
"""
from app.recording.recorder import RecordingState


def format_tray_tooltip(state, elapsed_seconds):
    """Build the tray icon tooltip for a given recording state and elapsed time."""
    if state == RecordingState.RECORDING:
        return f"TalkTrack \u2014 Recording {_format_elapsed(elapsed_seconds)}"
    if state == RecordingState.PAUSED:
        return f"TalkTrack \u2014 Paused {_format_elapsed(elapsed_seconds)}"
    return "TalkTrack"


def _format_elapsed(seconds):
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def tray_action_visibility(state):
    """Map of tray menu action visibility keyed by action name.

    Returns dict with keys: record, pause, resume, stop.
    """
    return {
        "record": state == RecordingState.IDLE,
        "pause": state == RecordingState.RECORDING,
        "resume": state == RecordingState.PAUSED,
        "stop": state in (RecordingState.RECORDING, RecordingState.PAUSED),
    }


def resolve_overlay(has_success, has_error):
    """Overlay color for pending notifications. Errors win over successes."""
    if has_error:
        return "red"
    if has_success:
        return "green"
    return None
```

- [ ] **Step 2:** Verify tests pass:

```bash
python -m pytest tests/test_tray_icon.py -v
```

Expected: All 13 tests PASS.

- [ ] **Step 3:** Full suite still green:

```bash
python -m pytest tests/ -v 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 4:** Commit:

```bash
git add app/ui/tray_icon.py tests/test_tray_icon.py
git commit -m "ui: add pure tray-icon helpers (tooltip, action visibility, overlay resolver)"
```

---

## Task 4: `TrayIcon` Qt widget

**Files:**
- Modify: `app/ui/tray_icon.py`

- [ ] **Step 1:** Append the `TrayIcon` class to `app/ui/tray_icon.py`. Uses `resources/talktrack.ico` as base icon. Supports overlay compositing, menu building, state-aware action visibility, and balloon.

Add these imports at the top of the file:

```python
from pathlib import Path

from PyQt6.QtCore import pyqtSignal, QObject, Qt
from PyQt6.QtGui import QAction, QColor, QIcon, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
```

Append the class:

```python
_ICON_PATH = Path(__file__).parent.parent.parent / "resources" / "talktrack.ico"

_DOT_COLORS = {
    "green": QColor("#a6e3a1"),
    "red": QColor("#f38ba8"),
}


class TrayIcon(QObject):
    """System tray icon wrapper.

    Emits signals for menu actions; owner (MainWindow) wires them to the
    same slots as the main recording controls.
    """

    show_requested = pyqtSignal()
    record_requested = pyqtSignal()
    pause_requested = pyqtSignal()
    resume_requested = pyqtSignal()
    stop_requested = pyqtSignal()
    quit_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._base_icon = QIcon(str(_ICON_PATH))
        self._current_overlay = None  # None | "green" | "red"

        self._tray = QSystemTrayIcon(self._base_icon, parent)
        self._tray.setToolTip("TalkTrack")
        self._tray.activated.connect(self._on_activated)

        self._menu = QMenu()
        self._action_show = QAction("Show TalkTrack", self._menu)
        self._action_show.triggered.connect(self.show_requested)
        self._menu.addAction(self._action_show)
        self._menu.addSeparator()

        self._action_record = QAction("Record", self._menu)
        self._action_record.triggered.connect(self.record_requested)
        self._action_pause = QAction("Pause", self._menu)
        self._action_pause.triggered.connect(self.pause_requested)
        self._action_resume = QAction("Resume", self._menu)
        self._action_resume.triggered.connect(self.resume_requested)
        self._action_stop = QAction("Stop", self._menu)
        self._action_stop.triggered.connect(self.stop_requested)
        for a in (self._action_record, self._action_pause, self._action_resume, self._action_stop):
            self._menu.addAction(a)

        self._menu.addSeparator()
        self._action_quit = QAction("Quit", self._menu)
        self._action_quit.triggered.connect(self.quit_requested)
        self._menu.addAction(self._action_quit)

        self._tray.setContextMenu(self._menu)
        self.set_state(RecordingState.IDLE, 0)

    def is_supported(self):
        return QSystemTrayIcon.isSystemTrayAvailable()

    def show(self):
        self._tray.show()

    def hide(self):
        self._tray.hide()

    def set_state(self, state, elapsed_seconds):
        """Update tooltip and menu visibility for the current recording state."""
        self._tray.setToolTip(format_tray_tooltip(state, elapsed_seconds))
        vis = tray_action_visibility(state)
        self._action_record.setVisible(vis["record"])
        self._action_pause.setVisible(vis["pause"])
        self._action_resume.setVisible(vis["resume"])
        self._action_stop.setVisible(vis["stop"])

    def set_overlay(self, color):
        """Apply an overlay dot. color in {None, 'green', 'red'}."""
        if color == self._current_overlay:
            return
        self._current_overlay = color
        if color is None:
            self._tray.setIcon(self._base_icon)
        else:
            self._tray.setIcon(self._compose_icon_with_dot(_DOT_COLORS[color]))

    def show_hint_balloon(self):
        """One-time welcome balloon shown on first tray hide."""
        self._tray.showMessage(
            "TalkTrack is still running",
            "Right-click the tray icon for options. Disable this in Settings > General.",
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

    def _on_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def _compose_icon_with_dot(self, color):
        """Return a QIcon with a colored dot overlaid on the base icon."""
        size = 64
        pixmap = self._base_icon.pixmap(size, size)
        canvas = QPixmap(pixmap)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        diameter = int(size * 0.4)
        margin = 2
        x = size - diameter - margin
        y = size - diameter - margin
        painter.setPen(QPen(QColor("#1e1e2e"), 1))
        painter.setBrush(color)
        painter.drawEllipse(x, y, diameter, diameter)
        painter.end()
        return QIcon(canvas)
```

- [ ] **Step 2:** Smoke-test the class instantiates offscreen:

```bash
python -c "
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication
from app.ui.tray_icon import TrayIcon
from app.recording.recorder import RecordingState
app = QApplication(sys.argv)
tray = TrayIcon()
tray.set_state(RecordingState.RECORDING, 125)
tray.set_overlay('green')
tray.set_overlay('red')
tray.set_overlay(None)
print('tray widget ok, supported:', tray.is_supported())
"
```

Expected: prints `tray widget ok, supported: ...` (True or False depending on environment). No exceptions.

- [ ] **Step 3:** Commit:

```bash
git add app/ui/tray_icon.py
git commit -m "ui: add TrayIcon widget with overlay dots, state-aware menu, and hint balloon"
```

---

## Task 5: Settings dialog — "hide to tray" checkbox

**Files:**
- Modify: `app/ui/settings_dialog.py`

- [ ] **Step 1:** In `_setup_ui`, inside the General tab's `recording_form` (after `self.mic_mute_on_start_cb`), add:

```python
        self.minimize_to_tray_cb = QCheckBox("When minimized, hide to system tray")
        self.minimize_to_tray_cb.setToolTip(
            "Keeps TalkTrack out of the taskbar when minimized.\n"
            "Right-click the tray icon to restore or stop recording."
        )
        recording_form.addRow(self.minimize_to_tray_cb)
```

- [ ] **Step 2:** In `_load_settings` (near the other general loads around line 340-345), add:

```python
        self.minimize_to_tray_cb.setChecked(self.config.get("general", "minimize_to_tray"))
```

- [ ] **Step 3:** In the save path (near line 428-430), add:

```python
        self.config.set("general", "minimize_to_tray", self.minimize_to_tray_cb.isChecked())
```

- [ ] **Step 4:** Smoke test:

```bash
python -c "
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication
from app.utils.config import Config
from app.ui.settings_dialog import SettingsDialog
app = QApplication(sys.argv)
d = SettingsDialog(Config())
print('minimize_to_tray_cb exists:', hasattr(d, 'minimize_to_tray_cb'))
print('initial value:', d.minimize_to_tray_cb.isChecked())
"
```

Expected: `minimize_to_tray_cb exists: True` and `initial value: False`.

- [ ] **Step 5:** Commit:

```bash
git add app/ui/settings_dialog.py
git commit -m "settings: add hide-to-tray checkbox under General > Recording"
```

---

## Task 6: Instantiate tray icon in MainWindow

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1:** Add import near the top (with other `app.ui.*` imports):

```python
from app.ui.tray_icon import TrayIcon
```

- [ ] **Step 2:** In `MainWindow.__init__`, after `_setup_ui()` but before the existing connect wiring, add:

```python
        self._really_quit = False
        self._success_pending = False
        self._error_pending = False

        self.tray = TrayIcon(self)
        if self.tray.is_supported():
            self.tray.show()
            self.tray.show_requested.connect(self._restore_from_tray)
            self.tray.record_requested.connect(self._start_recording)
            self.tray.pause_requested.connect(self._toggle_pause)
            self.tray.resume_requested.connect(self._toggle_pause)
            self.tray.stop_requested.connect(self._stop_recording)
            self.tray.quit_requested.connect(self._quit_from_tray)
        else:
            import logging
            logging.getLogger("talktrack").warning(
                "System tray not available; minimize-to-tray is disabled."
            )
```

- [ ] **Step 3:** Add new methods on `MainWindow` (near `_open_settings`, after other tray-adjacent methods):

```python
    def _restore_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._success_pending = False
        self._error_pending = False
        self.tray.set_overlay(None)

    def _quit_from_tray(self):
        # Same confirmation as X button; close() triggers closeEvent.
        self.close()
```

- [ ] **Step 4:** Smoke-test MainWindow still boots:

```bash
python -c "
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication
from app.main_window import MainWindow
app = QApplication(sys.argv)
w = MainWindow()
print('tray wired:', w.tray is not None)
print('tray supported:', w.tray.is_supported())
"
```

Expected: `tray wired: True`, no exceptions.

- [ ] **Step 5:** Commit:

```bash
git add app/main_window.py
git commit -m "ui: instantiate tray icon in MainWindow and wire menu signals"
```

---

## Task 7: `changeEvent` — minimize-to-tray

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1:** Add `changeEvent` override on `MainWindow` (near `closeEvent`, just before it):

```python
    def changeEvent(self, event):
        from PyQt6.QtCore import QEvent, Qt
        if event.type() == QEvent.Type.WindowStateChange:
            if self.windowState() & Qt.WindowState.WindowMinimized:
                if self.config.get("general", "minimize_to_tray") and self.tray.is_supported():
                    # Reset state so next showNormal opens at normal size.
                    self.setWindowState(Qt.WindowState.WindowNoState)
                    self.hide()
                    if self.config.get("general", "show_tray_hint"):
                        self.tray.show_hint_balloon()
                        self.config.set("general", "show_tray_hint", False)
                    event.accept()
                    return
        super().changeEvent(event)
```

- [ ] **Step 2:** Manual test plan (document for yourself, no automated smoke test possible for WindowStateChange):

```
1. python main.py
2. Toggle Settings > General > "When minimized, hide to system tray" on. Save.
3. Click minimize. Window should vanish, balloon should appear.
4. Right-click tray icon, click "Show TalkTrack". Window should restore.
5. Click minimize again. Window vanishes, NO balloon this time.
6. Toggle setting off. Minimize goes to taskbar.
```

- [ ] **Step 3:** Commit:

```bash
git add app/main_window.py
git commit -m "ui: minimize-to-tray via changeEvent, with one-time welcome balloon"
```

---

## Task 8: `closeEvent` — always confirm + unified quit path

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1:** Replace the existing `closeEvent` (lines ~947-968) with:

```python
    def closeEvent(self, event):
        if not self._really_quit:
            if not self._confirm_exit():
                event.ignore()
                return
            self._really_quit = True

        if self._gain_save_timer.isActive():
            self._gain_save_timer.stop()
            self._flush_gain_to_config()
        if self.recorder.state != RecordingState.IDLE:
            self.recorder.stop_recording()
        self.config.save()
        if hasattr(self, "tray"):
            self.tray.hide()
        event.accept()

    def _confirm_exit(self):
        """Show the exit-confirmation dialog. Returns True if user wants to quit."""
        if self.recorder.state != RecordingState.IDLE:
            body = (
                "A recording is in progress. Exiting will stop and save "
                "the current recording. Continue?"
            )
        else:
            body = "Are you sure you want to exit?"
        reply = QMessageBox.question(
            self,
            "Exit TalkTrack?",
            body,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        return reply == QMessageBox.StandardButton.Yes
```

- [ ] **Step 2:** Smoke-test: instantiate MainWindow and verify the new `_confirm_exit` exists:

```bash
python -c "
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication
from app.main_window import MainWindow
app = QApplication(sys.argv)
w = MainWindow()
print('has _confirm_exit:', hasattr(w, '_confirm_exit'))
print('has _really_quit:', w._really_quit is False)
"
```

Expected: both `True`.

- [ ] **Step 3:** Manual verification:

```
1. Launch app. Click X → confirmation dialog. Cancel → stays. Yes → quits.
2. Launch, start a recording, click X → dialog says "recording in progress". Yes → stops recording and quits.
3. Launch, enable hide-to-tray, minimize, right-click tray → Quit → confirmation pops, Yes quits cleanly.
```

- [ ] **Step 4:** Commit:

```bash
git add app/main_window.py
git commit -m "ui: always-confirm close (X) with unified quit path for tray Quit"
```

---

## Task 9: Sync tray state from recording state and timer

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1:** In `_on_state_changed` (after `self.recording_controls.set_state(state)`), add:

```python
        if hasattr(self, "tray") and self.tray.is_supported():
            self.tray.set_state(state, self._recording_elapsed_seconds())
```

- [ ] **Step 2:** Add a helper to compute elapsed seconds from the existing recording clock. Locate the recording timer label (e.g. `self.recording_controls.timer_label`) and check whether it exposes a numeric value. If not, read from `self.recorder`:

```python
    def _recording_elapsed_seconds(self):
        """Seconds elapsed on the current recording, 0 if idle."""
        # Recorder tracks start time internally; recording_controls displays it.
        # Use whichever source already exists — check RecordingControls for the
        # attribute name during implementation (likely `_elapsed_seconds` or
        # similar on the timer). Fall back to 0.
        rc = getattr(self, "recording_controls", None)
        if rc is None:
            return 0
        val = getattr(rc, "elapsed_seconds", None)
        return int(val) if isinstance(val, (int, float)) else 0
```

If `RecordingControls` doesn't expose elapsed seconds yet, add a lightweight `elapsed_seconds` property on `RecordingControls` that returns the integer seconds its timer shows (parse the label or track internally). Do this as the smallest addition possible — don't refactor the existing timer.

- [ ] **Step 3:** Update tray tooltip on every recording-clock tick. Find where the timer increments (probably inside `RecordingControls._update_timer` or similar). Emit a signal or call a method on `MainWindow`. Simplest: connect to an existing tick signal if one exists, else add a `tick = pyqtSignal()` to `RecordingControls`, connected to `self._on_recording_tick` on `MainWindow`:

```python
    def _on_recording_tick(self):
        if hasattr(self, "tray") and self.tray.is_supported():
            self.tray.set_state(self.recorder.state, self._recording_elapsed_seconds())
```

- [ ] **Step 4:** Smoke-test the new wiring:

```bash
python -c "
import os, sys
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PyQt6.QtWidgets import QApplication
from app.main_window import MainWindow
app = QApplication(sys.argv)
w = MainWindow()
print('elapsed helper:', w._recording_elapsed_seconds())
"
```

Expected: `elapsed helper: 0` when idle.

- [ ] **Step 5:** Commit:

```bash
git add app/main_window.py app/ui/recording_controls.py
git commit -m "ui: sync tray tooltip and menu with recording state and elapsed time"
```

---

## Task 10: Suppress popups and set overlay when hidden

**Files:**
- Modify: `app/main_window.py`

- [ ] **Step 1:** Add a helper method:

```python
    def _is_hidden_to_tray(self):
        return hasattr(self, "tray") and self.tray.is_supported() and self.isHidden()

    def _flag_error_notification(self):
        self._error_pending = True
        from app.ui.tray_icon import resolve_overlay
        self.tray.set_overlay(resolve_overlay(self._success_pending, self._error_pending))

    def _flag_success_notification(self):
        self._success_pending = True
        from app.ui.tray_icon import resolve_overlay
        self.tray.set_overlay(resolve_overlay(self._success_pending, self._error_pending))
```

- [ ] **Step 2:** Update the three background-triggered popup sites to suppress when hidden. Each edit below replaces the existing `QMessageBox.*` call.

**In `_on_diarization_error` (near line 545):**

```python
        if self._is_hidden_to_tray():
            self._flag_error_notification()
        else:
            QMessageBox.warning(self, "Diarization Error", error_msg)
```

**In `_on_transcription_error` (near line 586):**

```python
        if self._is_hidden_to_tray():
            self._flag_error_notification()
        else:
            QMessageBox.warning(self, "Transcription Error", error_msg)
```

**In `_on_error` (near line 751):**

```python
        if self._is_hidden_to_tray():
            self._flag_error_notification()
        else:
            QMessageBox.critical(self, "Error", error_msg)
```

- [ ] **Step 3:** Flag successful transcription completion when hidden. In `_display_final_transcript` (after `self.status_label.setText("Transcription complete.")`, around line 562), add:

```python
        if self._is_hidden_to_tray():
            self._flag_success_notification()
```

- [ ] **Step 4:** Manual verification:

```
1. Launch, enable hide-to-tray, start a recording, minimize to tray.
2. Stop recording via tray menu → let transcription complete.
3. Tray icon should show a GREEN dot.
4. Restore window → GREEN dot clears (handled by _restore_from_tray already).
5. Force an error path (e.g. disable network + configure cloud AI summary) and repeat → RED dot.
```

- [ ] **Step 5:** Run full test suite for regressions:

```bash
python -m pytest tests/ -v 2>&1 | tail -5
```

Expected: all tests pass.

- [ ] **Step 6:** Commit:

```bash
git add app/main_window.py
git commit -m "ui: suppress popups while hidden to tray; show overlay dots instead"
```

---

## Task 11: Final verification

- [ ] **Step 1:** Run the full suite:

```bash
python -m pytest tests/ -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 2:** Manual end-to-end:

1. Launch. Confirm tray icon appears. Tooltip = `TalkTrack`.
2. Enable "When minimized, hide to system tray" in Settings. Save.
3. Click minimize → window vanishes, balloon appears once ("TalkTrack is still running").
4. Right-click tray → context menu shows: `Show TalkTrack`, separator, `Record`, separator, `Quit`. (Record visible because idle.)
5. Click `Record` → recording starts. Tray tooltip shows elapsed time. Menu now shows `Pause` and `Stop`.
6. Click `Pause` in tray menu → recording pauses. Menu shows `Resume` and `Stop`.
7. Click `Resume` → recording continues.
8. Click `Stop` in tray → recording stops. Transcription runs silently. When it completes, green dot appears on tray icon.
9. Double-click tray icon → window restores, green dot clears.
10. Click X → confirmation dialog. Cancel stays. Yes quits cleanly.
11. Relaunch, verify tray hint balloon does NOT reappear (already shown once).

- [ ] **Step 3:** Final push:

```bash
git push origin master
```

- [ ] **Step 4:** Mark plan task complete.

---

## Notes for implementer

- **Use superpowers:subagent-driven-development.** Tasks 1-10 are independent commits; dispatch fresh subagents with the full task text. TDD pairs (Task 2 + Task 3) can be one dispatch, one commit per task.
- **Don't batch pause/resume logic rework.** The existing `_toggle_pause` handler already toggles pause/resume based on state — the tray `pause_requested` and `resume_requested` both connect to it intentionally.
- **No Co-Authored-By trailers** on commits (see `feedback_no_coauthor.md` memory).
- **Commit per task.** Do not consolidate into a single mega-commit.
- **Popup audit is complete.** If you find another site during implementation, it's likely user-initiated (menu action with visible window) and does not need suppression. Flag to human if unsure.
