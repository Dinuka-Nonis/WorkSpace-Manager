"""
ui/spotlight.py — Mac Spotlight-style session naming prompt.

Shown when a new virtual desktop is detected by the daemon.
The user types a session name and presses Enter to confirm,
or Esc to dismiss (the desktop is created but goes untracked).
"""

from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QApplication
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QPen, QFont, QKeyEvent

import db
from ui.styles import (
    BG, SURFACE, SURFACE2, BORDER, ACCENT, ACCENT2, ACCENT_DIM,
    TEXT, MUTED, MUTED2, WHITE_005, ACCENT_010, ACCENT_020
)

ICON_OPTIONS = ["🗂", "💻", "🌐", "📝", "🎨", "🔧", "📊", "🎮", "📚", "🔬"]


class SpotlightPrompt(QWidget):
    """
    Frameless, centred prompt for naming a new virtual desktop session.

    Signals:
      confirmed(session_id, desktop_id) — user pressed Enter with a name
      dismissed()                        — user pressed Esc or closed
    """
    confirmed = pyqtSignal(int, str)   # session_id, desktop_id
    dismissed = pyqtSignal()

    def __init__(self, desktop_id: str, parent=None):
        super().__init__(parent)
        self._desktop_id = desktop_id
        self._selected_icon = "🗂"

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(480, 220)
        self._build()
        self._center()

    def _center(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            screen.center().x() - self.width() // 2,
            screen.center().y() - self.height() // 2 - 60,
        )

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget(self)
        card.setObjectName("spotlightCard")
        card.setStyleSheet(f"""
            #spotlightCard {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 18px;
            }}
        """)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(14)

        # Title
        title = QLabel("Name this workspace")
        title.setStyleSheet(
            f"color: {TEXT}; font-size: 15px; font-weight: 700; background: transparent;"
        )
        layout.addWidget(title)

        hint = QLabel("A new virtual desktop was created. Give it a name to start tracking it.")
        hint.setStyleSheet(f"color: {MUTED}; font-size: 12px; background: transparent;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        # Icon picker row
        icon_row = QHBoxLayout()
        icon_row.setSpacing(6)
        self._icon_btns = []
        for emoji in ICON_OPTIONS:
            btn = QLabel(emoji)
            btn.setFixedSize(30, 30)
            btn.setAlignment(Qt.AlignmentFlag.AlignCenter)
            btn.setStyleSheet(f"""
                background: {SURFACE2};
                border: 1px solid {BORDER};
                border-radius: 7px;
                font-size: 15px;
            """)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.mousePressEvent = lambda e, ic=emoji, b=btn: self._select_icon(ic, b)
            icon_row.addWidget(btn)
            self._icon_btns.append((emoji, btn))
        icon_row.addStretch()
        layout.addLayout(icon_row)
        # Highlight default
        self._select_icon("🗂", self._icon_btns[0][1])

        # Name input
        self._input = QLineEdit()
        self._input.setPlaceholderText("e.g. OS Lab 3 — Scheduling")
        self._input.setFixedHeight(44)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {SURFACE2};
                border: 2px solid {ACCENT};
                border-radius: 10px;
                color: {TEXT};
                font-size: 15px;
                font-weight: 500;
                padding: 0 14px;
                selection-background-color: {ACCENT_020};
            }}
        """)
        self._input.returnPressed.connect(self._confirm)
        layout.addWidget(self._input)

        # Footer hint
        footer = QLabel("Enter  to confirm   ·   Esc  to skip")
        footer.setAlignment(Qt.AlignmentFlag.AlignCenter)
        footer.setStyleSheet(
            f"color: {MUTED2}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(footer)

        self._input.setFocus()

    def _select_icon(self, emoji: str, btn: QLabel):
        self._selected_icon = emoji
        for _, b in self._icon_btns:
            b.setStyleSheet(f"""
                background: {SURFACE2};
                border: 1px solid {BORDER};
                border-radius: 7px;
                font-size: 15px;
            """)
        btn.setStyleSheet(f"""
            background: {ACCENT_020};
            border: 1px solid {ACCENT};
            border-radius: 7px;
            font-size: 15px;
        """)

    def _confirm(self):
        name = self._input.text().strip()
        if not name:
            self._input.setStyleSheet(self._input.styleSheet().replace(
                f"border: 2px solid {ACCENT}",
                "border: 2px solid #f87171"
            ))
            QTimer.singleShot(1200, lambda: self._input.setStyleSheet(
                self._input.styleSheet().replace("border: 2px solid #f87171",
                                                  f"border: 2px solid {ACCENT}")
            ))
            return

        session_id = db.create_session(
            name=name,
            icon=self._selected_icon,
            virtual_desktop_id=self._desktop_id,
        )
        self.confirmed.emit(session_id, self._desktop_id)
        self.close()

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_Escape:
            self.dismissed.emit()
            self.close()
        else:
            super().keyPressEvent(e)

    def paintEvent(self, e):
        # Needed so WA_TranslucentBackground works
        pass