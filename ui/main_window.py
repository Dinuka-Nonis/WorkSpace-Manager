"""
ui/main_window.py — WorkSpace Manager main window.
Minimal design: neutral palette, list-style session cards, animated sidebar indicator.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QInputDialog, QLineEdit, QMessageBox, QApplication
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QTimer, QRect, QPropertyAnimation,
    QEasingCurve, QPoint, QSize
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QLinearGradient,
    QPen, QBrush, QIcon, QPixmap
)

import db
from ui.session_detail import SessionDetailPanel
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER,
    ACCENT, ACCENT2, ACCENT3, ACCENT_LIGHT, ACCENT_MED,
    TEXT, TEXT2, MUTED, MUTED2,
    RED, RED_BG, SHADOW_SM, SHADOW_MD
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
        self._msg = ""

    def show_toast(self, icon: str, msg: str, duration=2800):
        self._msg = f"{icon}  {msg}"
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
        path.addRoundedRect(1, 1, self.width() - 2, self.height() - 2, 10, 10)
        p.fillPath(path, QColor(25, 25, 25, 230))
        p.setPen(QColor(255, 255, 255, 220))
        p.setFont(QFont("Segoe UI Variable", 12, QFont.Weight.Medium))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._msg)


# ── Animated indicator bar (slides between nav items) ─────────────────────────

class AnimatedIndicator(QWidget):
    """A dark pill that slides vertically to highlight the active nav item."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(4)
        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(220)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def slide_to(self, y: int, h: int):
        self.setFixedHeight(h)
        target = QPoint(self.x(), y)
        if not self.isVisible():
            self.move(target)
            self.show()
            return
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 2, 2)
        p.fillPath(path, QColor(ACCENT))


# ── Session card (list-style, like the inspiration image) ────────────────────

class SessionCard(QWidget):
    open_clicked   = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    def __init__(self, session: dict, stats: dict, parent=None):
        super().__init__(parent)
        self.session_id = session["id"]
        self._hovered = False
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(72)
        self._build(session, stats)

    def _build(self, session: dict, stats: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 14, 0)
        layout.setSpacing(14)

        # Icon square — monochrome
        icon_lbl = QLabel(session.get("icon", "🗂"))
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: {SURFACE2};
            border: 1px solid {BORDER};
            border-radius: 9px;
            font-size: 17px;
        """)
        layout.addWidget(icon_lbl)

        # Name + meta
        text_col = QVBoxLayout()
        text_col.setSpacing(3)

        name_lbl = QLabel(session["name"])
        name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 13px; font-weight: 600;"
        )
        text_col.addWidget(name_lbl)

        # Build meta string
        parts = []
        if stats["files"]: parts.append(f"{stats['files']} file{'s' if stats['files'] != 1 else ''}")
        if stats["urls"]:  parts.append(f"{stats['urls']} URL{'s' if stats['urls'] != 1 else ''}")
        if stats["apps"]:  parts.append(f"{stats['apps']} app{'s' if stats['apps'] != 1 else ''}")

        try:
            dt = datetime.fromisoformat(session.get("updated_at", ""))
            date_str = dt.strftime("%b %d")
        except Exception:
            date_str = ""

        meta_parts = []
        if parts:
            meta_parts.append("  ·  ".join(parts))
        if date_str:
            meta_parts.append(date_str)

        meta_lbl = QLabel("  ·  ".join(meta_parts) if meta_parts else "Empty")
        meta_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        text_col.addWidget(meta_lbl)
        layout.addLayout(text_col)
        layout.addStretch()

        # Delete button — appears subtly
        self._del_btn = QPushButton("✕")
        self._del_btn.setFixedSize(26, 26)
        self._del_btn.setToolTip("Delete")
        self._del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: none;
                border-radius: 6px;
                font-size: 11px;
                color: {MUTED2};
            }}
            QPushButton:hover {{
                background: {RED_BG};
                color: {RED};
            }}
        """)
        self._del_btn.hide()
        self._del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.session_id))
        layout.addWidget(self._del_btn)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.open_clicked.emit(self.session_id)

    def enterEvent(self, e):
        self._hovered = True
        self._del_btn.show()
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self._del_btn.hide()
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            path = QPainterPath()
            path.addRoundedRect(0, 4, self.width(), self.height() - 8, 10, 10)
            p.fillPath(path, QColor(SURFACE2))


