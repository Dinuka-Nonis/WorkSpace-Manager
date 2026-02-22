"""
ui/spotlight.py — Mac Spotlight-inspired session naming prompt.
Appears on the current virtual desktop when Ctrl+Win+D creates a new desktop.
Frameless, centered, with blur overlay simulation.
"""

from PyQt6.QtWidgets import (
    QWidget, QLineEdit, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QApplication
)
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, QPoint,
    pyqtSignal, QTimer, QRect
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QKeyEvent,
    QLinearGradient, QBrush, QPen, QFontMetrics
)

from ui.styles import (
    BG, SURFACE, SURFACE2, BORDER, ACCENT, ACCENT2, TEXT, MUTED,
    MUTED2, WHITE_005, ACCENT_010, ACCENT_030
)

# Emoji suggestions for session names
SUGGESTIONS = [
    ("🔧", "OS Lab"),
    ("🌐", "Web Dev"),
    ("📄", "Research Paper"),
    ("🤖", "ML Project"),
    ("🗄", "Database"),
    ("🔌", "Networks Lab"),
    ("🌳", "DSA Assignment"),
    ("📐", "Math Assignment"),
    ("🎨", "Design Work"),
    ("⚙️", "System Admin"),
    ("📊", "Data Analysis"),
    ("🔐", "Security Lab"),
]


class SuggestionChip(QWidget):
    clicked = pyqtSignal(str)

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.full_text = f"{icon} {label}"
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(28)
        fm = QFontMetrics(QFont("Segoe UI Variable", 11))
        self.setFixedWidth(fm.horizontalAdvance(self.full_text) + 24)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        self.clicked.emit(self.full_text)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 7, 7)

        if self._hovered:
            p.fillPath(path, QColor(ACCENT).lighter(110))
            p.setPen(QColor(ACCENT2))
        else:
            p.fillPath(path, QColor(SURFACE2))
            p.setPen(QPen(QColor(BORDER), 1))
            p.drawPath(path)
            p.setPen(QColor(MUTED))

        p.setFont(QFont("Segoe UI Variable", 11))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self.full_text)


