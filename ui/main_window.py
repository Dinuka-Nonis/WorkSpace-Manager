"""
ui/main_window.py — WorkSpace Manager main window.

Changes in this version:
  • SnapshotPickerDialog — scan runs in background, user sees a checklist
    of actually-open apps + tabs, can deselect anything before saving
  • SnapshotDialog (name/target) is now shown AFTER the picker
  • Memory leaks fixed:
      - _Worker redefined per call → moved to module-level _SnapshotScanWorker
      - Reference cycles in closures → use QThread.finished to clean up
      - snap_worker held via self._snap_worker; slot connections use
        lambda-free patterns to avoid capturing stale references
"""

from datetime import datetime

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QLineEdit, QMessageBox, QApplication, QDialog,
    QComboBox, QCheckBox
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QTimer, QPropertyAnimation,
    QEasingCurve, QPoint, QThread
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
    GREEN, RED, RED_BG, SHADOW_SM, SHADOW_MD,
    FONT_DISPLAY, FONT_BODY
)

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


def _time_ago(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt  = datetime.fromisoformat(ts)
        now = datetime.now()
        s   = int((now - dt).total_seconds())
        if s < 60:      return "just now"
        if s < 3600:    return f"{s // 60}m ago"
        if s < 86400:   return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return ""


# ── Background scan worker ────────────────────────────────────────────────────

class _SnapshotScanWorker(QThread):
    """
    Runs scan_for_picker() off the main thread.
    Emits results(apps, tabs) when done, or error(msg) on failure.
    Cleans itself up via finished signal — no external reference needed
    beyond the duration of the scan.
    """
    results = pyqtSignal(list, list)   # apps, tabs
    error   = pyqtSignal(str)

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self._session_id = session_id
        # Auto-delete the C++ QThread object when done — prevents leak
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            from core.snapshot import scan_for_picker
            r = scan_for_picker(self._session_id)
            self.results.emit(r["apps"], r["tabs"])
        except Exception as e:
            self.error.emit(str(e))


# ── Snapshot save worker ──────────────────────────────────────────────────────

class _SnapshotSaveWorker(QThread):
    """Writes selected items to DB off the main thread."""
    done  = pyqtSignal(int, int)   # apps_added, tabs_added
    error = pyqtSignal(str)

    def __init__(self, session_id: int, apps: list, tabs: list, parent=None):
        super().__init__(parent)
        self._sid  = session_id
        self._apps = apps
        self._tabs = tabs
        self.finished.connect(self.deleteLater)

    def run(self):
        try:
            a = db.add_items_bulk(self._sid, self._apps)
            t = db.add_items_bulk(self._sid, self._tabs)
            self.done.emit(len(a), len(t))
        except Exception as e:
            self.error.emit(str(e))


# ── New Session dialog ────────────────────────────────────────────────────────

class NewSessionDialog(QDialog):
    def __init__(self, parent=None, placeholder="e.g. Morning Research"):
        super().__init__(parent)
        self.setWindowTitle("")
        self.setFixedSize(480, 160)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._result_text = ""
        self._placeholder = placeholder
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

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
        fx.setBlurRadius(50); fx.setColor(QColor(0, 0, 0, 55)); fx.setOffset(0, 12)
        card.setGraphicsEffect(fx)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(16)

        lbl = QLabel("Name your session")
        lbl.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        lbl.setStyleSheet(f"color: {MUTED}; letter-spacing: 0.2px;")
        layout.addWidget(lbl)

        pill_row = QHBoxLayout()
        pill_row.setSpacing(10)

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
        self._name_input.setPlaceholderText(self._placeholder)
        self._name_input.setFont(QFont(FONT_DISPLAY, 16, QFont.Weight.Bold))
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: transparent; border: none;
                color: {TEXT}; font-size: 17px; font-weight: 700; padding: 0;
            }}
        """)
        self._name_input.returnPressed.connect(self._accept)
        pc_layout.addWidget(self._name_input)

        create_btn = QPushButton("Create")
        create_btn.setFixedSize(88, 38)
        create_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        create_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; border: none; border-radius: 19px;
                color: white; font-weight: 700; font-size: 14px;
            }}
            QPushButton:hover   {{ background: {ACCENT2}; }}
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


# ── Snapshot picker dialog ─────────────────────────────────────────────────────
#
# Flow:
#  1. Opens immediately with a "Scanning…" state.
#  2. _SnapshotScanWorker runs in background; populates the list when done.
#  3. Each item is a checkbox — user can deselect anything.
#  4. "Save Snapshot" confirms; caller gets selected_apps + selected_tabs.

class SnapshotPickerDialog(QDialog):
    """
    Two-phase dialog:
      Phase 1 — scanning spinner
      Phase 2 — checklist of found apps + tabs, user picks what to keep

    Returns via .selected_apps and .selected_tabs after accept().
    """

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("")
        self.setFixedSize(560, 600)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.selected_apps: list[dict] = []
        self.selected_tabs: list[dict] = []

        self._session_id  = session_id
        self._app_checks: list[tuple[QCheckBox, dict]] = []
        self._tab_checks: list[tuple[QCheckBox, dict]] = []
        self._worker: "_SnapshotScanWorker | None" = None

        self._build()
        self._start_scan()

    # ── Construction ─────────────────────────────────────────────────────────

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        self._card = QWidget()
        self._card.setObjectName("pickerCard")
        self._card.setStyleSheet(f"""
            #pickerCard {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 24px;
            }}
        """)
        fx = QGraphicsDropShadowEffect(self._card)
        fx.setBlurRadius(50); fx.setColor(QColor(0, 0, 0, 55)); fx.setOffset(0, 12)
        self._card.setGraphicsEffect(fx)
        outer.addWidget(self._card)

        self._card_layout = QVBoxLayout(self._card)
        self._card_layout.setContentsMargins(28, 24, 28, 24)
        self._card_layout.setSpacing(16)

        # Header
        header_row = QHBoxLayout()
        title_lbl = QLabel("Save Snapshot")
        title_lbl.setFont(QFont(FONT_DISPLAY, 17, QFont.Weight.Bold))
        title_lbl.setStyleSheet(f"color: {TEXT};")
        header_row.addWidget(title_lbl)
        header_row.addStretch()

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedSize(80, 34)
        self._cancel_btn.setFont(QFont(FONT_BODY, 13))
        self._cancel_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE2}; border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 17px; color: {MUTED};
            }}
            QPushButton:hover {{ background: {SURFACE3}; color: {TEXT2}; }}
        """)
        self._cancel_btn.clicked.connect(self.reject)
        header_row.addWidget(self._cancel_btn)
        self._card_layout.addLayout(header_row)

        sub_lbl = QLabel("Select what to include in your snapshot.")
        sub_lbl.setFont(QFont(FONT_BODY, 13))
        sub_lbl.setStyleSheet(f"color: {MUTED};")
        self._card_layout.addWidget(sub_lbl)

        # Scanning state
        self._scanning_widget = QWidget()
        scan_layout = QVBoxLayout(self._scanning_widget)
        scan_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        scan_layout.setSpacing(10)

        self._scan_lbl = QLabel("Scanning open windows…")
        self._scan_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scan_lbl.setFont(QFont(FONT_BODY, 14))
        self._scan_lbl.setStyleSheet(f"color: {MUTED};")
        scan_layout.addWidget(self._scan_lbl)

        # Animated dots
        self._dot_timer = QTimer(self)
        self._dot_timer.setInterval(420)
        self._dot_timer.timeout.connect(self._tick_dots)
        self._dot_count = 0
        self._dot_timer.start()

        self._card_layout.addWidget(self._scanning_widget, 1)

        # Results area (hidden while scanning)
        self._results_widget = QWidget()
        self._results_widget.hide()
        res_layout = QVBoxLayout(self._results_widget)
        res_layout.setContentsMargins(0, 0, 0, 0)
        res_layout.setSpacing(12)

        # Select-all row
        sel_row = QHBoxLayout()
        self._select_all_btn = QPushButton("Select all")
        self._select_all_btn.setFixedHeight(30)
        self._select_all_btn.setFont(QFont(FONT_BODY, 12))
        self._select_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; color: {ACCENT};
                font-weight: 600; text-decoration: underline;
            }}
            QPushButton:hover {{ color: {ACCENT2}; }}
        """)
        self._select_all_btn.clicked.connect(lambda: self._set_all(True))
        self._deselect_all_btn = QPushButton("Deselect all")
        self._deselect_all_btn.setFixedHeight(30)
        self._deselect_all_btn.setFont(QFont(FONT_BODY, 12))
        self._deselect_all_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; color: {MUTED};
                font-weight: 600; text-decoration: underline;
            }}
            QPushButton:hover {{ color: {TEXT2}; }}
        """)
        self._deselect_all_btn.clicked.connect(lambda: self._set_all(False))
        sel_row.addWidget(self._select_all_btn)
        sel_row.addWidget(self._deselect_all_btn)
        sel_row.addStretch()
        res_layout.addLayout(sel_row)

        # Scrollable checklist
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"""
            QScrollArea {{ background: {SURFACE2}; border-radius: 14px; }}
            QScrollBar:vertical {{
                background: transparent; width: 5px; margin: 6px 1px;
            }}
            QScrollBar::handle:vertical {{
                background: rgba(0,0,0,0.10); border-radius: 3px; min-height: 30px;
            }}
            QScrollBar::handle:vertical:hover {{ background: rgba(0,0,0,0.20); }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet(f"background: {SURFACE2}; border-radius: 14px;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(4, 8, 4, 8)
        self._list_layout.setSpacing(0)
        self._list_layout.addStretch()

        scroll.setWidget(self._list_widget)
        res_layout.addWidget(scroll, 1)

        self._card_layout.addWidget(self._results_widget, 1)

        # Save button (disabled during scan)
        self._save_btn = QPushButton("Save Snapshot")
        self._save_btn.setFixedHeight(46)
        self._save_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {MUTED2}; border: none; border-radius: 23px;
                color: white; font-weight: 700;
            }}
            QPushButton:enabled {{
                background: {ACCENT};
            }}
            QPushButton:enabled:hover   {{ background: {ACCENT2}; }}
            QPushButton:enabled:pressed {{ background: {ACCENT3}; }}
        """)
        self._save_btn.clicked.connect(self._accept)
        self._card_layout.addWidget(self._save_btn)

    # ── Scanning ─────────────────────────────────────────────────────────────

    def _tick_dots(self):
        self._dot_count = (self._dot_count + 1) % 4
        dots = "·" * self._dot_count + " " * (3 - self._dot_count)
        self._scan_lbl.setText(f"Scanning open windows{dots}")

    def _start_scan(self):
        # Use a dummy session_id=0 for the scan — tabs will use the real one
        # at save time.  For scanning we just want the list of open tabs.
        w = _SnapshotScanWorker(self._session_id, parent=self)
        self._worker = w
        w.results.connect(self._on_scan_done)
        w.error.connect(self._on_scan_error)
        w.start()

    def _on_scan_done(self, apps: list, tabs: list):
        self._dot_timer.stop()
        self._scanning_widget.hide()
        self._worker = None

        if not apps and not tabs:
            self._scan_lbl.setText(
                "No open apps or Chrome tabs found.\n"
                "Make sure Chrome is running with the extension installed."
            )
            self._scan_lbl.setWordWrap(True)
            self._scanning_widget.show()
            # Still allow saving an empty snapshot
            self._save_btn.setEnabled(True)
            return

        # Build checklist
        self._app_checks.clear()
        self._tab_checks.clear()

        if apps:
            self._add_section_header("OPEN APPLICATIONS")
            for app in apps:
                cb = self._add_check_item(
                    app["label"],
                    app.get("path_or_url", ""),
                    icon="◈",
                    checked=True,
                )
                self._app_checks.append((cb, app))

        if tabs:
            if apps:
                self._add_divider()
            self._add_section_header("OPEN TABS")
            for tab in tabs:
                cb = self._add_check_item(
                    tab["label"],
                    tab.get("path_or_url", ""),
                    icon="○",
                    checked=True,
                )
                self._tab_checks.append((cb, tab))

        # Remove last stretch and re-add
        last = self._list_layout.itemAt(self._list_layout.count() - 1)
        if last and last.spacerItem():
            self._list_layout.takeAt(self._list_layout.count() - 1)
        self._list_layout.addStretch()

        self._results_widget.show()
        self._save_btn.setEnabled(True)
        self._update_save_btn_count()

    def _on_scan_error(self, msg: str):
        self._dot_timer.stop()
        self._scan_lbl.setText(f"Scan failed: {msg}")
        self._scan_lbl.setWordWrap(True)
        self._worker = None
        self._save_btn.setEnabled(True)

    # ── Checklist helpers ─────────────────────────────────────────────────────

    def _add_section_header(self, text: str):
        lbl = QLabel(text)
        lbl.setFont(QFont(FONT_BODY, 10, QFont.Weight.Bold))
        lbl.setStyleSheet(f"""
            color: {MUTED2}; letter-spacing: 1.5px;
            padding: 10px 16px 4px 16px;
            background: transparent;
        """)
        self._list_layout.insertWidget(self._list_layout.count() - 1, lbl)

    def _add_divider(self):
        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: rgba(0,0,0,0.06); margin: 6px 16px;")
        self._list_layout.insertWidget(self._list_layout.count() - 1, div)

    def _add_check_item(self, label: str, path: str, icon: str, checked: bool) -> QCheckBox:
        row = QWidget()
        row.setFixedHeight(58)
        row.setStyleSheet(f"""
            QWidget {{ background: transparent; border-radius: 10px; }}
            QWidget:hover {{ background: rgba(0,0,0,0.04); }}
        """)

        rl = QHBoxLayout(row)
        rl.setContentsMargins(12, 0, 12, 0)
        rl.setSpacing(12)

        # Icon box
        icon_box = QWidget()
        icon_box.setFixedSize(36, 36)
        icon_box.setStyleSheet(f"""
            background: {SURFACE}; border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 10px;
        """)
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        sym = QLabel(icon)
        sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sym.setFont(QFont(FONT_BODY, 12, QFont.Weight.Bold))
        sym.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(sym)
        rl.addWidget(icon_box)

        # Text
        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        name_lbl = QLabel(label)
        name_lbl.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        name_lbl.setStyleSheet(f"color: {TEXT};")
        name_lbl.setMaximumWidth(350)
        name_lbl.setWordWrap(False)
        text_col.addWidget(name_lbl)

        if path:
            short = ("…" + path[-44:]) if len(path) > 47 else path
            path_lbl = QLabel(short)
            path_lbl.setFont(QFont(FONT_BODY, 11))
            path_lbl.setStyleSheet(f"color: {MUTED};")
            path_lbl.setToolTip(path)
            text_col.addWidget(path_lbl)

        rl.addLayout(text_col)
        rl.addStretch()

        # Checkbox (right side)
        cb = QCheckBox()
        cb.setChecked(checked)
        cb.setStyleSheet(f"""
            QCheckBox::indicator {{
                width: 20px; height: 20px; border-radius: 6px;
                border: 1.5px solid rgba(0,0,0,0.18);
                background: {SURFACE};
            }}
            QCheckBox::indicator:checked {{
                background: {ACCENT};
                border-color: {ACCENT};
                image: none;
            }}
            QCheckBox::indicator:checked::after {{
                content: "✓";
            }}
        """)
        cb.stateChanged.connect(self._update_save_btn_count)
        rl.addWidget(cb)

        self._list_layout.insertWidget(self._list_layout.count() - 1, row)
        return cb

    # ── Controls ──────────────────────────────────────────────────────────────

    def _set_all(self, checked: bool):
        for cb, _ in self._app_checks + self._tab_checks:
            cb.setChecked(checked)

    def _update_save_btn_count(self):
        n = sum(1 for cb, _ in self._app_checks + self._tab_checks if cb.isChecked())
        if n == 0:
            self._save_btn.setText("Save Empty Snapshot")
        elif n == 1:
            self._save_btn.setText("Save 1 Item")
        else:
            self._save_btn.setText(f"Save {n} Items")

    def _accept(self):
        self.selected_apps = [
            {k: v for k, v in item.items() if not k.startswith("_")}
            for cb, item in self._app_checks if cb.isChecked()
        ]
        self.selected_tabs = [
            item for cb, item in self._tab_checks if cb.isChecked()
        ]
        self.accept()

    def closeEvent(self, e):
        # Stop worker and timer cleanly on any close
        self._dot_timer.stop()
        if self._worker and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(500)
        super().closeEvent(e)

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()


