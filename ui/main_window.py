"""
ui/main_window.py — WorkSpace Manager main window.
Uiverse-inspired: light theme, gradient sidebar, glass cards, soft shadows.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QInputDialog, QLineEdit, QMessageBox, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer, QRect
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QLinearGradient,
    QPen, QBrush, QIcon, QPixmap, QRadialGradient
)

import db
from ui.session_detail import SessionDetailPanel
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, GLASS, BORDER,
    ACCENT, ACCENT2, ACCENT3, ACCENT_LIGHT, ACCENT_MED,
    GRAD_START, GRAD_END, TEXT, TEXT2, MUTED, MUTED2,
    GREEN, GREEN_BG, AMBER, AMBER_BG, RED, RED_BG,
    SHADOW_SM, SHADOW_MD
)


# ── Drop shadow helper ────────────────────────────────────────────────────────

def _shadow(widget, radius=20, color=SHADOW_MD, dx=0, dy=4):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(radius)
    fx.setColor(QColor(color))
    fx.setOffset(dx, dy)
    widget.setGraphicsEffect(fx)


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
        self.setFixedSize(320, 48)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.hide)
        self._icon = ""
        self._msg  = ""

    def show_toast(self, icon: str, msg: str, duration=2800):
        self._icon = icon
        self._msg  = msg
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - 160, screen.bottom() - 90)
        self.show()
        self.raise_()
        self.update()
        self._timer.start(duration)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(2, 2, self.width()-4, self.height()-4, 14, 14)
        p.fillPath(path, QColor(255, 255, 255, 240))
        p.setPen(QPen(QColor(BORDER), 1.5))
        p.drawPath(path)
        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI Variable", 12, QFont.Weight.Medium))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                   f"  {self._icon}  {self._msg}")


# ── Session card ──────────────────────────────────────────────────────────────

class SessionCard(QWidget):
    open_clicked   = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    # Gradient pairs per index for variety
    CARD_GRADIENTS = [
        ("#6c63ff", "#a78bfa"),
        ("#f093fb", "#f5576c"),
        ("#4facfe", "#00f2fe"),
        ("#43e97b", "#38f9d7"),
        ("#fa709a", "#fee140"),
        ("#a18cd1", "#fbc2eb"),
        ("#fccb90", "#d57eeb"),
        ("#a1c4fd", "#c2e9fb"),
    ]

    def __init__(self, session: dict, stats: dict, index: int = 0, parent=None):
        super().__init__(parent)
        self.session_id = session["id"]
        self._hovered   = False
        self._grad      = self.CARD_GRADIENTS[index % len(self.CARD_GRADIENTS)]
        self.setFixedHeight(180)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._build(session, stats)
        _shadow(self, radius=18, color=SHADOW_SM, dy=3)

    def _build(self, session: dict, stats: dict):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QWidget()
        card.setStyleSheet(f"""
            QWidget {{
                background: {SURFACE};
                border: 1.5px solid {BORDER};
                border-radius: 16px;
            }}
        """)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        # ── Colour bar at top ──
        bar = QWidget(card)
        bar.setFixedHeight(5)
        bar.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 {self._grad[0]}, stop:1 {self._grad[1]});
            border-radius: 3px;
        """)
        layout.addWidget(bar)

        # ── Header row ──
        header = QHBoxLayout()
        header.setSpacing(10)

        icon_lbl = QLabel(session.get("icon", "🗂"))
        icon_lbl.setFixedSize(38, 38)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {self._grad[0]}22, stop:1 {self._grad[1]}22);
            border-radius: 10px;
            font-size: 18px;
            border: 1.5px solid {self._grad[0]}33;
        """)
        header.addWidget(icon_lbl)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        name_lbl = QLabel(session["name"])
        name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 14px; font-weight: 700; letter-spacing: -0.2px;"
        )
        name_col.addWidget(name_lbl)

        try:
            dt = datetime.fromisoformat(session.get("updated_at", ""))
            date_str = dt.strftime("%b %d, %H:%M")
        except Exception:
            date_str = "—"
        date_lbl = QLabel(f"Updated {date_str}")
        date_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        name_col.addWidget(date_lbl)
        header.addLayout(name_col)
        header.addStretch()

        # Delete button
        del_btn = QPushButton("🗑")
        del_btn.setFixedSize(30, 30)
        del_btn.setToolTip("Delete session")
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1.5px solid transparent;
                border-radius: 8px;
                font-size: 14px;
                color: {MUTED};
            }}
            QPushButton:hover {{
                background: {RED_BG};
                border-color: rgba(239,68,68,0.3);
                color: {RED};
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.session_id))
        header.addWidget(del_btn)
        layout.addLayout(header)

        # ── Stats chips ──
        chips_row = QHBoxLayout()
        chips_row.setSpacing(6)
        chip_data = []
        if stats["files"]: chip_data.append((f"📄  {stats['files']} file{'s' if stats['files']!=1 else ''}", self._grad[0]))
        if stats["urls"]:  chip_data.append((f"🌐  {stats['urls']} URL{'s' if stats['urls']!=1 else ''}",   self._grad[1]))
        if stats["apps"]:  chip_data.append((f"⚙️  {stats['apps']} app{'s' if stats['apps']!=1 else ''}",   "#6c63ff"))

        for text, color in chip_data:
            chip = QLabel(text)
            chip.setStyleSheet(f"""
                background: {color}18;
                border: 1px solid {color}33;
                border-radius: 20px;
                padding: 3px 10px;
                font-size: 11px;
                color: {color};
                font-weight: 600;
            """)
            chips_row.addWidget(chip)

        if not chip_data:
            empty = QLabel("Empty — click to add items")
            empty.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
            chips_row.addWidget(empty)
        chips_row.addStretch()
        layout.addLayout(chips_row)

        layout.addStretch()

        # ── Open button ──
        open_btn = QPushButton("▶  Open Session")
        open_btn.setFixedHeight(32)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {self._grad[0]}, stop:1 {self._grad[1]});
                border: none;
                border-radius: 8px;
                color: white;
                font-weight: 700;
                font-size: 12px;
            }}
            QPushButton:hover {{ opacity: 0.9; }}
        """)
        open_btn.clicked.connect(lambda: self.open_clicked.emit(self.session_id))
        layout.addWidget(open_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_clicked.emit(self.session_id)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()


# ── Empty state ───────────────────────────────────────────────────────────────

class GridEmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        icon = QLabel("✨")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 56px; background: transparent;")
        layout.addWidget(icon)

        title = QLabel("No sessions yet")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"color: {TEXT}; font-size: 20px; font-weight: 800; letter-spacing: -0.5px;"
        )
        layout.addWidget(title)

        subtitle = QLabel("Create a session to start organizing\nyour files, websites, and apps.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 13px; line-height: 1.5;")
        layout.addWidget(subtitle)


