"""
ui/main_window.py — Main window: session card grid + inline detail panel.

Layout:
  Left  — sidebar (logo, nav, create button)
  Right — either the session card grid OR the SessionDetailPanel
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QInputDialog, QLineEdit, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QSize, QTimer
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QLinearGradient, QPen, QIcon, QPixmap
)

import db
from ui.session_detail import SessionDetailPanel
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER, ACCENT, ACCENT2, ACCENT_DIM,
    TEXT, MUTED, MUTED2, GREEN, AMBER, RED,
    WHITE_005, ACCENT_010, ACCENT_020
)


# ── Toast ─────────────────────────────────────────────────────────────────────

class ToastNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 44)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.hide)
        self._icon = ""
        self._msg = ""

    def show_toast(self, icon: str, msg: str, duration=2500):
        self._icon = icon
        self._msg  = msg
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - 150, screen.bottom() - 80)
        self.show()
        self.raise_()
        self.update()
        self._timer.start(duration)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.fillPath(path, QColor(20, 20, 32, 240))
        p.setPen(QPen(QColor(ACCENT), 1))
        p.drawPath(path)
        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI Variable", 12))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                   f"  {self._icon}  {self._msg}")


# ── Session card ──────────────────────────────────────────────────────────────

class SessionCard(QWidget):
    clicked        = pyqtSignal(int)   # session_id
    delete_clicked = pyqtSignal(int)   # session_id

    def __init__(self, session: dict, stats: dict, parent=None):
        super().__init__(parent)
        self.session_id = session["id"]
        self._hovered   = False
        self.setFixedHeight(170)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._build(session, stats)

    def _build(self, session: dict, stats: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(8)

        # ── Top: icon + name + delete ──
        top = QHBoxLayout()
        top.setSpacing(10)

        icon_w = QLabel(session.get("icon", "🗂"))
        icon_w.setFixedSize(40, 40)
        icon_w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_w.setStyleSheet(f"""
            background: {ACCENT_010};
            border-radius: 10px;
            font-size: 20px;
        """)
        top.addWidget(icon_w)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = QLabel(session["name"])
        name.setStyleSheet(
            f"color: {TEXT}; font-size: 14px; font-weight: 700; letter-spacing: -0.2px;"
        )
        title_col.addWidget(name)

        try:
            dt = datetime.fromisoformat(session.get("updated_at", ""))
            date_str = dt.strftime("%b %d, %H:%M")
        except Exception:
            date_str = "—"
        date_lbl = QLabel(f"Updated {date_str}")
        date_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        title_col.addWidget(date_lbl)

        top.addLayout(title_col)
        top.addStretch()

        del_btn = QPushButton("✕")
        del_btn.setFixedSize(26, 26)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {MUTED2}; font-size: 12px; border-radius: 6px;
            }}
            QPushButton:hover {{
                background: rgba(248,113,113,0.15);
                color: {RED};
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.session_id))
        top.addWidget(del_btn)
        layout.addLayout(top)

        # ── Stats chips ──
        chips = QHBoxLayout()
        chips.setSpacing(6)
        chips.setContentsMargins(0, 0, 0, 0)
        chip_data = []
        if stats["files"]: chip_data.append(f"📄 {stats['files']}")
        if stats["urls"]:  chip_data.append(f"🌐 {stats['urls']}")
        if stats["apps"]:  chip_data.append(f"⚙️ {stats['apps']}")

        for text in chip_data:
            chip = QLabel(text)
            chip.setStyleSheet(f"""
                background: {SURFACE3};
                border-radius: 6px;
                padding: 3px 9px;
                font-size: 11px;
                color: {MUTED};
                font-weight: 600;
            """)
            chips.addWidget(chip)

        if not chip_data:
            empty_chip = QLabel("Empty")
            empty_chip.setStyleSheet(
                f"background: {SURFACE3}; border-radius: 6px; "
                f"padding: 3px 9px; font-size: 11px; color: {MUTED2};"
            )
            chips.addWidget(empty_chip)

        chips.addStretch()
        layout.addLayout(chips)

        # ── Description ──
        desc = session.get("description", "")
        if desc:
            desc_lbl = QLabel(desc)
            desc_lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
            desc_lbl.setWordWrap(True)
            layout.addWidget(desc_lbl)
        else:
            total = stats["total"]
            hint = QLabel(
                f"{total} item{'s' if total != 1 else ''}" if total
                else "Click to add files, URLs, or apps"
            )
            hint.setStyleSheet(f"color: {MUTED2}; font-size: 12px;")
            layout.addWidget(hint)

        layout.addStretch()

        # ── Bottom: Restore button ──
        restore_btn = QPushButton("▶  Restore All")
        restore_btn.setFixedHeight(30)
        restore_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_010};
                border: 1px solid {ACCENT};
                border-radius: 7px;
                color: {ACCENT2};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{ background: {ACCENT_020}; }}
        """)
        restore_btn.clicked.connect(lambda: self.clicked.emit(self.session_id))
        layout.addWidget(restore_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.session_id)

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
        path.addRoundedRect(0, 0, self.width(), self.height(), 14, 14)

        bg_color = QColor(SURFACE2) if not self._hovered else QColor(SURFACE3)
        p.fillPath(path, bg_color)

        border_color = QColor(ACCENT) if self._hovered else QColor(BORDER)
        p.setPen(QPen(border_color, 1))
        p.drawPath(path)


# ── Empty state ───────────────────────────────────────────────────────────────

class GridEmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon = QLabel("🗂")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 52px; background: transparent;")
        layout.addWidget(icon)

        title = QLabel("No sessions yet")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {TEXT}; font-size: 18px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel("Create a session to start organizing\nyour files, websites, and apps.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        layout.addWidget(subtitle)


# ── Sidebar ───────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    create_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self.setStyleSheet(f"background: {SURFACE};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 24, 20, 24)
        layout.setSpacing(0)

        # Logo
        logo_row = QHBoxLayout()
        logo_icon = QLabel("⊞")
        logo_icon.setStyleSheet(f"font-size: 22px; color: {ACCENT2};")
        logo_row.addWidget(logo_icon)
        logo_text = QLabel("WorkSpace")
        logo_text.setStyleSheet(
            f"font-size: 16px; font-weight: 800; color: {TEXT}; letter-spacing: -0.5px;"
        )
        logo_row.addWidget(logo_text)
        logo_row.addStretch()
        layout.addLayout(logo_row)
        layout.addSpacing(32)

        # Nav label
        nav_lbl = QLabel("SESSIONS")
        nav_lbl.setStyleSheet(
            f"color: {MUTED}; font-size: 10px; font-weight: 700; letter-spacing: 2px;"
        )
        layout.addWidget(nav_lbl)
        layout.addSpacing(8)

        # Sessions count
        self._count_lbl = QLabel("0 sessions")
        self._count_lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(self._count_lbl)

        layout.addStretch()

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background: {BORDER}; max-height: 1px;")
        layout.addWidget(div)
        layout.addSpacing(16)

        # Create button
        create_btn = QPushButton("＋  New Session")
        create_btn.setObjectName("accentBtn")
        create_btn.setFixedHeight(40)
        create_btn.clicked.connect(self.create_clicked.emit)
        layout.addWidget(create_btn)

    def set_count(self, n: int):
        self._count_lbl.setText(f"{n} session{'s' if n != 1 else ''}")


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkSpace Manager")
        self.setMinimumSize(900, 600)
        self.resize(1100, 700)
        self._detail_panel = None

        self._toast = ToastNotification()
        self._build()
        self._load_sessions()

    def _build(self):
        root = QWidget()
        root.setStyleSheet(f"background: {BG};")
        self.setCentralWidget(root)

        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)

        # Sidebar
        self._sidebar = Sidebar()
        self._sidebar.create_clicked.connect(self._create_session)
        h.addWidget(self._sidebar)

        # Vertical divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet(f"background: {BORDER}; max-width: 1px;")
        h.addWidget(div)

        # Content area (stacked: grid OR detail)
        self._content = QWidget()
        self._content.setStyleSheet(f"background: {BG};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        h.addWidget(self._content, 1)

        # Grid page
        self._grid_page = self._build_grid_page()
        self._content_layout.addWidget(self._grid_page)

    def _build_grid_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background: {BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(32, 28, 32, 28)
        layout.setSpacing(0)

        # Page header
        header = QHBoxLayout()
        title = QLabel("Sessions")
        title.setStyleSheet(
            f"color: {TEXT}; font-size: 22px; font-weight: 800; letter-spacing: -0.5px;"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        layout.addSpacing(24)

        # Scrollable card grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid_layout = QVBoxLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(12)
        self._grid_layout.addStretch()

        scroll.setWidget(self._grid_widget)
        layout.addWidget(scroll)

        return page

    # ── Data loading ──

    def _load_sessions(self):
        # Clear existing cards
        while self._grid_layout.count() > 1:
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sessions = db.get_all_sessions()
        self._sidebar.set_count(len(sessions))

        if not sessions:
            empty = GridEmptyState()
            self._grid_layout.insertWidget(0, empty)
            return

        for i, session in enumerate(sessions):
            stats = db.get_session_stats(session["id"])
            card = SessionCard(session, stats)
            card.clicked.connect(self._open_detail)
            card.delete_clicked.connect(self._delete_session)
            self._grid_layout.insertWidget(i, card)

    # ── Session actions ──

    def _create_session(self):
        name, ok = QInputDialog.getText(
            self, "New Session", "Session name:",
            QLineEdit.EchoMode.Normal, ""
        )
        if ok and name.strip():
            session_id = db.create_session(name.strip())
            self._load_sessions()
            self._toast.show_toast("✓", f'Session "{name.strip()}" created')
            # Immediately open the new session
            self._open_detail(session_id)

    def _delete_session(self, session_id: int):
        session = db.get_session(session_id)
        if not session:
            return
        reply = QMessageBox.question(
            self, "Delete Session",
            f'Delete "{session["name"]}"?\nThis cannot be undone.',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Yes:
            db.delete_session(session_id)
            self._close_detail()
            self._load_sessions()
            self._toast.show_toast("🗑", f'Deleted "{session["name"]}"')

    def _open_detail(self, session_id: int):
        self._close_detail()

        panel = SessionDetailPanel(session_id)
        panel.closed.connect(self._close_detail)
        panel.session_changed.connect(self._load_sessions)

        self._detail_panel = panel
        self._grid_page.hide()
        self._content_layout.addWidget(panel)

    def _close_detail(self):
        if self._detail_panel:
            self._content_layout.removeWidget(self._detail_panel)
            self._detail_panel.deleteLater()
            self._detail_panel = None
        self._grid_page.show()
        self._load_sessions()

    # ── Drag to move (frameless-friendly) ──

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton and hasattr(self, "_drag_pos"):
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()