# ── Session-target dialog (shown after picker) ────────────────────────────────

class SnapshotTargetDialog(QDialog):
    """
    After the user selects items in SnapshotPickerDialog, this asks:
    should we create a new session or add to an existing one?
    """
    MODE_NEW      = "new"
    MODE_EXISTING = "existing"

    def __init__(self, item_count: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("")
        self.setFixedSize(480, 230)
        self.setWindowFlags(
            Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._mode       = self.MODE_NEW
        self._name       = ""
        self._session_id = None
        self._sessions: list[dict] = []
        self._item_count = item_count
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        card = QWidget()
        card.setObjectName("targetCard")
        card.setStyleSheet(f"""
            #targetCard {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 24px;
            }}
        """)
        fx = QGraphicsDropShadowEffect(card)
        fx.setBlurRadius(50); fx.setColor(QColor(0, 0, 0, 55)); fx.setOffset(0, 12)
        card.setGraphicsEffect(fx)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(28, 22, 28, 22)
        layout.setSpacing(14)

        hdr = QLabel(f"Save {self._item_count} item{'s' if self._item_count != 1 else ''} to…")
        hdr.setFont(QFont(FONT_DISPLAY, 16, QFont.Weight.Bold))
        hdr.setStyleSheet(f"color: {TEXT};")
        layout.addWidget(hdr)

        # Toggle
        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)
        self._new_btn      = QPushButton("New Session")
        self._existing_btn = QPushButton("Existing Session")
        for btn in (self._new_btn, self._existing_btn):
            btn.setFixedHeight(36)
            btn.setFont(QFont(FONT_BODY, 13, QFont.Weight.Bold))
            toggle_row.addWidget(btn)
        self._new_btn.clicked.connect(lambda: self._set_mode(self.MODE_NEW))
        self._existing_btn.clicked.connect(lambda: self._set_mode(self.MODE_EXISTING))
        layout.addLayout(toggle_row)

        # Name input
        self._name_input = QLineEdit()
        self._name_input.setFixedHeight(42)
        self._name_input.setText(datetime.now().strftime("Snapshot %b %d %H:%M"))
        self._name_input.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: {SURFACE2}; border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 21px; color: {TEXT}; padding: 0 18px;
            }}
            QLineEdit:focus {{ border-color: rgba(0,0,0,0.20); }}
        """)
        self._name_input.returnPressed.connect(self._accept)
        layout.addWidget(self._name_input)

        # Existing session combo (hidden by default)
        self._session_combo = QComboBox()
        self._session_combo.setFixedHeight(42)
        self._session_combo.setFont(QFont(FONT_BODY, 14))
        self._session_combo.setStyleSheet(f"""
            QComboBox {{
                background: {SURFACE2}; border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 21px; color: {TEXT}; padding: 0 18px;
            }}
            QComboBox::drop-down {{ border: none; width: 30px; }}
            QComboBox QAbstractItemView {{
                background: {SURFACE}; border: 1.5px solid rgba(0,0,0,0.10);
                border-radius: 10px; selection-background-color: {SURFACE2};
                color: {TEXT};
            }}
        """)
        self._session_combo.hide()
        self._populate_sessions()
        layout.addWidget(self._session_combo)

        # Save button
        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(44)
        save_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        save_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; border: none; border-radius: 22px;
                color: white; font-weight: 700;
            }}
            QPushButton:hover   {{ background: {ACCENT2}; }}
            QPushButton:pressed {{ background: {ACCENT3}; }}
        """)
        save_btn.clicked.connect(self._accept)
        layout.addWidget(save_btn)

        self._update_toggle_styles()

    def _populate_sessions(self):
        self._session_combo.clear()
        self._sessions = db.get_all_sessions()
        for s in self._sessions:
            self._session_combo.addItem(s["name"])

    def _set_mode(self, mode: str):
        self._mode = mode
        self._name_input.setVisible(mode == self.MODE_NEW)
        self._session_combo.setVisible(mode == self.MODE_EXISTING)
        self._update_toggle_styles()

    def _update_toggle_styles(self):
        for btn, active in [
            (self._new_btn,      self._mode == self.MODE_NEW),
            (self._existing_btn, self._mode == self.MODE_EXISTING),
        ]:
            if active:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {ACCENT}; border: none; border-radius: 18px;
                        color: white; font-weight: 700;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {SURFACE2}; border: 1.5px solid rgba(0,0,0,0.08);
                        border-radius: 18px; color: {MUTED};
                    }}
                    QPushButton:hover {{ background: {SURFACE3}; color: {TEXT2}; }}
                """)

    def _accept(self):
        if self._mode == self.MODE_NEW:
            name = self._name_input.text().strip()
            if not name:
                return
            self._name = name
            self._session_id = None
        else:
            idx = self._session_combo.currentIndex()
            if idx < 0 or not self._sessions:
                return
            self._session_id = self._sessions[idx]["id"]
            self._name = ""
        self.accept()

    def result_mode(self)       -> str:       return self._mode
    def result_name(self)       -> str:       return self._name
    def result_session_id(self) -> "int|None": return self._session_id

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()


# ── Toast ──────────────────────────────────────────────────────────────────────

class ToastNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(380, 48)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.hide)
        self._msg = ""

    def show_toast(self, msg: str, duration=2800):
        self._msg = msg
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - 190, screen.bottom() - 90)
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


# ── Animated sidebar indicator ─────────────────────────────────────────────────

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


# ── Session card ───────────────────────────────────────────────────────────────

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
        self.setFixedHeight(96)
        self._build(session, stats)

    def _build(self, session: dict, stats: dict):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(24, 0, 20, 0)
        layout.setSpacing(18)

        icon_box = QWidget()
        icon_box.setFixedSize(46, 46)
        icon_box.setStyleSheet(f"""
            background: {SURFACE2};
            border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 14px;
        """)
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        letter = QLabel(session["name"][0].upper() if session["name"] else "S")
        letter.setAlignment(Qt.AlignmentFlag.AlignCenter)
        letter.setFont(QFont(FONT_DISPLAY, 17, QFont.Weight.Black))
        letter.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(letter)
        layout.addWidget(icon_box)

        text_col = QVBoxLayout()
        text_col.setSpacing(3)

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

        ago = _time_ago(session.get("last_restored_at") or "")
        if ago:
            restored_lbl = QLabel(f"Restored {ago}")
            restored_lbl.setFont(QFont(FONT_BODY, 11))
            restored_lbl.setStyleSheet(f"color: {MUTED2};")
            text_col.addWidget(restored_lbl)

        layout.addLayout(text_col)
        layout.addStretch()

        del_btn = QPushButton("×")
        del_btn.setFixedSize(34, 34)
        del_btn.setToolTip("Delete session")
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.setFont(QFont(FONT_BODY, 18, QFont.Weight.Light))
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1.5px solid transparent;
                border-radius: 10px; color: {MUTED2};
            }}
            QPushButton:hover {{
                background: {RED_BG}; border-color: rgba(138,26,26,0.18); color: {RED};
            }}
            QPushButton:pressed {{ background: rgba(138,26,26,0.13); }}
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

    def enterEvent(self, e): self._hovered = True;  self.update()
    def leaveEvent(self, e): self._hovered = False; self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hovered:
            path = QPainterPath()
            path.addRoundedRect(8, 4, self.width()-16, self.height()-8, 14, 14)
            p.fillPath(path, QColor(0, 0, 0, 22))


# ── Nav item ───────────────────────────────────────────────────────────────────

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

    def enterEvent(self, e): self._hovered = True;  self.update()
    def leaveEvent(self, e): self._hovered = False; self.update()

    def paintEvent(self, e):
        if self._hovered and not self._active:
            p = QPainter(self)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            path = QPainterPath()
            path.addRoundedRect(8, 3, self.width()-16, self.height()-6, 10, 10)
            p.fillPath(path, QColor(0, 0, 0, 14))


# ── Sidebar ────────────────────────────────────────────────────────────────────

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

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFixedHeight(1); sep.setStyleSheet("background: rgba(0,0,0,0.07);")
        layout.addWidget(sep)
        layout.addSpacing(12)

        menu_lbl = QLabel("MENU")
        menu_lbl.setFont(QFont(FONT_BODY, 10, QFont.Weight.Bold))
        menu_lbl.setStyleSheet(
            f"color: {MUTED2}; letter-spacing: 2px; padding-left: 20px; background: transparent;"
        )
        menu_lbl.setFixedHeight(24)
        layout.addWidget(menu_lbl)
        layout.addSpacing(4)

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

        bottom = QWidget()
        bottom.setFixedHeight(84)
        bl = QVBoxLayout(bottom)
        bl.setContentsMargins(16, 16, 16, 16)

        btn = QPushButton("+ New Session")
        btn.setFixedHeight(46)
        btn.setFont(QFont(FONT_DISPLAY, 15, QFont.Weight.Bold))
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT}; border: none; border-radius: 23px;
                color: white; letter-spacing: -0.2px;
            }}
            QPushButton:hover   {{ background: {ACCENT2}; }}
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


# ── Empty state ────────────────────────────────────────────────────────────────

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


# ── Main window ────────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    snapshot_requested = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("WorkSpace Manager")
        self.setMinimumSize(980, 660)
        self.resize(1160, 760)
        self._detail_panel = None
        self._toast        = ToastNotification()
        self._save_worker: "_SnapshotSaveWorker | None" = None
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

        header = QHBoxLayout()

        title = QLabel("Sessions")
        title.setFont(QFont(FONT_DISPLAY, 30, QFont.Weight.Black))
        title.setStyleSheet(f"color: {TEXT}; letter-spacing: -0.8px;")
        header.addWidget(title)
        header.addStretch()

        self._snap_btn = QPushButton("⊕ Save Snapshot")
        self._snap_btn.setFixedHeight(40)
        self._snap_btn.setMinimumWidth(148)
        self._snap_btn.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._snap_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE}; border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 20px; color: {TEXT2}; padding: 0 18px;
            }}
            QPushButton:hover  {{ background: {SURFACE2}; border-color: rgba(0,0,0,0.13); }}
            QPushButton:pressed {{ background: {SURFACE3}; }}
        """)
        _apply_shadow(self._snap_btn, blur=12, alpha=12, dy=3)
        self._snap_btn.clicked.connect(self._on_snapshot_clicked)
        header.addWidget(self._snap_btn)

        header.addSpacing(10)

        new_btn_hdr = QPushButton("+ New")
        new_btn_hdr.setFixedHeight(40)
        new_btn_hdr.setMinimumWidth(90)
        new_btn_hdr.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        new_btn_hdr.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE}; border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 20px; color: {TEXT2}; padding: 0 20px;
            }}
            QPushButton:hover  {{ background: {SURFACE2}; border-color: rgba(0,0,0,0.13); }}
            QPushButton:pressed {{ background: {SURFACE3}; }}
        """)
        _apply_shadow(new_btn_hdr, blur=12, alpha=12, dy=3)
        new_btn_hdr.clicked.connect(self._create_session)
        header.addWidget(new_btn_hdr)

        layout.addLayout(header)
        layout.addSpacing(6)

        subtitle = QLabel(
            "Click a session to view, edit, or restore it.  ·  Ctrl+Alt+W to show from anywhere."
        )
        subtitle.setFont(QFont(FONT_BODY, 13))
        subtitle.setStyleSheet(f"color: {MUTED};")
        layout.addWidget(subtitle)
        layout.addSpacing(32)

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

    # ── Data ──────────────────────────────────────────────────────────────────

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
            card  = SessionCard(session, stats)
            card.open_clicked.connect(self._open_detail)
            card.delete_clicked.connect(self._delete_session)
            self._grid_layout.insertWidget(i * 2, card)

            if i < len(sessions) - 1:
                div = QFrame()
                div.setFrameShape(QFrame.Shape.HLine)
                div.setFixedHeight(1)
                div.setStyleSheet("background: rgba(0,0,0,0.05); margin: 0 24px;")
                self._grid_layout.insertWidget(i * 2 + 1, div)

    # ── Actions ───────────────────────────────────────────────────────────────

    def _create_session(self):
        dlg = NewSessionDialog(self)
        geo = self.geometry()
        dlg.move(geo.center().x() - dlg.width() // 2,
                 geo.center().y() - dlg.height() // 2)
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

    # ── Snapshot flow ─────────────────────────────────────────────────────────
    #
    # Step 1: SnapshotPickerDialog — scan + user selects items
    # Step 2: SnapshotTargetDialog — name new session or pick existing
    # Step 3: _SnapshotSaveWorker  — write selected items to DB

    def _on_snapshot_clicked(self):
        """Entry point for the snapshot flow — opens the picker dialog."""
        # Always pass session_id=0 to SnapshotPickerDialog.  The native host
        # treats 0 + preview=True as a read-only request: it returns tabs in
        # tab_response.json but does NOT write them to the database.  Tabs are
        # only saved to the correct session after the user picks a target in
        # step 2.  This fixes the bug where Chrome tabs were permanently
        # written into the wrong (MRU) session before the user chose a target.
        picker = SnapshotPickerDialog(0, self)
        geo = self.geometry()
        picker.move(geo.center().x() - picker.width() // 2,
                    geo.center().y() - picker.height() // 2)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return

        selected_apps = picker.selected_apps
        selected_tabs = picker.selected_tabs
        total = len(selected_apps) + len(selected_tabs)

        # Step 2: choose target session
        target_dlg = SnapshotTargetDialog(total, self)
        target_dlg.move(geo.center().x() - target_dlg.width() // 2,
                        geo.center().y() - target_dlg.height() // 2)
        if target_dlg.exec() != QDialog.DialogCode.Accepted:
            return

        if target_dlg.result_mode() == SnapshotTargetDialog.MODE_NEW:
            name = target_dlg.result_name()
            if not name:
                return
            session_id = db.create_session(name)
            self._load_sessions()
        else:
            session_id = target_dlg.result_session_id()
            if not session_id:
                return

        self._run_save(session_id, selected_apps, selected_tabs)

    def _save_snapshot(self, session_id: int):
        """
        Non-interactive path used by the tray 'Save Snapshot' action
        and the shutdown hook.  Skips the picker and saves all detected
        apps + tabs directly — identical to the previous behaviour, used
        only when there's no UI context.
        """
        self._snap_btn.setEnabled(False)
        self._snap_btn.setText("Capturing…")

        class _QuickWorker(QThread):
            done  = pyqtSignal(int, int)
            error = pyqtSignal(str)

            def __init__(self, sid, parent=None):
                super().__init__(parent)
                self._sid = sid
                self.finished.connect(self.deleteLater)  # no leak

            def run(self):
                try:
                    from core.snapshot import capture_full_snapshot
                    r = capture_full_snapshot(self._sid)
                    a = db.add_items_bulk(self._sid, r["apps"])
                    t = db.add_items_bulk(self._sid, r["tabs"])
                    self.done.emit(len(a), len(t))
                except Exception as e:
                    self.error.emit(str(e))

        w = _QuickWorker(session_id, parent=self)
        self._save_worker = w

        def _done(apps_added, tabs_added):
            total = apps_added + tabs_added
            self._toast.show_toast(
                f"Snapshot saved — {total} item{'s' if total != 1 else ''} "
                f"({apps_added} app{'s' if apps_added != 1 else ''}, "
                f"{tabs_added} tab{'s' if tabs_added != 1 else ''})"
            )
            self._snap_btn.setEnabled(True)
            self._snap_btn.setText("⊕ Save Snapshot")
            self._load_sessions()
            self._save_worker = None

        def _err(msg):
            self._toast.show_toast(f"Snapshot failed: {msg}")
            self._snap_btn.setEnabled(True)
            self._snap_btn.setText("⊕ Save Snapshot")
            self._save_worker = None

        w.done.connect(_done)
        w.error.connect(_err)
        w.start()

    def _run_save(self, session_id: int, apps: list, tabs: list):
        """Write user-selected items to the DB via a background worker."""
        self._snap_btn.setEnabled(False)
        self._snap_btn.setText("Saving…")

        w = _SnapshotSaveWorker(session_id, apps, tabs, parent=self)
        self._save_worker = w

        def _done(apps_added, tabs_added):
            total = apps_added + tabs_added
            self._toast.show_toast(
                f"Snapshot saved — {total} item{'s' if total != 1 else ''} "
                f"({apps_added} app{'s' if apps_added != 1 else ''}, "
                f"{tabs_added} tab{'s' if tabs_added != 1 else ''})"
            )
            self._snap_btn.setEnabled(True)
            self._snap_btn.setText("⊕ Save Snapshot")
            self._load_sessions()
            self._save_worker = None

        def _err(msg):
            self._toast.show_toast(f"Snapshot failed: {msg}")
            self._snap_btn.setEnabled(True)
            self._snap_btn.setText("⊕ Save Snapshot")
            self._save_worker = None

        w.done.connect(_done)
        w.error.connect(_err)
        w.start()
