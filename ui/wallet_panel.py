"""
ui/wallet_panel.py — Hotkey-toggled floating wallet panel.

Changes vs original:
  • SessionRow emits inspect_requested when the row body is clicked (not restore btn).
  • WalletPanel inserts an _InspectorPanel inline below the clicked session row,
    showing every saved item with type icon, label, and tooltip for the URL/path.
  • Clicking the same row again, or pressing ×, closes the inspector.
  • PANEL_WIDTH widened slightly (360→) to accommodate the inspect hint.
"""

import sys
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QApplication
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QPoint, pyqtProperty, QThread, pyqtSignal
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QPen,
    QLinearGradient
)

import db

PANEL_BG     = QColor("#0f0f14")
PANEL_BG2    = QColor("#1a1a24")
PANEL_BORDER = QColor("#2a2a3a")
TEXT_WHITE   = QColor("#ffffff")
TEXT_DIM     = QColor("#888899")
TEXT_MUTED   = QColor("#44445a")
ACCENT_GREEN = QColor("#42d778")
ACCENT_BLUE  = QColor("#635bff")

ICON_COLORS = [
    QColor("#635bff"),
    QColor("#9bd86a"),
    QColor("#f59e0b"),
    QColor("#ef4444"),
    QColor("#06b6d4"),
    QColor("#ec4899"),
]

PANEL_WIDTH  = 360
PANEL_HEIGHT = 560


