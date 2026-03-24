"""
ui/session_detail.py — Session detail panel.
Uiverse-inspired: white glass cards, gradient accents, soft shadows.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGraphicsDropShadowEffect, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QLinearGradient, QPen

import db
import restore as restorer
from core.launcher import open_item, icon_for_item
from ui.add_item_dialog import AddItemDialog
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, GLASS, BORDER,
    ACCENT, ACCENT2, ACCENT3, ACCENT_LIGHT, ACCENT_MED,
    GRAD_START, GRAD_END, TEXT, TEXT2, MUTED, MUTED2,
    GREEN, GREEN_BG, AMBER, AMBER_BG, RED, RED_BG, SHADOW_SM, SHADOW_MD
)


def _shadow(widget, radius=16, color=SHADOW_SM, dy=3):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(radius)
    fx.setColor(QColor(color))
    fx.setOffset(0, dy)
    widget.setGraphicsEffect(fx)


# ── Stat badge ────────────────────────────────────────────────────────────────

class StatBadge(QWidget):
    def __init__(self, icon: str, count: int, label: str, color: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(64)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(10)

        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(36, 36)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: {color}18;
            border: 1.5px solid {color}33;
            border-radius: 10px;
            font-size: 18px;
        """)
        layout.addWidget(icon_lbl)

        text_col = QVBoxLayout()
        text_col.setSpacing(1)
        count_lbl = QLabel(str(count))
        count_lbl.setStyleSheet(
            f"color: {color}; font-size: 18px; font-weight: 800;"
        )
        text_col.addWidget(count_lbl)
        label_lbl = QLabel(label)
        label_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        text_col.addWidget(label_lbl)
        layout.addLayout(text_col)
        layout.addStretch()

        self.setStyleSheet(f"""
            QWidget {{
                background: {SURFACE};
                border: 1.5px solid {color}22;
                border-radius: 14px;
            }}
        """)
        _shadow(self, radius=12, color=SHADOW_SM, dy=2)


# ── Item row ──────────────────────────────────────────────────────────────────

class ItemRow(QWidget):
    open_clicked   = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    TYPE_COLORS = {
        "file": "#6c63ff",
        "url":  "#10b981",
        "app":  "#f59e0b",
    }

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item_id = item["id"]
        self._item   = item
        self.setFixedHeight(60)
        self._hovered = False
        self.setMouseTracking(True)
        self._build(item)

    def _build(self, item: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        color = self.TYPE_COLORS.get(item["type"], ACCENT)
        icon  = icon_for_item(item)

        # Icon pill
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(34, 34)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: {color}18;
            border: 1.5px solid {color}33;
            border-radius: 9px;
            font-size: 16px;
        """)
        layout.addWidget(icon_lbl)

        # Label + path
        text_col = QVBoxLayout()
        text_col.setSpacing(2)
        name_lbl = QLabel(item["label"])
        name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 13px; font-weight: 600;"
        )
        name_lbl.setMaximumWidth(340)
        text_col.addWidget(name_lbl)

        path = item["path_or_url"]
        short = ("…" + path[-50:]) if len(path) > 53 else path
        path_lbl = QLabel(short)
        path_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        path_lbl.setToolTip(path)
        text_col.addWidget(path_lbl)
        layout.addLayout(text_col)
        layout.addStretch()

        # Last opened chip
        last = item.get("last_opened_at")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                badge_txt = dt.strftime("%b %d")
            except Exception:
                badge_txt = "opened"
            badge = QLabel(f"🕐 {badge_txt}")
            badge.setStyleSheet(f"""
                color: {MUTED};
                background: {SURFACE3};
                border-radius: 8px;
                padding: 2px 8px;
                font-size: 10px;
                font-weight: 600;
            """)
            layout.addWidget(badge)

        # Open button
        open_btn = QPushButton("Open")
        open_btn.setFixedSize(62, 30)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                    stop:0 {GRAD_START}, stop:1 {GRAD_END});
                border: none; border-radius: 8px;
                color: white; font-size: 12px; font-weight: 700;
            }}
            QPushButton:hover {{ opacity: 0.85; }}
        """)
        open_btn.clicked.connect(lambda: self.open_clicked.emit(self.item_id))
        layout.addWidget(open_btn)

        # Delete button
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(30, 30)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1.5px solid {BORDER};
                border-radius: 8px;
                color: {MUTED};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: {RED_BG};
                border-color: rgba(239,68,68,0.4);
                color: {RED};
            }}
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.item_id))
        layout.addWidget(del_btn)

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
        color = QColor(SURFACE3) if self._hovered else QColor(SURFACE)
        p.fillPath(path, color)
        p.setPen(QPen(QColor(BORDER), 1.5))
        p.drawPath(path)


