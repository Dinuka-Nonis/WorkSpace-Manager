"""
ui/hud.py — Floating HUD (Heads-Up Display) for session management.
Toggled with Win+` hotkey. Bottom-right corner, frameless, blur-backed.
Shows all sessions with status indicators, quick restore/switch.
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGraphicsDropShadowEffect, QSizePolicy,
    QApplication
)
from PyQt6.QtCore import (
    Qt, QPropertyAnimation, QEasingCurve, pyqtSignal, QTimer, QPoint
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QLinearGradient,
    QPen, QBrush, QKeyEvent
)

import db
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER, ACCENT, ACCENT2,
    TEXT, MUTED, MUTED2, GREEN, AMBER, RED,
    WHITE_005, WHITE_008, ACCENT_010, ACCENT_020
)

STATUS_COLORS = {
    "active": GREEN,
    "paused": AMBER,
    "idle": MUTED,
}

APP_ICON_MAP = {
    "VS Code": "💙",
    "Chrome": "🌐",
    "Edge": "🔵",
    "Firefox": "🦊",
    "Terminal": "⬛",
    "Python": "🐍",
    "PyCharm": "🔮",
    "Postman": "📮",
    "Figma": "🎨",
    "Obsidian": "💎",
    "Word": "📝",
    "Excel": "📊",
    "PowerPoint": "📐",
}


class StatusDot(QWidget):
    def __init__(self, status: str, parent=None):
        super().__init__(parent)
        self.status = status
        self.setFixedSize(8, 8)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(STATUS_COLORS.get(self.status, MUTED))
        p.setBrush(color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(0, 0, 8, 8)


class AppChip(QWidget):
    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setFixedHeight(20)
        fm = QFont("Segoe UI Variable", 10)
        from PyQt6.QtGui import QFontMetrics
        w = QFontMetrics(fm).horizontalAdvance(text) + 18
        self.setFixedWidth(min(w, 100))

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 5, 5)
        p.fillPath(path, QColor(255, 255, 255, 12))
        pen = QPen(QColor(255, 255, 255, 20), 1)
        p.setPen(pen)
        p.drawPath(path)
        p.setPen(QColor(MUTED))
        p.setFont(QFont("Cascadia Mono", 10))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._text)


class SessionCard(QWidget):
    restore_clicked = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    def __init__(self, session: dict, stats: dict, parent=None):
        super().__init__(parent)
        self.session_id = session["id"]
        self.status = session.get("status", "idle")
        self._hovered = False
        self.setFixedHeight(96)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._build(session, stats)

    def _build(self, session: dict, stats: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 10, 10)
        layout.setSpacing(5)

        # ── Top row: dot, name, status badge ──
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(StatusDot(self.status))

        name_label = QLabel(f"{session.get('icon','🗂')} {session['name']}")
        name_label.setStyleSheet(f"""
            color: {TEXT};
            font-size: 13px;
            font-weight: 600;
            font-family: "Segoe UI Variable";
        """)
        name_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        top.addWidget(name_label)

        status_lbl = QLabel(self.status.upper())
        color = STATUS_COLORS.get(self.status, MUTED)
        status_lbl.setStyleSheet(f"""
            color: {color};
            background: {color}22;
            border-radius: 10px;
            padding: 1px 8px;
            font-size: 9px;
            font-weight: 700;
            font-family: "Cascadia Mono", monospace;
            letter-spacing: 0.5px;
        """)
        top.addWidget(status_lbl)
        layout.addLayout(top)

        # ── App chips ──
        chips_row = QHBoxLayout()
        chips_row.setSpacing(4)
        chips_row.setContentsMargins(0, 0, 0, 0)

        apps = stats.get("apps", [])
        if stats.get("tab_count", 0) > 0:
            chips_row.addWidget(AppChip(f"🌐 {stats['tab_count']} tabs"))
        for app in apps[:4]:
            icon = APP_ICON_MAP.get(app, "🪟")
            chips_row.addWidget(AppChip(f"{icon} {app}"))
        chips_row.addStretch()
        layout.addLayout(chips_row)

        # ── Bottom: time + action buttons ──
        bottom = QHBoxLayout()
        bottom.setSpacing(4)
        from datetime import datetime
        created = session.get("created_at", "")
        try:
            dt = datetime.fromisoformat(created)
            time_str = dt.strftime("%b %d, %H:%M")
        except Exception:
            time_str = "—"

        time_lbl = QLabel(f"⏱ {stats.get('duration','—')}  ·  {time_str}")
        time_lbl.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
        bottom.addWidget(time_lbl)
        bottom.addStretch()

        restore_btn = QPushButton("↩ Restore")
        restore_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_010};
                border: 1px solid {ACCENT}44;
                color: {ACCENT2};
                border-radius: 6px;
                padding: 3px 10px;
                font-size: 11px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {ACCENT_020};
                border-color: {ACCENT};
            }}
        """)
        restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_btn.clicked.connect(lambda: self.restore_clicked.emit(self.session_id))
        bottom.addWidget(restore_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(26, 26)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(248,113,113,0.08);
                border: 1px solid rgba(248,113,113,0.15);
                color: {RED};
                border-radius: 6px;
                font-size: 12px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background: rgba(248,113,113,0.2);
                border-color: {RED};
            }}
        """)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.session_id))
        bottom.addWidget(del_btn)

        layout.addLayout(bottom)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)

        if self._hovered:
            p.fillPath(path, QColor(ACCENT).lighter(110))
            p.fillPath(path, QColor(124, 106, 247, 18))
        else:
            p.fillPath(path, QColor(255, 255, 255, 8))

        # Left accent bar
        bar = QPainterPath()
        color = STATUS_COLORS.get(self.status, MUTED)
        bar.addRoundedRect(0, 10, 3, self.height() - 20, 2, 2)
        p.fillPath(bar, QColor(color))

        # Border
        pen = QPen(QColor(255, 255, 255, 18 if not self._hovered else 35), 1)
        p.setPen(pen)
        p.drawPath(path)


class HUDWindow(QWidget):
    """
    Floating HUD — shows all sessions with restore/delete.
    Toggled by Win+` (handled by daemon/main).
    """
    restore_requested = pyqtSignal(int)
    delete_requested = pyqtSignal(int)
    open_dashboard = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._visible = False
        self._setup_window()
        self._build_ui()
        self._setup_animation()

    # ── Window Setup ──────────────────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(360)
        self._reposition()

    def _reposition(self):
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.right() - self.width() - 24,
                  screen.bottom() - 600 - 24)

    # ── UI Construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Outer card
        self.card = QWidget()
        self.card.setObjectName("hudCard")
        self.card.setStyleSheet(f"""
            QWidget#hudCard {{
                background: rgba(12, 12, 20, 0.95);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 20px;
            }}
        """)

        shadow = QGraphicsDropShadowEffect()
        shadow.setBlurRadius(60)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 180))
        self.card.setGraphicsEffect(shadow)

        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)

        # ── Header ──
        header = self._build_header()
        card_layout.addWidget(header)

        # ── Divider ──
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: rgba(255,255,255,0.05); border: none;")
        card_layout.addWidget(div)

        # ── Session list (scrollable) ──
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.scroll.setMaximumHeight(440)
        self.scroll.setStyleSheet("background: transparent;")

        self.sessions_container = QWidget()
        self.sessions_container.setStyleSheet("background: transparent;")
        self.sessions_layout = QVBoxLayout(self.sessions_container)
        self.sessions_layout.setContentsMargins(10, 8, 10, 8)
        self.sessions_layout.setSpacing(6)
        self.sessions_layout.addStretch()

        self.scroll.setWidget(self.sessions_container)
        card_layout.addWidget(self.scroll)

        # ── Footer ──
        footer = self._build_footer()
        card_layout.addWidget(footer)

        root.addWidget(self.card)

    def _build_header(self) -> QWidget:
        header = QWidget()
        header.setFixedHeight(52)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(18, 0, 14, 0)
        hl.setSpacing(0)

        title = QLabel("WORKSPACE")
        title.setStyleSheet(f"""
            color: {ACCENT2};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 2.5px;
            font-family: "Cascadia Mono", monospace;
        """)
        hl.addWidget(title)
        hl.addStretch()

        self.count_label = QLabel("0 sessions")
        self.count_label.setStyleSheet(f"""
            color: {MUTED};
            font-size: 11px;
            font-family: "Cascadia Mono", monospace;
        """)
        hl.addWidget(self.count_label)

        return header

    def _build_footer(self) -> QWidget:
        footer = QWidget()
        footer.setFixedHeight(48)
        footer.setStyleSheet(f"""
            background: rgba(255,255,255,0.02);
            border-top: 1px solid rgba(255,255,255,0.05);
            border-radius: 0 0 20px 20px;
        """)
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(14, 0, 14, 0)
        fl.setSpacing(8)

        dash_btn = QPushButton("⊞  Open Dashboard")
        dash_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                color: {MUTED};
                font-size: 12px;
                font-weight: 600;
                text-align: left;
                padding: 0;
            }}
            QPushButton:hover {{
                color: {TEXT};
            }}
        """)
        dash_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dash_btn.clicked.connect(self.open_dashboard.emit)
        fl.addWidget(dash_btn)

        fl.addStretch()

        kbd = QLabel("Win+`")
        kbd.setStyleSheet(f"""
            color: {MUTED};
            background: rgba(255,255,255,0.06);
            border: 1px solid {BORDER};
            border-radius: 5px;
            padding: 1px 7px;
            font-family: "Cascadia Mono", monospace;
            font-size: 10px;
        """)
        fl.addWidget(kbd)

        return footer

    # ── Animation ─────────────────────────────────────────────────────────────

    def _setup_animation(self):
        self._pos_anim = QPropertyAnimation(self, b"pos")
        self._pos_anim.setDuration(240)
        self._pos_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def _get_hidden_pos(self) -> QPoint:
        screen = QApplication.primaryScreen().availableGeometry()
        return QPoint(screen.right() - self.width() - 24, screen.bottom() + 20)

    def _get_visible_pos(self) -> QPoint:
        screen = QApplication.primaryScreen().availableGeometry()
        return QPoint(screen.right() - self.width() - 24,
                      screen.bottom() - self.height() - 24)

    # ── Public API ────────────────────────────────────────────────────────────

    def toggle(self):
        if self._visible:
            self.hide_hud()
        else:
            self.show_hud()

    def show_hud(self):
        self.refresh()
        hidden = self._get_hidden_pos()
        visible = self._get_visible_pos()
        self.move(hidden)
        self.show()
        self.raise_()

        self._pos_anim.setStartValue(hidden)
        self._pos_anim.setEndValue(visible)
        self._pos_anim.start()
        self._visible = True

    def hide_hud(self):
        hidden = self._get_hidden_pos()
        self._pos_anim.setStartValue(self.pos())
        self._pos_anim.setEndValue(hidden)
        self._pos_anim.finished.connect(self._after_hide)
        self._pos_anim.start()

    def _after_hide(self):
        self._pos_anim.finished.disconnect()
        self.hide()
        self._visible = False

    def refresh(self):
        """Reload sessions from DB and rebuild the list."""
        sessions = db.get_all_sessions()
        self.count_label.setText(f"{len(sessions)} session{'s' if len(sessions) != 1 else ''}")

        # Clear existing cards
        while self.sessions_layout.count() > 1:
            item = self.sessions_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not sessions:
            empty = QLabel("No sessions yet.\nPress Ctrl+Win+D to start.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet(f"color: {MUTED}; font-size: 12px; padding: 20px;")
            self.sessions_layout.insertWidget(0, empty)
            return

        for i, session in enumerate(sessions):
            stats = db.get_session_stats(session["id"])
            card = SessionCard(session, stats)
            card.restore_clicked.connect(self._on_restore)
            card.delete_clicked.connect(self._on_delete)
            self.sessions_layout.insertWidget(i, card)

        # Resize to fit
        total_h = min(len(sessions) * 102 + 16, 440)
        self.scroll.setMaximumHeight(total_h)

    def _on_restore(self, session_id: int):
        self.hide_hud()
        self.restore_requested.emit(session_id)

    def _on_delete(self, session_id: int):
        db.delete_session(session_id)
        self.refresh()
        self.delete_requested.emit(session_id)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def keyPressEvent(self, e: QKeyEvent):
        if e.key() == Qt.Key.Key_Escape:
            self.hide_hud()
        else:
            super().keyPressEvent(e)
