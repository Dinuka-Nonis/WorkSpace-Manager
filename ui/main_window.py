"""
ui/main_window.py — WorkSpace Manager main window.
Premium redesign: Helvetica Bold · Floating cards · Large fonts · No emoji · 
Custom session name dialog (pill/glass inspired) · Delete on cards.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QLineEdit, QMessageBox, QApplication, QDialog
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QTimer, QPropertyAnimation,
    QEasingCurve, QPoint
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QPen
)

import db
from ui.session_detail import SessionDetailPanel
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER,
    ACCENT, ACCENT2, ACCENT3, ACCENT_LIGHT,
    TEXT, TEXT2, MUTED, MUTED2,
    RED, RED_BG, SHADOW_SM, SHADOW_MD,
    FONT_DISPLAY, FONT_BODY
)

# SVG-style geometric icons (text-based, no emoji)
ICON_SESSIONS = "▣"
ICON_DOT      = "◆"


def _apply_shadow(widget, blur=24, color="#000000", alpha=16, dy=6):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    c = QColor(color)
    c.setAlpha(alpha)
    fx.setColor(c)
    fx.setOffset(0, dy)
    widget.setGraphicsEffect(fx)


# ── Custom "New Session" dialog — pill/glass inspired ────────────────────────

class NewSessionDialog(QDialog):
    """
    Inspired by the frosted-glass pill input bar from inspiration image 2.
    Full rounded pill shape, Helvetica Bold, large text, floating card feel.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("")
        self.setFixedSize(480, 160)
        self.setWindowFlags(
            Qt.WindowType.Dialog |
            Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._result_text = ""
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        # Floating card
        card = QWidget()
        card.setObjectName("newSessionCard")
        card.setStyleSheet(f"""
            #newSessionCard {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 24px;
            }}
        """)
        fx = QGraphicsDropShadowEffect(card)
        fx.setBlurRadius(50)
        fx.setColor(QColor(0, 0, 0, 55))
        fx.setOffset(0, 12)
        card.setGraphicsEffect(fx)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        # Label
        lbl = QLabel("Name your session")
        lbl.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {MUTED}; letter-spacing: 0.2px;")
        layout.addWidget(lbl)

        # Pill input row (inspired by image 2's glass search bar)
        pill_row = QHBoxLayout()
        pill_row.setSpacing(10)

        # The pill input container
        pill_container = QWidget()
        pill_container.setFixedHeight(54)
        pill_container.setStyleSheet(f"""
            QWidget {{
                background: {SURFACE2};
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 27px;
            }}
        """)
        pc_layout = QHBoxLayout(pill_container)
        pc_layout.setContentsMargins(20, 0, 8, 0)
        pc_layout.setSpacing(8)

        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("e.g. Morning Research")
        self._name_input.setFont(QFont(FONT_DISPLAY, 16, QFont.Weight.Bold))
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent;
                border: none;
                color: {TEXT};
                font-size: 17px;
                font-weight: 700;
                padding: 0;
            }}
        """)
        self._name_input.returnPressed.connect(self._accept)
        pc_layout.addWidget(self._name_input)

        # Dark pill "Create" button — inspired by image 2's dark mic pill
        create_btn = QPushButton("Create")
        create_btn.setFixedSize(88, 38)
        create_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        create_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                border-radius: 19px;
                color: white;
                font-weight: 700;
                font-size: 14px;
            }}
            QPushButton:hover {{ background: {ACCENT2}; }}
            QPushButton:pressed {{ background: {ACCENT3}; }}
        """)
        create_btn.clicked.connect(self._accept)
        pc_layout.addWidget(create_btn)

        pill_row.addWidget(pill_container)
        layout.addLayout(pill_row)

    def _accept(self):
        text = self._name_input.text().strip()
        if text:
            self._result_text = text
            self.accept()

    def get_name(self) -> str:
        return self._result_text

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()


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
        self._msg = ""

    def show_toast(self, msg: str, duration=2800):
        self._msg = msg
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - 160, screen.bottom() - 90)
        self.show(); self.raise_(); self.update()
        self._timer.start(duration)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(1, 1, self.width()-2, self.height()-2, 14, 14)
        p.fillPath(path, QColor(16, 16, 16, 230))
        p.setPen(QColor(255, 255, 255, 210))
        p.setFont(QFont(FONT_BODY, 13, QFont.Weight.Bold))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._msg)


# ── Animated sidebar indicator ────────────────────────────────────────────────

