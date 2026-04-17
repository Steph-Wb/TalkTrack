"""Reusable collapsible section with a clickable title header."""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QToolButton, QVBoxLayout, QWidget


class CollapsibleSection(QWidget):
    """A section with a clickable header that toggles content visibility.

    When collapsed, the widget clamps its max height to the title bar so it
    cannot expand to fill space via layout stretch factors.
    """

    toggled = pyqtSignal(bool)

    def __init__(self, title, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header row: toggle button on the left, extras (Refresh, etc.)
        # can be added on the right via add_header_widget().
        self._header_row = QHBoxLayout()
        self._header_row.setContentsMargins(0, 0, 0, 0)
        self._header_row.setSpacing(4)

        self._toggle_btn = QToolButton()
        self._toggle_btn.setObjectName("collapsibleToggle")
        self._toggle_btn.setText(f"\u25b8  {title}")
        self._toggle_btn.setCheckable(True)
        self._toggle_btn.setChecked(False)
        self._toggle_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self._toggle_btn.toggled.connect(self._on_toggled)
        self._toggle_btn.setStyleSheet(
            "QToolButton { border: none; color: #89b4fa; font-weight: bold; "
            "text-align: left; padding: 4px 0; }"
            "QToolButton:hover { color: #b4befe; }"
        )
        self._header_row.addWidget(self._toggle_btn)
        self._header_row.addStretch()
        layout.addLayout(self._header_row)

        self._content = QWidget()
        self._content.setVisible(False)
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 4, 0, 0)
        layout.addWidget(self._content, 1)

        self._title = title

        # Start collapsed: clamp height to the title bar
        self.setMaximumHeight(self._toggle_btn.sizeHint().height() + 4)

    def add_header_widget(self, widget):
        """Add a widget to the right side of the header row."""
        self._header_row.addWidget(widget)

    def content_layout(self):
        return self._content_layout

    def is_expanded(self) -> bool:
        return self._toggle_btn.isChecked()

    def _on_toggled(self, checked):
        self._content.setVisible(checked)
        arrow = "\u25be" if checked else "\u25b8"
        self._toggle_btn.setText(f"{arrow}  {self._title}")
        if checked:
            self.setMaximumHeight(16777215)  # QWIDGETSIZE_MAX
        else:
            self.setMaximumHeight(self._toggle_btn.sizeHint().height() + 4)
        self.toggled.emit(checked)

    def set_expanded(self, expanded):
        self._toggle_btn.setChecked(expanded)