# ── Section header ────────────────────────────────────────────────────────────

class SectionHeader(QLabel):
    COLORS = {"FILES": "#6c63ff", "WEBSITES": "#10b981", "APPLICATIONS": "#f59e0b"}

    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        color = self.COLORS.get(label, ACCENT)
        self.setFixedHeight(30)
        self.setStyleSheet(f"""
            color: {color};
            font-size: 10px;
            font-weight: 800;
            letter-spacing: 2.5px;
            padding-left: 4px;
        """)


# ── Empty state ───────────────────────────────────────────────────────────────

class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)

        icon = QLabel("📂")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 40px; background: transparent;")
        layout.addWidget(icon)

        msg = QLabel("No items yet")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {TEXT}; font-size: 15px; font-weight: 700;")
        layout.addWidget(msg)

        hint = QLabel("Add files, URLs, or apps using the button below")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        layout.addWidget(hint)


# ── Main panel ────────────────────────────────────────────────────────────────

class SessionDetailPanel(QWidget):
    closed          = pyqtSignal()
    session_changed = pyqtSignal()

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._restore_timer = QTimer(self)
        self._restore_timer.setSingleShot(True)
        self._restore_timer.timeout.connect(self._reset_restore_btn)
        self._build()
        self.refresh()

    def _build(self):
        self.setStyleSheet(f"background: {BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(36, 28, 36, 28)
        layout.setSpacing(0)

        # ── Header ──
        header = QHBoxLayout()
        header.setSpacing(14)

        self._icon_lbl = QLabel("")
        self._icon_lbl.setFixedSize(52, 52)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet(f"""
            background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 {GRAD_START}22, stop:1 {GRAD_END}22);
            border: 2px solid {GRAD_START}33;
            border-radius: 14px;
            font-size: 26px;
        """)
        header.addWidget(self._icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(3)
        self._name_lbl = QLabel("")
        self._name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 20px; font-weight: 800; letter-spacing: -0.4px;"
        )
        title_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        title_col.addWidget(self._meta_lbl)
        header.addLayout(title_col)
        header.addStretch()

        back_btn = QPushButton("← Back")
        back_btn.setObjectName("ghostBtn")
        back_btn.setFixedHeight(36)
        back_btn.clicked.connect(self.closed.emit)
        header.addWidget(back_btn)

        layout.addLayout(header)
        layout.addSpacing(22)

        # ── Stats row ──
        self._stats_row = QHBoxLayout()
        self._stats_row.setSpacing(12)
        layout.addLayout(self._stats_row)
        layout.addSpacing(22)

        # ── Action bar ──
        actions = QHBoxLayout()
        actions.setSpacing(10)
        self._restore_btn = QPushButton("▶  Restore All")
        self._restore_btn.setObjectName("accentBtn")
        self._restore_btn.setFixedHeight(40)
        self._restore_btn.clicked.connect(self._restore_all)
        actions.addWidget(self._restore_btn)

        add_btn = QPushButton("＋  Add Item")
        add_btn.setFixedHeight(40)
        add_btn.clicked.connect(self._open_add_dialog)
        actions.addWidget(add_btn)
        actions.addStretch()
        layout.addLayout(actions)
        layout.addSpacing(20)

        # ── Item list ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(6)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_container)
        layout.addWidget(scroll)

    def refresh(self):
        session = db.get_session(self.session_id)
        if not session:
            return

        self._icon_lbl.setText(session.get("icon", "🗂"))
        self._name_lbl.setText(session["name"])

        stats = db.get_session_stats(self.session_id)
        parts = []
        if stats["files"]: parts.append(f"{stats['files']} file{'s' if stats['files']!=1 else ''}")
        if stats["urls"]:  parts.append(f"{stats['urls']} URL{'s' if stats['urls']!=1 else ''}")
        if stats["apps"]:  parts.append(f"{stats['apps']} app{'s' if stats['apps']!=1 else ''}")
        self._meta_lbl.setText("  ·  ".join(parts) if parts else "Empty session")

        # Rebuild stats badges
        while self._stats_row.count():
            item = self._stats_row.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if stats["total"]:
            badges = [
                ("📄", stats["files"], "Files",    "#6c63ff"),
                ("🌐", stats["urls"],  "Websites", "#10b981"),
                ("⚙️", stats["apps"],  "Apps",     "#f59e0b"),
            ]
            for icon, count, label, color in badges:
                if count:
                    b = StatBadge(icon, count, label, color)
                    self._stats_row.addWidget(b)
            self._stats_row.addStretch()

        # Rebuild item list
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = stats["items"]
        if not items:
            self._list_layout.insertWidget(0, EmptyState())
            return

        groups = {"file": [], "url": [], "app": []}
        for it in items:
            groups[it["type"]].append(it)

        group_labels = {"file": "FILES", "url": "WEBSITES", "app": "APPLICATIONS"}
        idx = 0
        for gtype in ("file", "url", "app"):
            grp = groups[gtype]
            if not grp:
                continue
            self._list_layout.insertWidget(idx, SectionHeader(group_labels[gtype]))
            idx += 1
            for item in grp:
                row = ItemRow(item)
                row.open_clicked.connect(self._open_single)
                row.delete_clicked.connect(self._delete_item)
                self._list_layout.insertWidget(idx, row)
                idx += 1
            spacer = QWidget()
            spacer.setFixedHeight(6)
            self._list_layout.insertWidget(idx, spacer)
            idx += 1

    def _open_add_dialog(self):
        dlg = AddItemDialog(self.session_id, self)
        dlg.item_added.connect(lambda _: (self.refresh(), self.session_changed.emit()))
        dlg.exec()

    def _open_single(self, item_id: int):
        item = next((i for i in db.get_items(self.session_id) if i["id"] == item_id), None)
        if not item:
            return
        success, err = open_item(item)
        if success:
            db.mark_item_opened(item_id)
            self.refresh()
        else:
            self._meta_lbl.setText(f"⚠ {err}")
            QTimer.singleShot(3000, self.refresh)

    def _delete_item(self, item_id: int):
        db.delete_item(item_id)
        self.refresh()
        self.session_changed.emit()

    def _restore_all(self):
        self._restore_btn.setEnabled(False)
        self._restore_btn.setText("Opening…")
        results = restorer.restore_session(self.session_id)
        opened, total, failed = results["opened"], results["total"], results["failed"]
        if failed == 0:
            self._restore_btn.setText(f"✓  Opened {opened}")
            self._restore_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {GREEN}, stop:1 #34d399);
                    border: none; border-radius: 10px;
                    color: white; font-weight: 700; padding: 9px 22px;
                }}
            """)
        else:
            self._restore_btn.setText(f"⚠  {opened}/{total} opened")
            self._restore_btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
                        stop:0 {AMBER}, stop:1 #fcd34d);
                    border: none; border-radius: 10px;
                    color: white; font-weight: 700; padding: 9px 22px;
                }}
            """)
        self.refresh()
        self._restore_timer.start(3000)

    def _reset_restore_btn(self):
        self._restore_btn.setText("▶  Restore All")
        self._restore_btn.setStyleSheet("")
        self._restore_btn.setObjectName("accentBtn")
        self._restore_btn.style().unpolish(self._restore_btn)
        self._restore_btn.style().polish(self._restore_btn)
        self._restore_btn.setEnabled(True)
