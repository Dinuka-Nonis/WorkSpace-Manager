"""
ui/session_detail.py — Session detail panel.
Premium redesign: Helvetica Bold · Large fonts · Floating cards · No emoji ·
Proper button sizing · Geometric icons.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QGraphicsDropShadowEffect, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QPen

import db
import restore as restorer
from core.launcher import open_item, icon_for_item
from ui.add_item_dialog import AddItemDialog
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER,
    ACCENT, ACCENT2, ACCENT3,
    TEXT, TEXT2, MUTED, MUTED2,
    GREEN, AMBER, RED, RED_BG, SHADOW_SM,
    FONT_DISPLAY, FONT_BODY
)

# Geometric type icons — no emoji
ICON_FILE    = "▭"
ICON_WEB     = "○"
ICON_APP     = "◈"
ICON_GENERIC = "▣"


def _apply_shadow(widget, blur=16, alpha=16, dy=4):
    fx = QGraphicsDropShadowEffect(widget)
    fx.setBlurRadius(blur)
    c = QColor(0, 0, 0); c.setAlpha(alpha)
    fx.setColor(c); fx.setOffset(0, dy)
    widget.setGraphicsEffect(fx)


def _icon_for_item_geo(item: dict) -> str:
    t = item.get("type", "")
    if t == "file": return ICON_FILE
    if t == "url":  return ICON_WEB
    if t == "app":  return ICON_APP
    return ICON_GENERIC


# ── Stat badge ────────────────────────────────────────────────────────────────

class StatBadge(QWidget):
    def __init__(self, label_text: str, count: int, sub: str, parent=None):
        super().__init__(parent)
        self.setFixedHeight(72)
        self.setMinimumWidth(110)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 14, 18, 14)
        layout.setSpacing(14)

        # Geometric icon box
        icon_box = QWidget()
        icon_box.setFixedSize(38, 38)
        icon_box.setStyleSheet(f"""
            background: {SURFACE2};
            border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 11px;
        """)
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        sym = QLabel(label_text)
        sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sym.setFont(QFont(FONT_BODY, 14, QFont.Weight.Bold))
        sym.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(sym)
        layout.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        count_lbl = QLabel(str(count))
        count_lbl.setFont(QFont(FONT_DISPLAY, 20, QFont.Weight.Black))
        count_lbl.setStyleSheet(f"color: {TEXT};")
        text_col.addWidget(count_lbl)

        label_lbl = QLabel(sub)
        label_lbl.setFont(QFont(FONT_BODY, 13))
        label_lbl.setStyleSheet(f"color: {MUTED};")
        text_col.addWidget(label_lbl)
        layout.addLayout(text_col)
        layout.addStretch()

        self.setStyleSheet(f"""
            QWidget {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.06);
                border-radius: 16px;
            }}
        """)
        _apply_shadow(self, blur=16, alpha=12, dy=4)


# ── Item row ──────────────────────────────────────────────────────────────────

class ItemRow(QWidget):
    open_clicked   = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item_id  = item["id"]
        self._hovered = False
        self.setFixedHeight(70)
        self.setMouseTracking(True)
        self._del_btn = None
        self._build(item)

    def _build(self, item: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(20, 0, 16, 0)
        layout.setSpacing(16)

        # Geometric icon box
        icon_box = QWidget()
        icon_box.setFixedSize(38, 38)
        icon_box.setStyleSheet(f"""
            background: {SURFACE2};
            border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 11px;
        """)
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        sym = QLabel(_icon_for_item_geo(item))
        sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sym.setFont(QFont(FONT_BODY, 13, QFont.Weight.Bold))
        sym.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(sym)
        layout.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(4)

        name_lbl = QLabel(item["label"])
        name_lbl.setFont(QFont(FONT_DISPLAY, 15, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {TEXT};")
        name_lbl.setMaximumWidth(420)
        text_col.addWidget(name_lbl)

        path = item["path_or_url"]
        short = ("…" + path[-52:]) if len(path) > 55 else path
        path_lbl = QLabel(short)
        path_lbl.setFont(QFont(FONT_BODY, 12))
        path_lbl.setStyleSheet(f"color: {MUTED};")
        path_lbl.setToolTip(path)
        text_col.addWidget(path_lbl)
        layout.addLayout(text_col)
        layout.addStretch()

        # Last opened badge
        last = item.get("last_opened_at")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                badge_txt = dt.strftime("%b %d")
            except Exception:
                badge_txt = "—"
            badge = QLabel(badge_txt)
            badge.setFont(QFont(FONT_BODY, 12, QFont.Weight.Medium))
            badge.setStyleSheet(f"""
                color: {MUTED};
                background: {SURFACE2};
                border: 1.5px solid rgba(0,0,0,0.07);
                border-radius: 8px;
                padding: 3px 10px;
            """)
            layout.addWidget(badge)

        # Open button — fixed wide enough for text
        open_btn = QPushButton("Open")
        open_btn.setFixedSize(76, 36)
        open_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                border-radius: 18px;
                color: white;
            }}
            QPushButton:hover  {{ background: {ACCENT2}; }}
            QPushButton:pressed {{ background: {ACCENT3}; }}
        """)
        open_btn.clicked.connect(lambda: self.open_clicked.emit(self.item_id))
        layout.addWidget(open_btn)

        # Delete button
        del_btn = QPushButton("×")
        del_btn.setFixedSize(34, 34)
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
        """)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.item_id))
        self._del_btn = del_btn
        layout.addWidget(del_btn)

    def enterEvent(self, e):
        self._hovered = True; self.update()

    def leaveEvent(self, e):
        self._hovered = False; self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            path = QPainterPath()
            path.addRoundedRect(6, 3, self.width()-12, self.height()-6, 12, 12)
            p.fillPath(path, QColor(0, 0, 0, 18))


# ── Section header ────────────────────────────────────────────────────────────

class SectionHeader(QLabel):
    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setFixedHeight(36)
        self.setFont(QFont(FONT_BODY, 11, QFont.Weight.Bold))
        self.setStyleSheet(f"""
            color: {MUTED};
            letter-spacing: 1.5px;
            padding-left: 20px;
        """)


# ── Empty state ───────────────────────────────────────────────────────────────

class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(12)

        icon = QLabel(ICON_GENERIC)
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setFont(QFont(FONT_BODY, 30))
        icon.setStyleSheet(f"color: {MUTED2}; background: transparent;")
        layout.addWidget(icon)

        msg = QLabel("No items yet")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setFont(QFont(FONT_DISPLAY, 18, QFont.Weight.Black))
        msg.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(msg)

        hint = QLabel("Add files, URLs, or apps using the button above")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setFont(QFont(FONT_BODY, 14))
        hint.setStyleSheet(f"color: {MUTED};")
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
        layout.setContentsMargins(48, 40, 48, 40)
        layout.setSpacing(0)

        # ── Header row: Back button ──
        header = QHBoxLayout()
        header.setSpacing(16)

        back_btn = QPushButton("← Back")
        back_btn.setFixedHeight(40)
        back_btn.setMinimumWidth(100)
        back_btn.setFont(QFont(FONT_BODY, 14, QFont.Weight.Bold))
        back_btn.setStyleSheet(f"""
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
        _apply_shadow(back_btn, blur=12, alpha=10, dy=3)
        back_btn.clicked.connect(self.closed.emit)
        header.addWidget(back_btn)
        header.addStretch()

        layout.addLayout(header)
        layout.addSpacing(28)

        # ── Session title row ──
        title_row = QHBoxLayout()
        title_row.setSpacing(18)

        # Icon box with session initial
        self._icon_box = QWidget()
        self._icon_box.setFixedSize(58, 58)
        self._icon_box.setStyleSheet(f"""
            background: {SURFACE2};
            border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 17px;
        """)
        il = QHBoxLayout(self._icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        self._icon_letter = QLabel("S")
        self._icon_letter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_letter.setFont(QFont(FONT_DISPLAY, 22, QFont.Weight.Black))
        self._icon_letter.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(self._icon_letter)
        title_row.addWidget(self._icon_box)

        name_col = QVBoxLayout()
        name_col.setSpacing(4)
        self._name_lbl = QLabel("")
        self._name_lbl.setFont(QFont(FONT_DISPLAY, 26, QFont.Weight.Black))
        self._name_lbl.setStyleSheet(f"color: {TEXT}; letter-spacing: -0.5px;")
        name_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setFont(QFont(FONT_BODY, 14))
        self._meta_lbl.setStyleSheet(f"color: {MUTED};")
        name_col.addWidget(self._meta_lbl)
        title_row.addLayout(name_col)
        title_row.addStretch()

        # Action buttons
        self._restore_btn = QPushButton("Restore All")
        self._restore_btn.setObjectName("accentBtn")
        self._restore_btn.setFixedHeight(44)
        self._restore_btn.setMinimumWidth(140)
        self._restore_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._restore_btn.clicked.connect(self._restore_all)
        _apply_shadow(self._restore_btn, blur=16, alpha=44, dy=5)
        title_row.addWidget(self._restore_btn)

        add_btn = QPushButton("+ Add Item")
        add_btn.setFixedHeight(44)
        add_btn.setMinimumWidth(120)
        add_btn.setFont(QFont(FONT_BODY, 14, QFont.Weight.Bold))
        add_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 22px;
                color: {TEXT2};
                padding: 0 22px;
            }}
            QPushButton:hover  {{ background: {SURFACE2}; border-color: rgba(0,0,0,0.13); }}
            QPushButton:pressed {{ background: {SURFACE3}; }}
        """)
        _apply_shadow(add_btn, blur=12, alpha=12, dy=3)
        add_btn.clicked.connect(self._open_add_dialog)
        title_row.addWidget(add_btn)

        layout.addLayout(title_row)
        layout.addSpacing(28)

        # Stats row
        self._stats_row = QHBoxLayout()
        self._stats_row.setSpacing(14)
        layout.addLayout(self._stats_row)
        layout.addSpacing(28)

        # Floating item list card
        list_card = QWidget()
        list_card.setObjectName("listCard")
        list_card.setStyleSheet(f"""
            QWidget#listCard {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.06);
                border-radius: 20px;
            }}
        """)
        _apply_shadow(list_card, blur=36, alpha=16, dy=10)

        lc_layout = QVBoxLayout(list_card)
        lc_layout.setContentsMargins(0, 10, 0, 10)
        lc_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent; border: none;")

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()
        scroll.setWidget(self._list_container)
        lc_layout.addWidget(scroll)
        layout.addWidget(list_card, 1)

    def refresh(self):
        session = db.get_session(self.session_id)
        if not session:
            return

        name = session["name"]
        self._icon_letter.setText(name[0].upper() if name else "S")
        self._name_lbl.setText(name)

        stats = db.get_session_stats(self.session_id)
        parts = []
        if stats["files"]: parts.append(f"{stats['files']} file{'s' if stats['files']!=1 else ''}")
        if stats["urls"]:  parts.append(f"{stats['urls']} URL{'s' if stats['urls']!=1 else ''}")
        if stats["apps"]:  parts.append(f"{stats['apps']} app{'s' if stats['apps']!=1 else ''}")
        self._meta_lbl.setText("  ·  ".join(parts) if parts else "Empty session")

        # Rebuild stats badges
        while self._stats_row.count():
            item = self._stats_row.takeAt(0)
            if item.widget(): item.widget().deleteLater()

        if stats["total"]:
            for sym, count, label in [
                ("F", stats["files"], "Files"),
                ("W", stats["urls"],  "Websites"),
                ("A", stats["apps"],  "Apps"),
            ]:
                if count:
                    self._stats_row.addWidget(StatBadge(sym, count, label))
            self._stats_row.addStretch()

        # Rebuild item list
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()

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
            for i, item in enumerate(grp):
                row = ItemRow(item)
                row.open_clicked.connect(self._open_single)
                row.delete_clicked.connect(self._delete_item)
                self._list_layout.insertWidget(idx, row)
                idx += 1
                if i < len(grp) - 1:
                    div = QFrame()
                    div.setFrameShape(QFrame.Shape.HLine)
                    div.setFixedHeight(1)
                    div.setStyleSheet("background: rgba(0,0,0,0.05); margin: 0 20px;")
                    self._list_layout.insertWidget(idx, div)
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
            self._meta_lbl.setText(f"Could not open: {err}")
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
            self._restore_btn.setText(f"Opened {opened}")
            self._restore_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {GREEN};
                    border: none; border-radius: 22px;
                    color: white; font-weight: 700; padding: 0 22px;
                    font-size: 14px;
                }}
            """)
        else:
            self._restore_btn.setText(f"{opened}/{total} opened")
            self._restore_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {AMBER};
                    border: none; border-radius: 22px;
                    color: white; font-weight: 700; padding: 0 22px;
                    font-size: 14px;
                }}
            """)
        self.refresh()
        self._restore_timer.start(3000)

    def _reset_restore_btn(self):
        self._restore_btn.setText("Restore All")
        self._restore_btn.setStyleSheet("")
        self._restore_btn.setObjectName("accentBtn")
        self._restore_btn.style().unpolish(self._restore_btn)
        self._restore_btn.style().polish(self._restore_btn)
        self._restore_btn.setEnabled(True)