class AnimatedIndicator(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(3)
        self._anim = QPropertyAnimation(self, b"pos")
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

    def slide_to(self, y: int, h: int):
        self.setFixedHeight(h)
        target = QPoint(self.x(), y)
        if not self.isVisible():
            self.move(target); self.show(); return
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


# ── Session card ──────────────────────────────────────────────────────────────

class SessionCard(QWidget):
    open_clicked   = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    def __init__(self, session: dict, stats: dict, parent=None):
        super().__init__(parent)
        self.session_id = session["id"]
        self._hovered   = False
        self._del_btn   = None
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self.setFixedHeight(88)
        self._build(session, stats)

    def _build(self, session: dict, stats: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 20, 0)
        layout.setSpacing(18)

        # Icon placeholder — geometric shape, no emoji
        icon_box = QWidget()
        icon_box.setFixedSize(46, 46)
        icon_box.setStyleSheet(f"""
            background: {SURFACE2};
            border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 14px;
        """)
        # Icon letter from session name
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        letter = QLabel(session["name"][0].upper() if session["name"] else "S")
        letter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        letter.setFont(QFont(FONT_DISPLAY, 17, QFont.Weight.Black))
        letter.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(letter)
        layout.addWidget(icon_box)

        # Name + meta
        text_col = QVBoxLayout()
        text_col.setSpacing(5)

        name_lbl = QLabel(session["name"])
        name_lbl.setFont(QFont(FONT_DISPLAY, 17, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {TEXT};")
        text_col.addWidget(name_lbl)

        parts = []
        if stats["files"]: parts.append(f"{stats['files']} file{'s' if stats['files']!=1 else ''}")
        if stats["urls"]:  parts.append(f"{stats['urls']} URL{'s' if stats['urls']!=1 else ''}")
        if stats["apps"]:  parts.append(f"{stats['apps']} app{'s' if stats['apps']!=1 else ''}")

        try:
            dt = datetime.fromisoformat(session.get("updated_at", ""))
            date_str = dt.strftime("%b %d")
        except Exception:
            date_str = ""

        meta_parts = []
        if parts:    meta_parts.append("  ·  ".join(parts))
        if date_str: meta_parts.append(date_str)

        meta_lbl = QLabel("  ·  ".join(meta_parts) if meta_parts else "Empty session")
        meta_lbl.setFont(QFont(FONT_BODY, 13))
        meta_lbl.setStyleSheet(f"color: {MUTED};")
        text_col.addWidget(meta_lbl)
        layout.addLayout(text_col)
        layout.addStretch()

        # Delete button — always visible, minimal until hover
        del_btn = QPushButton("×")
        del_btn.setFixedSize(34, 34)
        del_btn.setToolTip("Delete session")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFont(QFont(FONT_BODY, 18, QFont.Weight.Light))
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1.5px solid transparent;
                border-radius: 10px;
                color: {MUTED2};
            }}
            QPushButton:hover {{
                background: {RED_BG};
                border-color: rgba(138,26,26,0.18);
                color: {RED};
            }}
            QPushButton:pressed {{
                background: rgba(138,26,26,0.13);
            }}
        """)
        del_btn.clicked.connect(self._on_delete_clicked)
        self._del_btn = del_btn
        layout.addWidget(del_btn)

    def _on_delete_clicked(self):
        self.delete_clicked.emit(self.session_id)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(e.pos())
            if child is self._del_btn or (child and child.parent() is self._del_btn):
                return
            self.open_clicked.emit(self.session_id)

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            path = QPainterPath()
            path.addRoundedRect(8, 4, self.width()-16, self.height()-8, 14, 14)
            p.fillPath(path, QColor(0, 0, 0, 22))


# ── Nav item ──────────────────────────────────────────────────────────────────

class NavItem(QWidget):
    clicked = pyqtSignal(object)

    def __init__(self, icon: str, label: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(44)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._active  = False
        self._hovered = False

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 16, 0)
        layout.setSpacing(12)

        self._icon_lbl = QLabel(icon)
        self._icon_lbl.setFixedWidth(22)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setFont(QFont(FONT_BODY, 13))
        self._icon_lbl.setStyleSheet(f"color: {MUTED}; background: transparent;")
        layout.addWidget(self._icon_lbl)

        self._label = QLabel(label)
        self._label.setFont(QFont(FONT_BODY, 15))
        self._label.setStyleSheet(f"color: {MUTED}; background: transparent;")
        layout.addWidget(self._label)
        layout.addStretch()

    def set_active(self, active: bool):
        self._active = active
        if active:
            self._label.setFont(QFont(FONT_DISPLAY, 15, QFont.Weight.Bold))
            self._label.setStyleSheet(f"color: {TEXT}; background: transparent;")
            self._icon_lbl.setStyleSheet(f"color: {TEXT}; background: transparent;")
        else:
            self._label.setFont(QFont(FONT_BODY, 15))
            self._label.setStyleSheet(f"color: {MUTED}; background: transparent;")
            self._icon_lbl.setStyleSheet(f"color: {MUTED}; background: transparent;")
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self)

    def enterEvent(self, e):
        self._hovered = True; self.update()

    def leaveEvent(self, e):
        self._hovered = False; self.update()

    def paintEvent(self, e):
        if self._hovered and not self._active:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(8, 3, self.width()-16, self.height()-6, 10, 10)
            p.fillPath(path, QColor(0, 0, 0, 14))


# ── Sidebar ───────────────────────────────────────────────────────────────────

class Sidebar(QWidget):
    create_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(240)
        self._count       = 0
        self._nav_items   = []
        self._active_item = None
        self._build()

    def paintEvent(self, e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(SURFACE))
        p.setPen(QPen(QColor(0, 0, 0, 14), 1))
        p.drawLine(self.width()-1, 0, self.width()-1, self.height())

    def set_count(self, n: int):
        self._count = n
        if hasattr(self, "_count_lbl"):
            self._count_lbl.setText(str(n))

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── Logo ──
        logo_area = QWidget()
        logo_area.setFixedHeight(76)
        ll = QHBoxLayout(logo_area)
        ll.setContentsMargins(20, 0, 20, 0)
        ll.setSpacing(10)

        dot = QLabel(ICON_DOT)
        dot.setFont(QFont(FONT_DISPLAY, 11, QFont.Weight.Black))
        dot.setStyleSheet(f"color: {TEXT}; background: transparent;")
        ll.addWidget(dot)

        brand = QLabel("WorkSpace")
        brand.setFont(QFont(FONT_DISPLAY, 17, QFont.Weight.Black))
        brand.setStyleSheet(f"color: {TEXT}; letter-spacing: -0.5px; background: transparent;")
        ll.addWidget(brand)
        ll.addStretch()
        layout.addWidget(logo_area)

        # Separator
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1); sep.setStyleSheet("background: rgba(0,0,0,0.07);")
        layout.addWidget(sep)
        layout.addSpacing(12)

        # ── MENU label ──
        menu_lbl = QLabel("MENU")
        menu_lbl.setFont(QFont(FONT_BODY, 10, QFont.Weight.Bold))
        menu_lbl.setStyleSheet(
            f"color: {MUTED2}; letter-spacing: 2px; padding-left: 20px; background: transparent;"
        )
        menu_lbl.setFixedHeight(24)
        layout.addWidget(menu_lbl)
        layout.addSpacing(4)

        # ── Nav container ──
        self._nav_container = QWidget()
        self._nav_container.setStyleSheet("background: transparent;")
        nav_vbox = QVBoxLayout(self._nav_container)
        nav_vbox.setContentsMargins(0, 0, 0, 0)
        nav_vbox.setSpacing(2)

        self._indicator = AnimatedIndicator(self._nav_container)
        self._indicator.hide()

        for icon, label in [(ICON_SESSIONS, "Sessions")]:
            item = NavItem(icon, label)
            item.clicked.connect(self._on_nav_clicked)
            self._nav_items.append(item)
            nav_vbox.addWidget(item)

        if self._nav_items:
            self._set_active(self._nav_items[0])

        layout.addWidget(self._nav_container)
        layout.addSpacing(16)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setFixedHeight(1); sep2.setStyleSheet("background: rgba(0,0,0,0.07);")
        layout.addWidget(sep2)
        layout.addSpacing(16)

        # ── Session count ──
        count_row = QHBoxLayout()
        count_row.setContentsMargins(20, 0, 20, 0)
        lbl = QLabel("Sessions")
        lbl.setFont(QFont(FONT_BODY, 14))
        lbl.setStyleSheet(f"color: {MUTED}; background: transparent;")
        count_row.addWidget(lbl)
        count_row.addStretch()
        self._count_lbl = QLabel(str(self._count))
        self._count_lbl.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._count_lbl.setStyleSheet(f"color: {MUTED2}; background: transparent;")
        count_row.addWidget(self._count_lbl)
        layout.addLayout(count_row)

        layout.addStretch()

        # ── Bottom: New Session pill button ──
        bottom = QWidget()
        bottom.setFixedHeight(84)
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(16, 16, 16, 16)

        btn = QPushButton("+ New Session")
        btn.setFixedHeight(46)
        btn.setFont(QFont(FONT_DISPLAY, 15, QFont.Weight.Bold))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                border-radius: 23px;
                color: white;
                letter-spacing: -0.2px;
            }}
            QPushButton:hover  {{ background: {ACCENT2}; }}
            QPushButton:pressed {{ background: {ACCENT3}; }}
        """)
        btn.clicked.connect(self.create_clicked.emit)
        _apply_shadow(btn, blur=20, alpha=50, dy=6)
        bl.addWidget(btn)
        layout.addWidget(bottom)

    def _on_nav_clicked(self, item):
        self._set_active(item)

    def _set_active(self, item):
        if self._active_item:
            self._active_item.set_active(False)
        item.set_active(True)
        self._active_item = item
        pos = item.mapTo(self._nav_container, QPoint(0, 0))
        self._indicator.slide_to(pos.y() + 11, item.height() - 22)
        self._indicator.raise_()