# ── Sidebar ───────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    create_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(230)
        self._count = 0

    def set_count(self, n: int):
        self._count = n
        if hasattr(self, "_count_lbl"):
            self._count_lbl.setText(f"{n} session{'s' if n != 1 else ''}")

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QLinearGradient(0, 0, 0, self.height())
        grad.setColorAt(0, QColor("#6c63ff"))
        grad.setColorAt(0.5, QColor("#8b5cf6"))
        grad.setColorAt(1, QColor("#a78bfa"))
        p.fillRect(self.rect(), grad)

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 28, 22, 28)
        layout.setSpacing(0)

        # Logo
        logo_row = QHBoxLayout()
        logo_icon = QLabel("⊞")
        logo_icon.setStyleSheet("font-size: 26px; color: white;")
        logo_row.addWidget(logo_icon)
        logo_text = QLabel("WorkSpace")
        logo_text.setStyleSheet(
            "font-size: 17px; font-weight: 800; color: white; letter-spacing: -0.5px;"
        )
        logo_row.addWidget(logo_text)
        logo_row.addStretch()
        layout.addLayout(logo_row)
        layout.addSpacing(8)

        tagline = QLabel("Your work, always ready.")
        tagline.setStyleSheet("color: rgba(255,255,255,0.6); font-size: 11px;")
        layout.addWidget(tagline)
        layout.addSpacing(36)

        # Section label
        sec = QLabel("SESSIONS")
        sec.setStyleSheet(
            "color: rgba(255,255,255,0.5); font-size: 10px; font-weight: 700; letter-spacing: 2.5px;"
        )
        layout.addWidget(sec)
        layout.addSpacing(8)

        self._count_lbl = QLabel(f"{self._count} sessions")
        self._count_lbl.setStyleSheet("color: rgba(255,255,255,0.75); font-size: 12px;")
        layout.addWidget(self._count_lbl)

        layout.addStretch()

        # Divider
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet("background: rgba(255,255,255,0.2); max-height: 1px;")
        layout.addWidget(div)
        layout.addSpacing(18)

        # New session button
        create_btn = QPushButton("＋  New Session")
        create_btn.setFixedHeight(42)
        create_btn.setStyleSheet("""
            QPushButton {
                background: rgba(255,255,255,0.2);
                border: 1.5px solid rgba(255,255,255,0.35);
                border-radius: 12px;
                color: white;
                font-weight: 700;
                font-size: 13px;
            }
            QPushButton:hover {
                background: rgba(255,255,255,0.32);
                border-color: rgba(255,255,255,0.55);
            }
            QPushButton:pressed {
                background: rgba(255,255,255,0.15);
            }
        """)
        create_btn.clicked.connect(self.create_clicked.emit)
        layout.addWidget(create_btn)


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkSpace Manager")
        self.setMinimumSize(960, 640)
        self.resize(1120, 720)
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
        self._sidebar._build()
        self._sidebar.create_clicked.connect(self._create_session)
        h.addWidget(self._sidebar)

        # Content area
        self._content = QWidget()
        self._content.setStyleSheet(f"background: {BG};")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(0, 0, 0, 0)
        self._content_layout.setSpacing(0)
        h.addWidget(self._content, 1)

        self._grid_page = self._build_grid_page()
        self._content_layout.addWidget(self._grid_page)

    def _build_grid_page(self) -> QWidget:
        page = QWidget()
        page.setStyleSheet(f"background: {BG};")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(36, 32, 36, 32)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        title = QLabel("Sessions")
        title.setStyleSheet(
            f"color: {TEXT}; font-size: 24px; font-weight: 800; letter-spacing: -0.5px;"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        layout.addSpacing(6)

        subtitle = QLabel("Click a session to view, edit, or restore it.")
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        layout.addWidget(subtitle)
        layout.addSpacing(28)

        # Scrollable 2-column grid
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid_layout = QVBoxLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 4, 0)
        self._grid_layout.setSpacing(14)
        self._grid_layout.addStretch()

        scroll.setWidget(self._grid_widget)
        layout.addWidget(scroll)
        return page

    # ── Data ──

    def _load_sessions(self):
        while self._grid_layout.count() > 1:
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                # remove row layout
                while item.layout().count():
                    c = item.layout().takeAt(0)
                    if c.widget():
                        c.widget().deleteLater()

        sessions = db.get_all_sessions()
        self._sidebar.set_count(len(sessions))

        if not sessions:
            self._grid_layout.insertWidget(0, GridEmptyState())
            return

        # 2-column grid
        row_layout = None
        for i, session in enumerate(sessions):
            if i % 2 == 0:
                row_layout = QHBoxLayout()
                row_layout.setSpacing(14)
                self._grid_layout.insertLayout(i // 2, row_layout)

            stats = db.get_session_stats(session["id"])
            card = SessionCard(session, stats, index=i)
            card.open_clicked.connect(self._open_detail)
            card.delete_clicked.connect(self._delete_session)
            row_layout.addWidget(card)

        # Pad last row if odd number
        if len(sessions) % 2 != 0 and row_layout:
            row_layout.addStretch()

    # ── Actions ──

    def _create_session(self):
        name, ok = QInputDialog.getText(
            self, "New Session", "Session name:",
            QLineEdit.EchoMode.Normal, ""
        )
        if ok and name.strip():
            session_id = db.create_session(name.strip())
            self._load_sessions()
            self._toast.show_toast("✨", f'"{name.strip()}" created')
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
            if self._detail_panel:
                self._close_detail()
            self._load_sessions()
            self._toast.show_toast("🗑", f'"{session["name"]}" deleted')

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