# ── Animated nav item ─────────────────────────────────────────────────────────

class NavItem(QWidget):
    clicked = pyqtSignal(object)   # emits self

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(36)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._active = False
        self._hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(10)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFixedWidth(18)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet("font-size: 14px; background: transparent;")
        layout.addWidget(self._icon_lbl)

        self._label = QLabel(label)
        self._label.setStyleSheet(f"color: {MUTED}; font-size: 13px; background: transparent;")
        layout.addWidget(self._label)
        layout.addStretch()

    def set_active(self, active: bool):
        self._active = active
        color = TEXT if active else MUTED
        weight = "600" if active else "400"
        self._label.setStyleSheet(
            f"color: {color}; font-size: 13px; font-weight: {weight}; background: transparent;"
        )
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def paintEvent(self, e):
        if self._hovered and not self._active:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(8, 2, self.width() - 16, self.height() - 4, 7, 7)
            p.fillPath(path, QColor(0, 0, 0, 14))


# ── Sidebar ───────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    create_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(220)
        self._count = 0
        self._nav_items = []
        self._active_item = None
        self._build()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURFACE))
        # Right border
        p.setPen(QPen(QColor(0, 0, 0, 18), 1))
        p.drawLine(self.width() - 1, 0, self.width() - 1, self.height())

    def set_count(self, n: int):
        self._count = n
        if hasattr(self, "_count_lbl"):
            self._count_lbl.setText(f"{n}")

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Top: logo ──
        logo_area = QWidget()
        logo_area.setFixedHeight(64)
        logo_layout = QHBoxLayout(logo_area)
        logo_layout.setContentsMargins(20, 0, 20, 0)

        logo_dot = QLabel("✦")
        logo_dot.setStyleSheet(f"font-size: 14px; color: {TEXT}; background: transparent;")
        logo_layout.addWidget(logo_dot)

        logo_text = QLabel("WorkSpace")
        logo_text.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {TEXT}; letter-spacing: -0.3px; background: transparent;"
        )
        logo_layout.addWidget(logo_text)
        logo_layout.addStretch()
        layout.addWidget(logo_area)

        # Thin separator
        sep1 = QFrame()
        sep1.setFrameShape(QFrame.Shape.HLine)
        sep1.setFixedHeight(1)
        sep1.setStyleSheet("background: rgba(0,0,0,0.07);")
        layout.addWidget(sep1)
        layout.addSpacing(8)

        # ── Nav section label ──
        nav_label = QLabel("MENU")
        nav_label.setStyleSheet(
            f"color: {MUTED2}; font-size: 10px; font-weight: 700; "
            f"letter-spacing: 1.5px; padding-left: 20px; background: transparent;"
        )
        nav_label.setFixedHeight(24)
        layout.addWidget(nav_label)
        layout.addSpacing(2)

        # ── Nav items container (for indicator overlay) ──
        self._nav_container = QWidget()
        self._nav_container.setStyleSheet("background: transparent;")
        nav_vbox = QVBoxLayout(self._nav_container)
        nav_vbox.setContentsMargins(0, 0, 0, 0)
        nav_vbox.setSpacing(2)

        # Indicator
        self._indicator = AnimatedIndicator(self._nav_container)
        self._indicator.hide()

        # Nav items
        nav_defs = [
            ("◫", "Sessions"),
        ]
        for icon, label in nav_defs:
            item = NavItem(icon, label)
            item.clicked.connect(self._on_nav_clicked)
            self._nav_items.append(item)
            nav_vbox.addWidget(item)

        # Activate first by default
        if self._nav_items:
            self._set_active(self._nav_items[0])

        layout.addWidget(self._nav_container)
        layout.addSpacing(16)

        # Thin separator
        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1)
        sep2.setStyleSheet("background: rgba(0,0,0,0.07);")
        layout.addWidget(sep2)
        layout.addSpacing(12)

        # ── Sessions count ──
        count_row = QHBoxLayout()
        count_row.setContentsMargins(20, 0, 20, 0)
        count_lbl_desc = QLabel("Sessions")
        count_lbl_desc.setStyleSheet(f"color: {MUTED}; font-size: 12px; background: transparent;")
        count_row.addWidget(count_lbl_desc)
        count_row.addStretch()
        self._count_lbl = QLabel(f"{self._count}")
        self._count_lbl.setStyleSheet(
            f"color: {MUTED2}; font-size: 12px; background: transparent;"
        )
        count_row.addWidget(self._count_lbl)
        layout.addLayout(count_row)

        layout.addStretch()

        # ── Bottom: new session button ──
        bottom_area = QWidget()
        bottom_area.setFixedHeight(72)
        bottom_layout = QVBoxLayout(bottom_area)
        bottom_layout.setContentsMargins(14, 12, 14, 12)

        create_btn = QPushButton("+ New Session")
        create_btn.setFixedHeight(36)
        create_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                border-radius: 8px;
                color: white;
                font-weight: 600;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: {ACCENT2};
            }}
            QPushButton:pressed {{
                background: {ACCENT3};
            }}
        """)
        create_btn.clicked.connect(self.create_clicked.emit)
        bottom_layout.addWidget(create_btn)
        layout.addWidget(bottom_area)

    def _on_nav_clicked(self, item: NavItem):
        self._set_active(item)

    def _set_active(self, item: NavItem):
        if self._active_item:
            self._active_item.set_active(False)
        item.set_active(True)
        self._active_item = item

        # Slide indicator to match item position
        pos = item.mapTo(self._nav_container, QPoint(0, 0))
        self._indicator.slide_to(pos.y() + 8, item.height() - 16)
        self._indicator.raise_()


# ── Empty state ───────────────────────────────────────────────────────────────

class GridEmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        icon = QLabel("◫")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet(f"font-size: 36px; color: {MUTED2}; background: transparent;")
        layout.addWidget(icon)

        title = QLabel("No sessions yet")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(f"color: {TEXT}; font-size: 17px; font-weight: 700;")
        layout.addWidget(title)

        subtitle = QLabel("Create a session to start organizing\nyour files, websites, and apps.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        layout.addWidget(subtitle)


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

        self._sidebar = Sidebar()
        self._sidebar.create_clicked.connect(self._create_session)
        h.addWidget(self._sidebar)

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
        layout.setContentsMargins(40, 36, 40, 36)
        layout.setSpacing(0)

        # Header
        header = QHBoxLayout()
        title = QLabel("Sessions")
        title.setStyleSheet(
            f"color: {TEXT}; font-size: 22px; font-weight: 700; letter-spacing: -0.4px;"
        )
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)
        layout.addSpacing(4)

        subtitle = QLabel("Click a session to view, edit, or restore it.")
        subtitle.setStyleSheet(f"color: {MUTED}; font-size: 13px;")
        layout.addWidget(subtitle)
        layout.addSpacing(28)

        # Sessions list card
        list_card = QWidget()
        list_card.setStyleSheet(f"""
            QWidget {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 14px;
            }}
        """)
        list_card_layout = QVBoxLayout(list_card)
        list_card_layout.setContentsMargins(0, 8, 0, 8)
        list_card_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._grid_widget = QWidget()
        self._grid_widget.setStyleSheet("background: transparent;")
        self._grid_layout = QVBoxLayout(self._grid_widget)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(0)
        self._grid_layout.addStretch()

        scroll.setWidget(self._grid_widget)
        list_card_layout.addWidget(scroll)
        layout.addWidget(list_card, 1)
        return page

    # ── Data ──

    def _load_sessions(self):
        while self._grid_layout.count() > 1:
            item = self._grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        sessions = db.get_all_sessions()
        self._sidebar.set_count(len(sessions))

        if not sessions:
            self._grid_layout.insertWidget(0, GridEmptyState())
            return

        for i, session in enumerate(sessions):
            stats = db.get_session_stats(session["id"])
            card = SessionCard(session, stats)
            card.open_clicked.connect(self._open_detail)
            card.delete_clicked.connect(self._delete_session)
            self._grid_layout.insertWidget(i, card)

            # Divider between items (not after last)
            if i < len(sessions) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setFixedHeight(1)
                div.setStyleSheet("background: rgba(0,0,0,0.05); margin: 0 18px;")
                self._grid_layout.insertWidget(i * 2 + 1, div)

    # ── Actions ──

    def _create_session(self):
        name, ok = QInputDialog.getText(
            self, "New Session", "Session name:",
            QLineEdit.EchoMode.Normal, ""
        )
        if ok and name.strip():
            session_id = db.create_session(name.strip())
            self._load_sessions()
            self._toast.show_toast("✦", f'"{name.strip()}" created')
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
            self._toast.show_toast("✕", f'"{session["name"]}" deleted')

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