# ── Empty state ───────────────────────────────────────────────────────────────

class GridEmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(14)

        icon = QLabel(ICON_SESSIONS)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFont(QFont(FONT_BODY, 36))
        icon.setStyleSheet(f"color: {MUTED2}; background: transparent;")
        layout.addWidget(icon)

        title = QLabel("No sessions yet")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont(FONT_DISPLAY, 22, QFont.Weight.Black))
        title.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(title)

        sub = QLabel("Create a session to start organizing\nyour files, websites, and apps.")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont(FONT_BODY, 15))
        sub.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(sub)


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkSpace Manager")
        self.setMinimumSize(980, 660)
        self.resize(1160, 760)
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
        layout.setContentsMargins(48, 44, 48, 44)
        layout.setSpacing(0)

        # Header row
        header = QHBoxLayout()

        title = QLabel("Sessions")
        title.setFont(QFont(FONT_DISPLAY, 30, QFont.Weight.Black))
        title.setStyleSheet(f"color: {TEXT}; letter-spacing: -0.8px;")
        header.addWidget(title)
        header.addStretch()

        new_btn_hdr = QPushButton("+ New")
        new_btn_hdr.setFixedHeight(40)
        new_btn_hdr.setMinimumWidth(90)
        new_btn_hdr.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        new_btn_hdr.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 20px;
                color: {TEXT2};
                padding: 0 20px;
            }}
            QPushButton:hover  {{ background: {SURFACE2}; border-color: rgba(0,0,0,0.13); }}
            QPushButton:pressed {{ background: {SURFACE3}; }}
        """)
        _apply_shadow(new_btn_hdr, blur=12, alpha=12, dy=3)
        new_btn_hdr.clicked.connect(self._create_session)
        header.addWidget(new_btn_hdr)

        layout.addLayout(header)
        layout.addSpacing(6)

        subtitle = QLabel("Click a session to view, edit, or restore it.")
        subtitle.setFont(QFont(FONT_BODY, 14))
        subtitle.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(subtitle)
        layout.addSpacing(32)

        # Floating sessions card
        list_card = QWidget()
        list_card.setObjectName("listCard")
        list_card.setStyleSheet(f"""
            QWidget#listCard {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.06);
                border-radius: 20px;
            }}
        """)
        _apply_shadow(list_card, blur=36, alpha=18, dy=10)

        list_card_layout = QVBoxLayout(list_card)
        list_card_layout.setContentsMargins(0, 12, 0, 12)
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
            self._grid_layout.insertWidget(i * 2, card)

            if i < len(sessions) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setFixedHeight(1)
                div.setStyleSheet("background: rgba(0,0,0,0.05); margin: 0 24px;")
                self._grid_layout.insertWidget(i * 2 + 1, div)

    # ── Actions ──

    def _create_session(self):
        dlg = NewSessionDialog(self)
        # Center on parent
        geo = self.geometry()
        dlg.move(
            geo.center().x() - dlg.width() // 2,
            geo.center().y() - dlg.height() // 2
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.get_name()
            if name:
                session_id = db.create_session(name)
                self._load_sessions()
                self._toast.show_toast(f'"{name}" created')
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
            self._toast.show_toast(f'"{session["name"]}" deleted')

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
