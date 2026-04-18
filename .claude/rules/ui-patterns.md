# UI Patterns: reusable widget conventions and Qt gotchas

## CollapsibleSection (`app/ui/collapsible_section.py`)

- Reusable widget with a banded header (QFrame `#collapsibleHeader`) and collapsible content area.
- Emits `toggled(bool)` signal. Exposes `add_header_widget(widget)` for right-aligned extras (e.g., Refresh button).
- When collapsed, `setMaximumHeight(header_height)` so it can't claim empty space via layout stretch.
- **Dynamic stretch pattern**: when wrapping a CollapsibleSection in a parent QVBoxLayout, connect `toggled` to `setStretchFactor(widget, 1 if expanded else 0)`. This lets sibling sections absorb freed space when one is collapsed. See `MainWindow._setup_ui` for Audio Sources + Recordings example.
  - **Gotcha — all-collapsed case**: with only dynamic section stretches, collapsing every section leaves the layout with no claimant and Qt distributes the empty space oddly (centering one section, dropping the other to the bottom). Add a trailing `addStretch(0)` spacer and flip its stretch to 1 when no section is expanded, 0 otherwise — see `MainWindow._update_left_panel_stretch`.

## Left panel layout

- Fixed width 400px (`left_panel.setFixedWidth(400)`, objectName `leftPanel`). Intentionally non-draggable — prevents layout jitter on collapse/expand.
- Left-pane font size reduced to 9pt via QSS `#leftPanel QLabel, #leftPanel QRadioButton, ...`. Timer keeps 13pt via `#leftPanel #timerLabel`.
- Section title bands use `QFrame#collapsibleHeader` with `background-color: #313244` (Catppuccin surface0) and `border-radius: 4px`.

## DAW meter fill direction (`_VerticalMeter` in `meters_panel.py`)

- Bar fills **upward from bottom** as volume rises (standard DAW).
- Implementation: paint color zones over full height, then fill the **empty region ABOVE current level** with background color (`0` to `current_y`), NOT below. Getting this backwards makes the bar look like it's losing color as you speak.
- Peak hold line: 3px `#f5e0dc` (rosewater) — stands out against green/yellow/red and the dark empty region.

## Qt QSS gotchas

- Plain `QWidget` subclasses don't render `background-color` from QSS unless you set `WA_StyledBackground` attribute. Symptom: `#myPanel { background-color: X }` appears to apply everywhere or nowhere predictably.
- Cleaner alternatives: (a) wrap in a `QFrame` with an object name and style the frame, (b) custom `paintEvent` with `painter.drawRoundedRect`, (c) palette + `setAutoFillBackground(True)`.
- `QLabel`, `QFrame`, and similar DO render QSS backgrounds — scope them explicitly with `#parentId QLabel { ... }` to avoid cascade surprises.

## Palette

Catppuccin Mocha throughout. Common shades:
- Base: `#1e1e2e` — app bg
- Mantle: `#181825` — darker sections
- Surface0: `#313244` — bands, subtle lifts
- Text: `#cdd6f4`
- Blue accent: `#89b4fa`
- Red (clip/mute): `#f38ba8`
- Green (healthy): `#a6e3a1`
- Yellow (hot): `#f9e2af`
- Rosewater (peak line): `#f5e0dc`
