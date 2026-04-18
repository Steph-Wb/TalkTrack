# System Tray — Design

Date: 2026-04-18

## Overview

Let TalkTrack run quietly while a long meeting is in progress by hiding the main window to the Windows system tray. The minimize button becomes a "send to tray" action (configurable), the close button always quits after a confirmation dialog, and a tray icon provides restore access plus at-a-glance state via colored overlay dots.

Primary goal: reduce taskbar clutter during multi-hour meetings without disrupting recording or transcription.

## Non-Goals

- **No "start minimized to tray."** App always launches visible.
- **No auto-start-on-login integration.** Separate feature.
- **No balloon notifications for completion.** Only the first-minimize welcome balloon uses a Windows notification; everything else uses the tray icon overlay.
- **No tray control of settings.** Tray menu exposes record/pause/stop/quit only. Settings require the main window.
- **No tray icon during `--status-panel` or CLI subcommands.** Tray is a main-window concern.
- **No macOS/Linux support.** Windows-only, consistent with the rest of the app.

## Settings

Two new keys under `general`:

| Key                       | Type | Default | Purpose                                                     |
|---------------------------|------|---------|-------------------------------------------------------------|
| `general.minimize_to_tray` | bool | `False` | When true, minimize button hides the window to tray.        |
| `general.show_tray_hint`  | bool | `True`  | When true, show one-time welcome balloon on first tray hide. Flipped to `False` after the balloon is shown once. |

UI exposure: new checkbox in Settings > General tab, labeled **"When minimized, hide to system tray"**, with tooltip `"Keeps TalkTrack out of the taskbar. Right-click the tray icon to restore or stop recording."` The `show_tray_hint` flag has no UI — it's internal state.

## Window Behavior

### Minimize button

- If `minimize_to_tray` is **false**: default Qt behavior (taskbar minimize). No change from today.
- If `minimize_to_tray` is **true**:
  1. Hide the main window (`self.hide()` — not `showMinimized()`, so it leaves the taskbar entirely).
  2. If `show_tray_hint` is true, show a one-time tray balloon:
     - Title: `TalkTrack is still running`
     - Body: `Right-click the tray icon for options. Disable this in Settings > General.`
     - Duration: 5 seconds.
     - After showing, set `show_tray_hint` to false and persist.
  3. Recording, transcription, and summaries continue normally.

Detection: override `changeEvent` and check for `QEvent.Type.WindowStateChange` where `windowState()` includes `Qt.WindowState.WindowMinimized`. When hiding to tray, restore `windowState()` to `WindowNoState` before calling `hide()` so the window opens at normal size next time it's shown.

### Close (X) button

- Always shows a `QMessageBox` confirmation:
  - Title: `Exit TalkTrack?`
  - Body (idle): `Are you sure you want to exit?`
  - Body (recording): `A recording is in progress. Exiting will stop and save the current recording. Continue?`
  - Buttons: `Exit` (default), `Cancel`.
- On `Exit`: set `self._really_quit = True`, let the existing `closeEvent` shutdown path run (stops recording cleanly, flushes config). `QApplication.quit()` follows automatically.
- On `Cancel`: `event.ignore()`, stay running.
- The confirmation does **not** fire when `_really_quit` is already true (e.g., from tray Quit). Prevents double prompts.

### closeEvent flow

```
closeEvent(event):
    if not self._really_quit:
        if not self._confirm_exit():   # QMessageBox
            event.ignore()
            return
        self._really_quit = True
    # existing shutdown: stop recording, flush config, stop timers, ...
    super().closeEvent(event)
```

## Tray Icon

### Lifecycle

- Created in `MainWindow.__init__` after `_setup_ui`, always present while the app runs.
- Uses `resources/talktrack.ico` as the base icon.
- If `QSystemTrayIcon.isSystemTrayAvailable()` returns false, tray is skipped: minimize falls back to taskbar behavior regardless of the setting, close still confirms-and-quits. A single log warning is emitted on startup.

### Icon states (overlay badges)

Base icon with an overlay dot in the bottom-right corner, painted at runtime with `QPainter`.

| State                         | Overlay       | Meaning                                                                   |
|-------------------------------|---------------|---------------------------------------------------------------------------|
| Idle / normal recording       | none          | Nothing to report. Recording state shown via tooltip, not overlay.        |
| Success notification pending  | green dot     | Transcription or summary completed while window was hidden.               |
| Error notification pending    | red dot       | Transcription or summary failed while window was hidden.                  |

The overlay resets to no-overlay when the window is restored (`showNormal` path). If both success and error events occurred, red wins (errors are more important to surface).

Dot size: ~28% of icon diagonal, positioned with 2px margin from bottom-right. Drawn with a 1px dark ring (`#1e1e2e`) for visibility over any base-icon background.

### Tooltip

Dynamic, updated on every recording-timer tick (already exists) and on state transitions:

| State         | Tooltip                                       |
|---------------|-----------------------------------------------|
| Idle          | `TalkTrack`                                   |
| Recording     | `TalkTrack — Recording 00:12:34`              |
| Paused        | `TalkTrack — Paused 00:12:34`                 |

Tooltip is truncated by Windows after ~127 chars; these fit comfortably.

### Click behavior

- **Left single-click or double-click** (`QSystemTrayIcon.ActivationReason.Trigger` / `.DoubleClick`): restore the main window (`showNormal()`, `raise_()`, `activateWindow()`) and clear any notification overlay.
- **Right-click**: Qt shows the context menu automatically when a menu is set.

### Context menu

Built once, refreshed on state changes so actions stay consistent with the main UI:

```
┌──────────────────────────┐
│ Show TalkTrack           │   ← always
├──────────────────────────┤
│ Record          Ctrl+R*  │   ← visible when IDLE
│ Pause                    │   ← visible when RECORDING
│ Resume                   │   ← visible when PAUSED
│ Stop                     │   ← visible when RECORDING or PAUSED
├──────────────────────────┤
│ Quit                     │   ← always
└──────────────────────────┘
```

*Shortcut labels are cosmetic on tray menus (Windows doesn't route accelerators through tray menus), included only for discoverability.

Actions call the **same slots** the main-window buttons already wire up (`_on_record_clicked`, `_on_pause_clicked`, `_on_stop_clicked`). No duplication of recording logic.

`Quit` calls the same `_confirm_exit()` + `close()` path as the X button. Confirmation appears when `Quit` is chosen from the tray menu, even if the main window is hidden — the modal will pop in the foreground.

## Popup Suppression While Hidden

**Rule:** when `self.isHidden()` is true, any code path that would show a modal `QMessageBox`, `QDialog`, or `QInputDialog` must be suppressed — the dialog is either skipped entirely or its result substituted with a default.

Implementation: a helper `MainWindow._suppress_popups_while_hidden(callable, *args, **kwargs)` wraps any call that may show a dialog. If hidden, it records the event type (success/error) and sets the appropriate tray overlay; if visible, it executes the callable normally.

Audit to run during implementation — known suspects (catalog verified in plan phase):

- Transcription completion — if a `QMessageBox.information` exists announcing "Transcription ready."
- Transcription failure — `QMessageBox.critical` from the worker error path.
- Summary completion / failure — similar.
- Recording save errors — `QMessageBox.warning` on disk errors.
- Any modal triggered by the silence-auto-stop feature.

When the window is restored:

- **No queued popups replay.** The user sees the current state via the viewers and (if applicable) the cleared-but-previously-red/green tray indicator.
- If a red (error) overlay was active, a status-bar message or banner **may** be added in the plan phase if auditing reveals a case where the user would otherwise have no indication something failed. TBD during audit.

## First-Time Balloon

Single scenario: user enables `minimize_to_tray`, clicks minimize for the first time, window vanishes. The one-time tray balloon (`show_tray_hint`) prevents confusion.

Balloon details:

- API: `QSystemTrayIcon.showMessage(title, body, icon, msecs=5000)`
- Icon arg: `QSystemTrayIcon.MessageIcon.Information`
- No click-through action required; balloon is informational only.

After display, `show_tray_hint` flips to false and is written to config immediately (not debounced), so even a crash preserves the flag.

## Edge Cases

- **Tray disabled by OS:** `QSystemTrayIcon.isSystemTrayAvailable()` is false. Tray icon is not created. `minimize_to_tray` becomes a no-op with a log warning; minimize button behaves as default Qt. Close still confirms-and-quits.
- **Restore while recording:** no special handling — recording state machine is unchanged by window visibility.
- **Exit while hidden, from tray Quit:** confirmation dialog appears (Windows auto-focuses the dialog even without a visible parent window). On confirm, normal shutdown runs.
- **Settings dialog opened while hidden:** not possible — settings is reached from main window menu. Main window must be visible first.
- **Multiple rapid minimize/restore:** tray overlay updates are idempotent; no race conditions because all UI changes happen on the main thread.
- **Recording auto-stop (silence) while hidden:** recorder stops, transcription runs (if auto-transcribe enabled), no popups appear, tray gets green dot on completion (or red on failure).
- **First launch with `minimize_to_tray=True` carried over from a previous session:** tray hint still shows on first minimize of that session — `show_tray_hint` is a one-time-ever flag, not per-session.

## Files Touched

- `app/main_window.py` — `changeEvent`, `closeEvent`, `_confirm_exit`, tray wiring, `_really_quit` flag, overlay state tracking.
- `app/ui/tray_icon.py` — **new.** `TrayIcon` wrapper around `QSystemTrayIcon`. Owns base icon + overlay compositing + menu + state-aware action visibility.
- `app/ui/settings_dialog.py` — add "When minimized, hide to system tray" checkbox to General tab.
- `app/utils/config.py` — ensure `general.minimize_to_tray` and `general.show_tray_hint` have defaults on load (if defaults are centralized there).
- `tests/test_tray_icon.py` — **new.** Unit tests for pure helpers (overlay compositing given dot color, state→menu-visibility logic, tooltip formatter).
- Existing popup call sites — add `isHidden()` guards as per audit.

## Testing Strategy

Per ways-of-working.md, UI code is smoke-tested; pure helpers are unit tested.

**Unit tests (pure helpers, no Qt app needed beyond offscreen):**

- Tooltip formatter: `format_tray_tooltip(state, elapsed)` returns expected strings for IDLE / RECORDING / PAUSED.
- Menu visibility resolver: `tray_action_visibility(state)` returns the correct `{action_name: bool}` map for each `RecordingState`.
- Overlay color resolver: given a history of success/error events since last restore, returns `None` / `"green"` / `"red"` with red-wins rule.

**Smoke tests:**

- Import + instantiate `TrayIcon` under `QApplication` offscreen, verify no exceptions.
- Full-app boot still opens and closes cleanly on Windows (manual).

**Manual verification (documented in plan, run before commit):**

1. Launch app, enable "hide to tray" in General, click minimize → window disappears, balloon shows once.
2. Right-click tray, select Stop / Pause / Record during various states — each behaves like the main-window button.
3. Double-click tray → window restores.
4. Close (X) → confirmation dialog. Cancel keeps app running. Exit shuts down cleanly.
5. Recording → minimize to tray → let it auto-stop via silence (or manual stop via tray) → transcription completes → green dot appears. Restore window → dot clears.
6. Disable tray setting → minimize reverts to taskbar behavior.