class SpotlightOverlay(QWidget):
    """Full-screen dim overlay behind the spotlight box."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(5, 5, 10, 160))


class SpotlightWindow(QWidget):
    """
    Mac Spotlight-style session naming prompt.
    Signals:
        session_confirmed(str)  — user pressed Enter with a name
        session_cancelled()     — user pressed Esc or clicked Cancel
    """
    session_confirmed = pyqtSignal(str)
    session_cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._setup_window()
        self._build_ui()
        self._setup_animations()

    # ── Window Setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(0.0)

        # Cover entire screen
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Spacer to push box to ~20% from top
        root.addStretch(2)

        # Center-align the box horizontally
        hbox = QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(self._build_box())
        hbox.addStretch()
        root.addLayout(hbox)

        root.addStretch(5)

    def _build_box(self) -> QWidget:
        box = QWidget(self)
        box.setObjectName("spotlightBox")
        box.setFixedWidth(580)
        box.setAutoFillBackground(False)
        self._box = box

        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Header row ──
        header = QWidget()
        header.setFixedHeight(64)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 0, 18, 0)
        hl.setSpacing(12)

        # Gradient icon badge
        icon_badge = self._make_icon_badge()
        hl.addWidget(icon_badge)

        # Text input
        self.input = QLineEdit()
        self.input.setPlaceholderText("Name this session…")
        self.input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {TEXT};
                font-size: 17px;
                font-weight: 500;
                font-family: "Segoe UI Variable", "Segoe UI";
                padding: 0;
                letter-spacing: -0.2px;
            }}
        """)
        self.input.returnPressed.connect(self._confirm)
        hl.addWidget(self.input)

        layout.addWidget(header)

        # ── Divider ──
        layout.addWidget(self._make_divider())

        # ── Suggestions ──
        sugg_widget = QWidget()
        sugg_widget.setFixedHeight(52)
        sl = QHBoxLayout(sugg_widget)
        sl.setContentsMargins(16, 0, 16, 0)
        sl.setSpacing(6)

        sugg_label = QLabel("Quick:")
        sugg_label.setStyleSheet(f"color: {MUTED}; font-size: 11px; font-weight: 600;")
        sl.addWidget(sugg_label)

        for icon, label in SUGGESTIONS[:5]:
            chip = SuggestionChip(icon, label)
            chip.clicked.connect(self._fill_suggestion)
            sl.addWidget(chip)

        sl.addStretch()
        layout.addWidget(sugg_widget)

        # ── Divider ──
        layout.addWidget(self._make_divider())

        # ── Footer: keyboard hints + buttons ──
        footer = QWidget()
        footer.setFixedHeight(50)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(16, 0, 16, 0)
        fl.setSpacing(8)

        for key, hint in [("↩ Enter", "confirm"), ("Esc", "cancel")]:
            fl.addWidget(self._make_kbd(key))
            lbl = QLabel(hint)
            lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
            fl.addWidget(lbl)
            fl.addSpacing(8)

        fl.addStretch()

        # Cancel button
        cancel_btn = QPushButton("✕  Cancel")
        cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(248,113,113,0.1);
                border: 1px solid rgba(248,113,113,0.2);
                color: #f87171;
                border-radius: 8px;
                padding: 5px 14px;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: rgba(248,113,113,0.2);
                border-color: #f87171;
            }}
        """)
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self._cancel)
        fl.addWidget(cancel_btn)

        # Confirm button
        confirm_btn = QPushButton("Start Session  →")
        confirm_btn.setObjectName("accentBtn")
        confirm_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                color: white;
                border-radius: 8px;
                padding: 6px 16px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: {ACCENT2};
            }}
        """)
        confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm_btn.clicked.connect(self._confirm)
        fl.addWidget(confirm_btn)

        layout.addWidget(footer)

        # Apply background styling
        box.setStyleSheet(f"""
            QWidget#spotlightBox {{
                background: rgba(16, 16, 26, 0.97);
                border: 1px solid rgba(124, 106, 247, 0.4);
                border-radius: 18px;
            }}
        """)

        # Drop shadow
        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(80)
        shadow.setOffset(0, 20)
        shadow.setColor(QColor(0, 0, 0, 200))
        box.setGraphicsEffect(shadow)

        return box

    def _make_icon_badge(self) -> QWidget:
        badge = QWidget()
        badge.setFixedSize(34, 34)

        class _Badge(QWidget):
            def __init__(self, p=None):
                super().__init__(p)
                self.setFixedSize(34, 34)

            def paintEvent(self, e):
                p = QPainter(self)
                p.setRenderHint(QPainter.RenderHint.Antialiasing)
                path = QPainterPath()
                path.addRoundedRect(0, 0, 34, 34, 9, 9)
                grad = QLinearGradient(0, 0, 34, 34)
                grad.setColorAt(0, QColor(ACCENT))
                grad.setColorAt(1, QColor(ACCENT2))
                p.fillPath(path, grad)
                p.setPen(QColor("white"))
                p.setFont(QFont("Segoe UI", 16))
                p.drawText(QRect(0, 0, 34, 34), Qt.AlignmentFlag.AlignCenter, "⊞")

        return _Badge(self)

    def _make_divider(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.HLine)
        f.setFixedHeight(1)
        f.setStyleSheet(f"background: {BORDER}; border: none;")
        return f

    def _make_kbd(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet(f"""
            color: {MUTED};
            background: rgba(255,255,255,0.06);
            border: 1px solid {BORDER};
            border-radius: 5px;
            padding: 1px 7px;
            font-family: "Cascadia Mono", "Consolas", monospace;
            font-size: 11px;
            font-weight: 500;
        """)
        return lbl

    # ── Animations ────────────────────────────────────────────────────────────

    def _setup_animations(self):
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity")
        self._fade_anim.setDuration(180)
        self._fade_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    # ── Public API ────────────────────────────────────────────────────────────

    def show_prompt(self):
        """Show the spotlight prompt with animation."""
        screen = QApplication.primaryScreen().geometry()
        self.setGeometry(screen)
        self.input.clear()
        self.show()
        self.raise_()
        self.activateWindow()

        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

        QTimer.singleShot(50, self.input.setFocus)

    def hide_prompt(self):
        self._fade_anim.setStartValue(self.windowOpacity())
        self._fade_anim.setEndValue(0.0)
        self._fade_anim.finished.connect(self._after_hide)
        self._fade_anim.start()

    def _after_hide(self):
        self._fade_anim.finished.disconnect()
        self.hide()

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _confirm(self):
        name = self.input.text().strip()
        if not name:
            self.input.setPlaceholderText("Please enter a session name…")
            self.input.setStyleSheet(self.input.styleSheet() +
                                     f"border-bottom: 1px solid #f87171;")
            return
        self.hide_prompt()
        self.session_confirmed.emit(name)

    def _cancel(self):
        self.hide_prompt()
        self.session_cancelled.emit()

    def _fill_suggestion(self, text: str):
        self.input.setText(text)
        self.input.setFocus()
        self.input.end(False)

    # ── Keyboard ──────────────────────────────────────────────────────────────

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(e)

    # ── Paint overlay ─────────────────────────────────────────────────────────

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(5, 5, 10, 150))
