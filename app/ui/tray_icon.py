"""System tray icon for TalkTrack.

Pure helpers are module-level and unit-testable. The Qt widget class (TrayIcon)
comes in a later task and will compose them with QSystemTrayIcon.
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
