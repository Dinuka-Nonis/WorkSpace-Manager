"""
ui/wallet_panel.py — Hotkey-toggled floating wallet panel.

Changes:
  • Inspector rows show a profile badge for Chrome URLs.
    Green  = chrome-profile:<dir>   → confirmed, restores in correct profile.
    Amber  = chrome-profile-email:  → unconfirmed at save, restore will try to resolve.
  • [ProfileName] prefix stripped from display label (shown as badge instead).
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
    QPainter, QColor, QPainterPath, QFont, QPen, QLinearGradient
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
    QColor("#635bff"), QColor("#9bd86a"), QColor("#f59e0b"),
    QColor("#ef4444"), QColor("#06b6d4"), QColor("#ec4899"),
]
PANEL_WIDTH  = 360
PANEL_HEIGHT = 560


def _time_ago(ts: str) -> str:
    if not ts: return ""
    try:
        from datetime import datetime as dt
        s = int((dt.now() - dt.fromisoformat(ts)).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s//60}m ago"
        if s < 86400: return f"{s//3600}h ago"
        return f"{s//86400}d ago"
    except Exception: return ""


def _profile_badge(path_or_url: str) -> tuple[str, str]:
    """
    Returns (badge_text, color_hex) for a saved URL.
    Green  = confirmed profile dir
    Amber  = email hint only (unconfirmed)
    Empty  = no profile info (plain URL)
    """
    if path_or_url.startswith("chrome-profile:"):
        rest = path_or_url[len("chrome-profile:"):]
        if "|" in rest:
            return rest.split("|", 1)[0], "#42d778"
    elif path_or_url.startswith("chrome-profile-email:"):
        rest = path_or_url[len("chrome-profile-email:"):]
        if "|" in rest:
            email = rest.split("|", 1)[0]
            short = email.split("@")[0] if "@" in email else email
            return f"⚠ {short}", "#f59e0b"
    return "", ""


class _RestoreWorker(QThread):
    done = pyqtSignal(dict, int)
    def __init__(self, session_id, parent=None):
        super().__init__(parent); self._sid = session_id
        self.finished.connect(self.deleteLater)
    def run(self):
        import restore
        self.done.emit(restore.restore_session(self._sid), self._sid)


class SessionRow(QWidget):
    restore_requested = pyqtSignal(int)
    inspect_requested = pyqtSignal(int)
    delete_requested  = pyqtSignal(int)

    def __init__(self, session, index, parent=None):
        super().__init__(parent)
        self._session = session; self._index = index
        self._hovered = self._restoring = self._inspected = False
        self.setMouseTracking(True); self.setFixedHeight(72)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def update_session(self, s): self._session = s; self.update()
    def set_restoring(self, v): self._restoring = v; self.update()
    def set_inspected(self, v): self._inspected = v; self.update()
    def enterEvent(self, e): self._hovered = True;  self.update()
    def leaveEvent(self, e): self._hovered = False; self.update()

    def mousePressEvent(self, e):
        x, w = e.position().x(), self.width()
        if x > w - 90:                        self.restore_requested.emit(self._session["id"])
        elif x > w - 120 and self._hovered:   self.delete_requested.emit(self._session["id"])
        else:                                  self.inspect_requested.emit(self._session["id"])

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, sess = self.width(), self.height(), self._session

        if self._hovered or self._inspected:
            bg = QPainterPath(); bg.addRoundedRect(0, 2, w, h-4, 12, 12)
            p.fillPath(bg, QColor(255,255,255, 30 if self._inspected else 18))
        if self._inspected:
            p.fillRect(QRect(0,10,3,h-20), ICON_COLORS[self._index % len(ICON_COLORS)])

        ic = ICON_COLORS[self._index % len(ICON_COLORS)]
        ip = QPainterPath(); ip.addRoundedRect(16,18,36,36,8,8)
        g  = QLinearGradient(16,18,52,54)
        g.setColorAt(0, ic.lighter(130)); g.setColorAt(1, ic)
        p.fillPath(ip, g)
        p.setPen(QColor(255,255,255)); p.setFont(QFont("Helvetica Neue",14,QFont.Weight.Bold))
        p.drawText(QRect(16,18,36,36), Qt.AlignmentFlag.AlignCenter, sess.get("name","?")[0].upper())

        p.setPen(TEXT_WHITE); p.setFont(QFont("Helvetica Neue",11,QFont.Weight.Bold))
        p.drawText(QRect(66,14,w-170,24), Qt.AlignmentFlag.AlignVCenter, sess.get("name","Session"))

        p.setPen(TEXT_DIM); p.setFont(QFont("Helvetica Neue",9))
        p.drawText(QRect(w-90,14,78,24), Qt.AlignmentFlag.AlignRight|Qt.AlignmentFlag.AlignVCenter,
                   _time_ago(sess.get("updated_at","")))

        items  = db.get_items(sess["id"])
        n_a    = sum(1 for i in items if i["type"]=="app")
        n_u    = sum(1 for i in items if i["type"]=="url")
        n_f    = sum(1 for i in items if i["type"]=="file")
        parts  = ([f"{n_a} app{'s' if n_a!=1 else ''}"] if n_a else []) + \
                 ([f"{n_u} url{'s' if n_u!=1 else ''}"] if n_u else []) + \
                 ([f"{n_f} file{'s' if n_f!=1 else ''}"] if n_f else [])
        p.setPen(TEXT_DIM); p.setFont(QFont("Helvetica Neue",9))
        p.drawText(QRect(66,40,w-170,20), Qt.AlignmentFlag.AlignVCenter,
                   " · ".join(parts) if parts else "empty")
        p.setPen(TEXT_MUTED); p.setFont(QFont("Helvetica Neue",8))
        p.drawText(QRect(66,56,w-170,14), Qt.AlignmentFlag.AlignVCenter,
                   "▾ inspecting" if self._inspected else "▸ tap to inspect")

        if self._hovered:
            dp = QPainterPath(); dp.addRoundedRect(w-120,22,24,28,6,6)
            p.fillPath(dp, QColor(239,68,68,160))
            p.setPen(QColor(255,255,255)); p.setFont(QFont("Helvetica Neue",11,QFont.Weight.Bold))
            p.drawText(QRect(w-120,22,24,28), Qt.AlignmentFlag.AlignCenter, "×")
            bp = QPainterPath(); bp.addRoundedRect(w-88,22,74,28,8,8)
            p.fillPath(bp, ACCENT_GREEN if not self._restoring else QColor(255,255,255,20))
            p.setPen(QColor(0,0,0) if not self._restoring else TEXT_DIM)
            p.setFont(QFont("Helvetica Neue",9,QFont.Weight.Bold))
            p.drawText(QRect(w-88,22,74,28), Qt.AlignmentFlag.AlignCenter,
                       "Restoring…" if self._restoring else "Restore")
        p.end()


class _InspectorPanel(QWidget):
    closed       = pyqtSignal()
    item_removed = pyqtSignal(int)
    TYPE_ICONS   = {"url":"🔗","file":"📄","app":"⚡"}

    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self._session_id = session_id
        self.setStyleSheet("background: transparent;")
        self._build()

    def _build(self):
        if self.layout():
            while self.layout().count():
                it = self.layout().takeAt(0)
                if it.widget(): it.widget().deleteLater()
        else:
            lay = QVBoxLayout(self)
            lay.setContentsMargins(16,2,16,10); lay.setSpacing(3)

        lay = self.layout()

        hdr = QHBoxLayout(); hdr.setContentsMargins(0,0,0,4)
        lbl = QLabel("Items in this session")
        lbl.setStyleSheet("color:#888899;font-size:10px;")
        hdr.addWidget(lbl); hdr.addStretch()
        cb = QPushButton("×"); cb.setFixedSize(20,20)
        cb.setStyleSheet("QPushButton{color:#44445a;background:transparent;border:none;font-size:14px;padding:0;}"
                         "QPushButton:hover{color:#fff;}")
        cb.clicked.connect(self.closed.emit); hdr.addWidget(cb)
        lay.addLayout(hdr)

        items = db.get_items(self._session_id)
        if not items:
            e = QLabel("No items yet — drag windows or URLs here.")
            e.setWordWrap(True); e.setStyleSheet("color:#44445a;font-size:10px;padding:6px 0;")
            lay.addWidget(e); return

        for item in items:
            self._add_row(lay, item)

    def _add_row(self, lay, item):
        pou   = item.get("path_or_url","")
        label = item.get("label","")

        # Strip [Profile] / [⚠ email] prefix from label — show as badge instead.
        display = label
        if item["type"] == "url" and display.startswith("[") and "] " in display:
            display = display.split("] ", 1)[1]

        badge_text, badge_color = _profile_badge(pou) if item["type"] == "url" else ("","")

        row = QWidget()
        row.setMinimumHeight(34)
        row.setStyleSheet("background:rgba(255,255,255,0.05);border-radius:6px;")
        rl = QHBoxLayout(row); rl.setContentsMargins(8,0,4,0); rl.setSpacing(5)

        icon_lbl = QLabel(self.TYPE_ICONS.get(item["type"],"•"))
        icon_lbl.setFixedWidth(16)
        icon_lbl.setStyleSheet("font-size:11px;background:transparent;")
        rl.addWidget(icon_lbl)

        name_lbl = QLabel(display)
        name_lbl.setStyleSheet("color:#ccccdd;font-size:10px;background:transparent;")
        name_lbl.setToolTip(f"Stored: {pou}\nLabel: {label}")
        rl.addWidget(name_lbl, 1)

        if badge_text:
            b = QLabel(badge_text)
            tip = ("✓ Will restore in this Chrome profile" if "⚠" not in badge_text else
                   "⚠ Profile not confirmed at save time — restore will try to resolve from your Google account email")
            b.setToolTip(tip)
            b.setStyleSheet(
                f"color:{badge_color};font-size:8px;"
                f"background:rgba(255,255,255,0.07);border-radius:3px;padding:1px 4px;")
            rl.addWidget(b)

        type_badge = QLabel(item["type"].upper())
        type_badge.setStyleSheet("color:#44445a;font-size:8px;background:transparent;")
        rl.addWidget(type_badge)

        rm = QPushButton("×"); rm.setFixedSize(20,20)
        rm.setToolTip(f"Remove '{label}'")
        rm.setStyleSheet("QPushButton{color:#44445a;background:transparent;border:none;"
                         "font-size:13px;padding:0;border-radius:4px;}"
                         "QPushButton:hover{color:#fff;background:rgba(239,68,68,0.6);}")
        iid = item["id"]
        rm.clicked.connect(lambda _, i=iid: self.item_removed.emit(i))
        rl.addWidget(rm)
        lay.addWidget(row)

    def refresh(self): self._build()


class WalletPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible_state   = False
        self._sessions        = []
        self._session_rows    = []
        self._restore_workers = []
        self._inspected_id    = None
        self._inspector_widget= None
        self._setup_window(); self._build_ui()
        self._position_on_screen(); self._setup_animation(); self._refresh()
        t = QTimer(self); t.timeout.connect(self._refresh); t.start(4000)

    def _setup_window(self):
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)

    def _position_on_screen(self):
        s = QApplication.primaryScreen()
        if not s: return
        g = s.geometry()
        self._final_x  = g.x() + g.width() - PANEL_WIDTH - 20
        self._final_y  = g.y() + 20
        self._hidden_x = g.x() + g.width() + 10
        self.move(self._hidden_x, self._final_y)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic); self._anim.setDuration(280)

    def _build_ui(self):
        outer = QVBoxLayout(self); outer.setContentsMargins(0,0,0,0); outer.setSpacing(0)
        self._header = _PanelHeader(self); outer.addWidget(self._header)
        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll_area.setStyleSheet("""
            QScrollArea{background:transparent;border:none;}
            QScrollBar:vertical{background:transparent;width:4px;margin:0;}
            QScrollBar::handle:vertical{background:rgba(255,255,255,0.12);border-radius:2px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}""")
        self._list_widget = QWidget(); self._list_widget.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(8,4,8,12); self._list_layout.setSpacing(2)
        self._list_layout.addStretch()
        self._scroll_area.setWidget(self._list_widget); outer.addWidget(self._scroll_area, 1)
        self._footer = _PanelFooter(self); outer.addWidget(self._footer)

    def _refresh(self):
        self._sessions = db.get_all_sessions(); self._rebuild_rows(); self.update()

    def _rebuild_rows(self):
        inspected = self._inspected_id
        for r in self._session_rows: r.setParent(None); r.deleteLater()
        self._session_rows.clear()
        if self._inspector_widget:
            self._inspector_widget.setParent(None); self._inspector_widget.deleteLater()
            self._inspector_widget = None
        while self._list_layout.count():
            it = self._list_layout.takeAt(0)
            if it.widget(): it.widget().deleteLater()

        if not self._sessions:
            e = QLabel("No sessions yet.\nDrag a window to the right edge\nto create one.")
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.setStyleSheet("color:#44445a;font-size:13px;padding:40px 20px;")
            self._list_layout.addWidget(e); self._list_layout.addStretch(); return

        for i, sess in enumerate(self._sessions):
            row = SessionRow(sess, i, self._list_widget)
            row.restore_requested.connect(self._on_restore)
            row.inspect_requested.connect(self._on_inspect)
            row.delete_requested.connect(self._on_delete)
            self._session_rows.append(row); self._list_layout.addWidget(row)
            if inspected is not None and sess["id"] == inspected:
                row.set_inspected(True)
                self._inspector_widget = _InspectorPanel(inspected, self._list_widget)
                self._inspector_widget.closed.connect(self._close_inspector)
                self._inspector_widget.item_removed.connect(self._on_remove_item)
                self._list_layout.addWidget(self._inspector_widget)
        self._list_layout.addStretch()

    def _on_delete(self, sid):
        db.delete_session(sid)
        if self._inspected_id == sid: self._inspected_id = None
        self._refresh()

    def _on_inspect(self, sid):
        if self._inspected_id == sid: self._close_inspector(); return
        self._inspected_id = sid; self._rebuild_rows()

    def _close_inspector(self): self._inspected_id = None; self._rebuild_rows()

    def _on_remove_item(self, item_id):
        db.delete_item(item_id)
        if self._inspector_widget: self._inspector_widget.refresh()
        self._refresh()

    def _on_restore(self, sid):
        for r in self._session_rows:
            if r._session["id"] == sid: r.set_restoring(True); break
        w = _RestoreWorker(sid, parent=self)
        w.done.connect(self._on_restore_done); self._restore_workers.append(w); w.start()

    def _on_restore_done(self, result, sid):
        for r in self._session_rows:
            if r._session["id"] == sid: r.set_restoring(False); break
        self._restore_workers = [w for w in self._restore_workers if w.isRunning()]

    def toggle(self):
        if self._visible_state: self.hide_panel()
        else: self.show_panel()

    def show_panel(self):
        self._visible_state = True; self._refresh(); self.show(); self.raise_()
        self._anim.stop()
        self._anim.setStartValue(self.pos()); self._anim.setEndValue(QPoint(self._final_x, self._final_y))
        self._anim.start()

    def hide_panel(self):
        self._visible_state = False; self._anim.stop()
        self._anim.setStartValue(self.pos()); self._anim.setEndValue(QPoint(self._hidden_x, self._final_y))
        self._anim.finished.connect(self._on_hide_anim_done); self._anim.start()

    def _on_hide_anim_done(self):
        if not self._visible_state: self.hide()
        try: self._anim.finished.disconnect(self._on_hide_anim_done)
        except Exception: pass

    def paintEvent(self, event):
        p = QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QPainterPath(); bg.addRoundedRect(0,0,w,h,16,16)
        p.fillPath(bg, PANEL_BG)
        p.setPen(QPen(PANEL_BORDER, 1.0))
        bd = QPainterPath(); bd.addRoundedRect(0.5,0.5,w-1,h-1,16,16)
        p.drawPath(bd); p.end()


class _PanelHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedHeight(60)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self); lay.setContentsMargins(18,0,18,0)
        t = QLabel("Workspace Sessions")
        t.setStyleSheet(f"color:{TEXT_WHITE.name()};font-size:14px;font-weight:700;"
                        f"font-family:'Helvetica Neue','Helvetica',sans-serif;background:transparent;")
        lay.addWidget(t); lay.addStretch()
        h = QLabel("Ctrl+Shift+Space")
        h.setStyleSheet(f"color:{TEXT_MUTED.name()};font-size:10px;"
                        f"font-family:'Helvetica Neue','Helvetica',sans-serif;"
                        f"background:rgba(255,255,255,0.05);border:1px solid rgba(255,255,255,0.08);"
                        f"border-radius:5px;padding:3px 7px;")
        lay.addWidget(h)
    def paintEvent(self, e):
        p = QPainter(self); p.setPen(QPen(PANEL_BORDER, 1.0))
        p.drawLine(0, self.height()-1, self.width(), self.height()-1); p.end()


class _PanelFooter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent); self.setFixedHeight(52)
        self.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(self); lay.setContentsMargins(18,0,18,0)
        h = QLabel("Drag any window to the right edge of your screen to save it")
        h.setWordWrap(True)
        h.setStyleSheet(f"color:{TEXT_MUTED.name()};font-size:10px;"
                        f"font-family:'Helvetica Neue','Helvetica',sans-serif;background:transparent;")
        lay.addWidget(h)
    def paintEvent(self, e):
        p = QPainter(self); p.setPen(QPen(PANEL_BORDER, 1.0))
        p.drawLine(0, 0, self.width(), 0); p.end()
