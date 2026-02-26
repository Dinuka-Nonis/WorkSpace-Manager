"""
ui/session_detail.py — Panel showing the items inside a session.

Displayed when the user clicks a session card in the main window.
Shows a list of items (file/url/app) with open and delete per item.
Has a "Restore All" button and an "Add Item" button.
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QSizePolicy, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont

import db
import restore as restorer
from core.launcher import open_item, icon_for_item
from ui.add_item_dialog import AddItemDialog
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER, ACCENT, ACCENT2, ACCENT_DIM,
    TEXT, MUTED, MUTED2, GREEN, RED, AMBER, WHITE_005, ACCENT_010, ACCENT_020
)


# ── Individual item row ───────────────────────────────────────────────────────

class ItemRow(QWidget):
    open_clicked   = pyqtSignal(int)   # item_id
    delete_clicked = pyqtSignal(int)   # item_id

    def __init__(self, item: dict, parent=None):
        super().__init__(parent)
        self.item_id = item["id"]
        self._item   = item
        self.setFixedHeight(56)
        self._hovered = False
        self.setMouseTracking(True)
        self._build(item)

    def _build(self, item: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(10)

        # Icon
        icon = icon_for_item(item)
        icon_lbl = QLabel(icon)
        icon_lbl.setFixedSize(32, 32)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet(f"""
            background: {SURFACE3};
            border-radius: 8px;
            font-size: 16px;
        """)
        layout.addWidget(icon_lbl)

        # Label + path
        text_col = QVBoxLayout()
        text_col.setSpacing(1)

        name_lbl = QLabel(item["label"])
        name_lbl.setStyleSheet(f"color: {TEXT}; font-size: 13px; font-weight: 600;")
        name_lbl.setMaximumWidth(280)
        name_lbl.setToolTip(item["path_or_url"])
        text_col.addWidget(name_lbl)

        path_lbl = QLabel(item["path_or_url"])
        path_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        path_lbl.setMaximumWidth(280)
        # Truncate display but keep full in tooltip
        metrics_text = item["path_or_url"]
        if len(metrics_text) > 55:
            metrics_text = "…" + metrics_text[-52:]
        path_lbl.setText(metrics_text)
        path_lbl.setToolTip(item["path_or_url"])
        text_col.addWidget(path_lbl)

        layout.addLayout(text_col)
        layout.addStretch()

        # Last opened badge
        last = item.get("last_opened_at")
        if last:
            try:
                dt = datetime.fromisoformat(last)
                badge_text = dt.strftime("%b %d")
            except Exception:
                badge_text = "opened"
            badge = QLabel(badge_text)
            badge.setStyleSheet(f"""
                color: {MUTED};
                background: {SURFACE3};
                border-radius: 6px;
                padding: 2px 8px;
                font-size: 10px;
            """)
            layout.addWidget(badge)

        # Open button
        open_btn = QPushButton("Open")
        open_btn.setFixedSize(60, 30)
        open_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT_010};
                border: 1px solid {ACCENT};
                border-radius: 7px;
                color: {ACCENT2};
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: {ACCENT_020};
            }}
        """)
        open_btn.clicked.connect(lambda: self.open_clicked.emit(self.item_id))
        layout.addWidget(open_btn)

        # Delete button
        del_btn = QPushButton("✕")
        del_btn.setFixedSize(30, 30)
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {BORDER};
                border-radius: 7px;
                color: {MUTED};
                font-size: 12px;
            }}
            QPushButton:hover {{
                background: rgba(248,113,113,0.15);
                border-color: {RED};
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
        path.addRoundedRect(0, 0, self.width(), self.height(), 10, 10)
        if self._hovered:
            p.fillPath(path, QColor(SURFACE3))
        else:
            p.fillPath(path, QColor(SURFACE2))


# ── Type section header ───────────────────────────────────────────────────────

class SectionHeader(QLabel):
    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setFixedHeight(28)
        self.setStyleSheet(f"""
            color: {MUTED};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 2px;
            padding-left: 4px;
        """)


# ── Empty state ───────────────────────────────────────────────────────────────

class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)

        icon = QLabel("🗂")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("font-size: 36px; background: transparent;")
        layout.addWidget(icon)

        msg = QLabel("No items yet")
        msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        msg.setStyleSheet(f"color: {MUTED}; font-size: 14px; font-weight: 600;")
        layout.addWidget(msg)

        hint = QLabel("Add files, URLs, or apps to this session\nusing the button below")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setStyleSheet(f"color: {MUTED2}; font-size: 12px;")
        layout.addWidget(hint)


# ── Main session detail panel ─────────────────────────────────────────────────

class SessionDetailPanel(QWidget):
    closed          = pyqtSignal()
    session_changed = pyqtSignal()   # something was added/deleted

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._restore_feedback_timer = QTimer(self)
        self._restore_feedback_timer.setSingleShot(True)
        self._restore_feedback_timer.timeout.connect(self._reset_restore_btn)
        self._build()
        self.refresh()

    def _build(self):
        self.setStyleSheet(f"background: {BG};")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(0)

        # ── Header ──
        header = QHBoxLayout()
        header.setSpacing(12)

        self._icon_lbl = QLabel("")
        self._icon_lbl.setFixedSize(44, 44)
        self._icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_lbl.setStyleSheet(f"""
            background: {ACCENT_010};
            border-radius: 12px;
            font-size: 22px;
        """)
        header.addWidget(self._icon_lbl)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self._name_lbl = QLabel("")
        self._name_lbl.setStyleSheet(
            f"color: {TEXT}; font-size: 18px; font-weight: 700; letter-spacing: -0.3px;"
        )
        title_col.addWidget(self._name_lbl)
        self._meta_lbl = QLabel("")
        self._meta_lbl.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        title_col.addWidget(self._meta_lbl)
        header.addLayout(title_col)
        header.addStretch()

        back_btn = QPushButton("← Back")
        back_btn.setFixedHeight(34)
        back_btn.setObjectName("ghostBtn")
        back_btn.clicked.connect(self.closed.emit)
        header.addWidget(back_btn)

        layout.addLayout(header)
        layout.addSpacing(20)

        # ── Action bar ──
        actions = QHBoxLayout()
        actions.setSpacing(10)

        self._restore_btn = QPushButton("▶  Restore All")
        self._restore_btn.setObjectName("accentBtn")
        self._restore_btn.setFixedHeight(38)
        self._restore_btn.clicked.connect(self._restore_all)
        actions.addWidget(self._restore_btn)

        add_btn = QPushButton("＋  Add Item")
        add_btn.setFixedHeight(38)
        add_btn.clicked.connect(self._open_add_dialog)
        actions.addWidget(add_btn)

        actions.addStretch()
        layout.addLayout(actions)
        layout.addSpacing(18)

        # ── Scrollable item list ──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._list_container = QWidget()
        self._list_container.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_container)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(4)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_container)
        layout.addWidget(scroll)

    def refresh(self):
        """Reload data from DB and rebuild the item list."""
        session = db.get_session(self.session_id)
        if not session:
            return

        self._icon_lbl.setText(session.get("icon", "🗂"))
        self._name_lbl.setText(session["name"])

        stats = db.get_session_stats(self.session_id)
        parts = []
        if stats["files"]:  parts.append(f"{stats['files']} file{'s' if stats['files'] != 1 else ''}")
        if stats["urls"]:   parts.append(f"{stats['urls']} URL{'s' if stats['urls'] != 1 else ''}")
        if stats["apps"]:   parts.append(f"{stats['apps']} app{'s' if stats['apps'] != 1 else ''}")
        self._meta_lbl.setText("  ·  ".join(parts) if parts else "Empty session")

        # Clear existing rows (preserve the trailing stretch)
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        items = stats["items"]
        if not items:
            empty = EmptyState()
            self._list_layout.insertWidget(0, empty)
            return

        # Group by type
        groups = {"file": [], "url": [], "app": []}
        for it in items:
            groups[it["type"]].append(it)

        group_labels = {"file": "FILES", "url": "WEBSITES", "app": "APPLICATIONS"}
        idx = 0
        for gtype in ("file", "url", "app"):
            grp = groups[gtype]
            if not grp:
                continue

            header = SectionHeader(group_labels[gtype])
            self._list_layout.insertWidget(idx, header)
            idx += 1

            for item in grp:
                row = ItemRow(item)
                row.open_clicked.connect(self._open_single)
                row.delete_clicked.connect(self._delete_item)
                self._list_layout.insertWidget(idx, row)
                idx += 1

            spacer = QWidget()
            spacer.setFixedHeight(8)
            self._list_layout.insertWidget(idx, spacer)
            idx += 1

    # ── Actions ──

    def _open_add_dialog(self):
        dlg = AddItemDialog(self.session_id, self)
        dlg.item_added.connect(self._on_item_added)
        dlg.exec()

    def _on_item_added(self, item_id: int):
        self.refresh()
        self.session_changed.emit()

    def _open_single(self, item_id: int):
        item = next((i for i in db.get_items(self.session_id) if i["id"] == item_id), None)
        if not item:
            return
        success, err = open_item(item)
        if success:
            db.mark_item_opened(item_id)
            self.refresh()
        else:
            # Show error briefly in meta label
            self._meta_lbl.setText(f"⚠ Could not open: {err}")
            QTimer.singleShot(3000, self.refresh)

    def _delete_item(self, item_id: int):
        db.delete_item(item_id)
        self.refresh()
        self.session_changed.emit()

    def _restore_all(self):
        self._restore_btn.setEnabled(False)
        self._restore_btn.setText("Opening…")

        results = restorer.restore_session(self.session_id)

        opened = results["opened"]
        total  = results["total"]
        failed = results["failed"]

        if failed == 0:
            self._restore_btn.setText(f"✓  Opened {opened}")
            self._restore_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(74,222,128,0.15);
                    border: 1px solid {GREEN};
                    color: {GREEN};
                    border-radius: 10px;
                    font-weight: 700;
                    padding: 9px 22px;
                }}
            """)
        else:
            self._restore_btn.setText(f"⚠  {opened}/{total} opened")
            self._restore_btn.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(251,191,36,0.15);
                    border: 1px solid {AMBER};
                    color: {AMBER};
                    border-radius: 10px;
                    font-weight: 700;
                    padding: 9px 22px;
                }}
            """)

        self.refresh()
        self._restore_feedback_timer.start(3000)

    def _reset_restore_btn(self):
        self._restore_btn.setText("▶  Restore All")
        self._restore_btn.setObjectName("accentBtn")
        self._restore_btn.setStyleSheet("")  # revert to stylesheet
        # Re-apply the object name style
        self._restore_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                color: white;
                font-weight: 700;
                border-radius: 10px;
                padding: 9px 22px;
            }}
            QPushButton:hover {{ background: {ACCENT2}; }}
            QPushButton:pressed {{ background: {ACCENT_DIM}; }}
        """)
        self._restore_btn.setEnabled(True)