def _time_ago(ts: str) -> str:
    if not ts:
        return ""
    try:
        dt  = datetime.fromisoformat(ts)
        now = datetime.now()
        s   = int((now - dt).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s // 60}m ago"
        if s < 86400: return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return ""


class _RestoreWorker(QThread):
    done = pyqtSignal(dict, int)

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self._sid = session_id
        self.finished.connect(self.deleteLater)

    def run(self):
        import restore
        result = restore.restore_session(self._sid)
        self.done.emit(result, self._sid)


class SessionRow(QWidget):
    restore_requested = pyqtSignal(int)
    inspect_requested = pyqtSignal(int)
    delete_requested  = pyqtSignal(int)

    def __init__(self, session: dict, index: int, parent=None):
        super().__init__(parent)
        self._session   = session
        self._index     = index
        self._hovered   = False
        self._restoring = False
        self._inspected = False
        self.setMouseTracking(True)
        self.setFixedHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def update_session(self, session: dict):
        self._session = session
        self.update()

    def set_restoring(self, v: bool):
        self._restoring = v
        self.update()

    def set_inspected(self, v: bool):
        self._inspected = v
        self.update()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        x = e.position().x()
        w = self.width()
        if x > w - 90:
            self.restore_requested.emit(self._session["id"])
        elif x > w - 120 and self._hovered:
            # Delete button zone (×) — only active when row is hovered
            self.delete_requested.emit(self._session["id"])
        else:
            self.inspect_requested.emit(self._session["id"])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()
        sess = self._session

        if self._hovered or self._inspected:
            bg_path = QPainterPath()
            bg_path.addRoundedRect(0, 2, w, h - 4, 12, 12)
            p.fillPath(bg_path, QColor(255, 255, 255, 30 if self._inspected else 18))

        if self._inspected:
            p.fillRect(QRect(0, 10, 3, h - 20), ICON_COLORS[self._index % len(ICON_COLORS)])

        icon_color = ICON_COLORS[self._index % len(ICON_COLORS)]
        icon_path  = QPainterPath()
        icon_path.addRoundedRect(16, 18, 36, 36, 8, 8)
        grad = QLinearGradient(16, 18, 52, 54)
        grad.setColorAt(0, icon_color.lighter(130))
        grad.setColorAt(1, icon_color)
        p.fillPath(icon_path, grad)

        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Helvetica Neue", 14, QFont.Weight.Bold))
        p.drawText(QRect(16, 18, 36, 36), Qt.AlignmentFlag.AlignCenter,
                   sess.get("name", "?")[0].upper())

        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
        p.drawText(QRect(66, 14, w - 170, 24), Qt.AlignmentFlag.AlignVCenter,
                   sess.get("name", "Session"))

        p.setPen(TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(QRect(w - 90, 14, 78, 24),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _time_ago(sess.get("updated_at", "")))

        items  = db.get_items(sess["id"])
        n_apps = sum(1 for i in items if i["type"] == "app")
        n_urls = sum(1 for i in items if i["type"] == "url")
        n_file = sum(1 for i in items if i["type"] == "file")
        parts  = []
        if n_apps: parts.append(f"{n_apps} app{'s' if n_apps != 1 else ''}")
        if n_urls: parts.append(f"{n_urls} url{'s' if n_urls != 1 else ''}")
        if n_file: parts.append(f"{n_file} file{'s' if n_file != 1 else ''}")
        subtitle = " · ".join(parts) if parts else "empty"

        p.setPen(TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(QRect(66, 40, w - 170, 20), Qt.AlignmentFlag.AlignVCenter, subtitle)

        # Tiny hint below subtitle
        hint_text = "▾ inspecting" if self._inspected else "▸ tap to inspect"
        p.setPen(TEXT_MUTED)
        p.setFont(QFont("Helvetica Neue", 8))
        p.drawText(QRect(66, 56, w - 170, 14), Qt.AlignmentFlag.AlignVCenter, hint_text)

        if self._hovered:
            # Delete (×) button
            del_path = QPainterPath()
            del_path.addRoundedRect(w - 120, 22, 24, 28, 6, 6)
            p.fillPath(del_path, QColor(239, 68, 68, 160))
            p.setPen(QColor(255, 255, 255))
            p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
            p.drawText(QRect(w - 120, 22, 24, 28), Qt.AlignmentFlag.AlignCenter, "×")

            btn_path = QPainterPath()
            btn_path.addRoundedRect(w - 88, 22, 74, 28, 8, 8)
            p.fillPath(btn_path, ACCENT_GREEN if not self._restoring else QColor(255, 255, 255, 20))
            p.setPen(QColor(0, 0, 0) if not self._restoring else TEXT_DIM)
            p.setFont(QFont("Helvetica Neue", 9, QFont.Weight.Bold))
            p.drawText(QRect(w - 88, 22, 74, 28), Qt.AlignmentFlag.AlignCenter,
                       "Restoring…" if self._restoring else "Restore")

        p.end()


class _InspectorPanel(QWidget):
    """Inline item list shown below a session row when the user taps it."""

    closed = pyqtSignal()

    TYPE_ICONS = {"url": "🔗", "file": "📄", "app": "⚡"}

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self._session_id = session_id
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 2, 16, 10)
        layout.setSpacing(3)

        # Header row
        hdr = QHBoxLayout()
        hdr.setContentsMargins(0, 0, 0, 4)
        lbl = QLabel("Items in this session")
        lbl.setStyleSheet("color: #888899; font-size: 10px;")
        hdr.addWidget(lbl)
        hdr.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet("""
            QPushButton { color:#44445a; background:transparent; border:none; font-size:14px; padding:0; }
            QPushButton:hover { color:#ffffff; }
        """)
        close_btn.clicked.connect(self.closed.emit)
        hdr.addWidget(close_btn)
        layout.addLayout(hdr)

        items = db.get_items(self._session_id)

        if not items:
            empty = QLabel("No items yet — drag windows or URLs here to save them.")
            empty.setWordWrap(True)
            empty.setStyleSheet("color: #44445a; font-size: 10px; padding: 6px 0;")
            layout.addWidget(empty)
            return

        for item in items:
            row = QWidget()
            row.setFixedHeight(34)
            row.setStyleSheet("background: rgba(255,255,255,0.05); border-radius: 6px;")
            rl = QHBoxLayout(row)
            rl.setContentsMargins(8, 0, 8, 0)
            rl.setSpacing(6)

            icon = QLabel(self.TYPE_ICONS.get(item["type"], "•"))
            icon.setFixedWidth(16)
            icon.setStyleSheet("font-size: 11px; background: transparent;")
            rl.addWidget(icon)

            name_lbl = QLabel(item["label"])
            name_lbl.setStyleSheet("color: #ccccdd; font-size: 10px; background: transparent;")
            name_lbl.setToolTip(item["path_or_url"])
            rl.addWidget(name_lbl, 1)

            type_badge = QLabel(item["type"].upper())
            type_badge.setStyleSheet("color: #44445a; font-size: 8px; background: transparent;")
            rl.addWidget(type_badge)

            layout.addWidget(row)


class WalletPanel(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible_state    = False
        self._sessions: list[dict] = []
        self._session_rows: list[SessionRow] = []
        self._restore_workers: list[_RestoreWorker] = []
        self._inspected_id: int | None = None
        self._inspector_widget: _InspectorPanel | None = None

        self._setup_window()
        self._build_ui()
        self._position_on_screen()
        self._setup_animation()
        self._refresh()

        _t = QTimer(self)
        _t.timeout.connect(self._refresh)
        _t.start(4000)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)

    def _position_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        self._final_x  = geo.x() + geo.width() - PANEL_WIDTH - 20
        self._final_y  = geo.y() + 20
        self._hidden_x = geo.x() + geo.width() + 10
        self.move(self._hidden_x, self._final_y)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(280)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = _PanelHeader(self)
        outer.addWidget(self._header)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical { background: transparent; width: 4px; margin: 0; }
            QScrollBar::handle:vertical { background: rgba(255,255,255,0.12); border-radius: 2px; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(8, 4, 8, 12)
        self._list_layout.setSpacing(2)
        self._list_layout.addStretch()

        self._scroll_area.setWidget(self._list_widget)
        outer.addWidget(self._scroll_area, 1)

        self._footer = _PanelFooter(self)
        outer.addWidget(self._footer)

    def _refresh(self):
        self._sessions = db.get_all_sessions()
        self._rebuild_rows()
        self.update()

    def _rebuild_rows(self):
        inspected = self._inspected_id

        for row in self._session_rows:
            row.setParent(None)
            row.deleteLater()
        self._session_rows.clear()

        if self._inspector_widget:
            self._inspector_widget.setParent(None)
            self._inspector_widget.deleteLater()
            self._inspector_widget = None

        while self._list_layout.count():
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._sessions:
            empty = QLabel("No sessions yet.\nDrag a window to the right edge\nto create one.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #44445a; font-size: 13px; padding: 40px 20px;")
            self._list_layout.addWidget(empty)
            self._list_layout.addStretch()
            return

        for i, sess in enumerate(self._sessions):
            row = SessionRow(sess, i, self._list_widget)
            row.restore_requested.connect(self._on_restore)
            row.inspect_requested.connect(self._on_inspect)
            row.delete_requested.connect(self._on_delete)
            self._session_rows.append(row)
            self._list_layout.addWidget(row)

            if inspected is not None and sess["id"] == inspected:
                row.set_inspected(True)
                self._inspector_widget = _InspectorPanel(inspected, self._list_widget)
                self._inspector_widget.closed.connect(self._close_inspector)
                self._list_layout.addWidget(self._inspector_widget)

        self._list_layout.addStretch()

    def _on_delete(self, session_id: int):
        db.delete_session(session_id)
        if self._inspected_id == session_id:
            self._inspected_id = None
        self._refresh()

    def _on_inspect(self, session_id: int):
        if self._inspected_id == session_id:
            self._close_inspector()
            return
        self._inspected_id = session_id
        self._rebuild_rows()

    def _close_inspector(self):
        self._inspected_id = None
        self._rebuild_rows()

    def _on_restore(self, session_id: int):
        for row in self._session_rows:
            if row._session["id"] == session_id:
                row.set_restoring(True)
                break

        worker = _RestoreWorker(session_id, parent=self)
        worker.done.connect(self._on_restore_done)
        self._restore_workers.append(worker)
        worker.start()

    def _on_restore_done(self, result: dict, session_id: int):
        for row in self._session_rows:
            if row._session["id"] == session_id:
                row.set_restoring(False)
                break
        self._restore_workers = [w for w in self._restore_workers if w.isRunning()]

    def toggle(self):
        if self._visible_state:
            self.hide_panel()
        else:
            self.show_panel()

    def show_panel(self):
        self._visible_state = True
        self._refresh()
        self.show()
        self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(self._final_x, self._final_y))
        self._anim.start()

    def hide_panel(self):
        self._visible_state = False
        self._anim.stop()
        self._anim.setStartValue(self.pos())
        self._anim.setEndValue(QPoint(self._hidden_x, self._final_y))
        self._anim.finished.connect(self._on_hide_anim_done)
        self._anim.start()

    def _on_hide_anim_done(self):
        if not self._visible_state:
            self.hide()
        try:
            self._anim.finished.disconnect(self._on_hide_anim_done)
        except Exception:
            pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()
        bg_path = QPainterPath()
        bg_path.addRoundedRect(0, 0, w, h, 16, 16)
        p.fillPath(bg_path, PANEL_BG)
        p.setPen(QPen(PANEL_BORDER, 1.0))
        border_path = QPainterPath()
        border_path.addRoundedRect(0.5, 0.5, w - 1, h - 1, 16, 16)
        p.drawPath(border_path)
        p.end()


class _PanelHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(60)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)

        title = QLabel("Workspace Sessions")
        title.setStyleSheet(f"""
            color: {TEXT_WHITE.name()}; font-size: 14px; font-weight: 700;
            font-family: 'Helvetica Neue', 'Helvetica', sans-serif; background: transparent;
        """)
        layout.addWidget(title)
        layout.addStretch()

        hint = QLabel("Ctrl+Shift+Space")
        hint.setStyleSheet(f"""
            color: {TEXT_MUTED.name()}; font-size: 10px;
            font-family: 'Helvetica Neue', 'Helvetica', sans-serif;
            background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08);
            border-radius: 5px; padding: 3px 7px;
        """)
        layout.addWidget(hint)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(PANEL_BORDER, 1.0))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


class _PanelFooter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 0, 18, 0)

        hint = QLabel("Drag any window to the right edge of your screen to save it")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"""
            color: {TEXT_MUTED.name()}; font-size: 10px;
            font-family: 'Helvetica Neue', 'Helvetica', sans-serif; background: transparent;
        """)
        layout.addWidget(hint)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setPen(QPen(PANEL_BORDER, 1.0))
        p.drawLine(0, 0, self.width(), 0)
        p.end()
