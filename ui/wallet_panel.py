"""
ui/wallet_panel.py — Hotkey-toggled floating wallet panel.

Redesign v4:
  • Card visual language ported from drop_zone.py:
      – Dark #1a1a24 card background (matching CARD_BG)
      – Gradient icon square (same icon_grad logic as drop zone)
      – Text layout mirrors drop_zone textBox: bold title + dim subtitle
  • Animation bug-fixes:
      – Each card owns ONE QPropertyAnimation on a float field (_t).
        setFixedHeight is driven only inside setExpandT so there's no
        competing resize call.
      – enterEvent / leaveEvent stop the anim and restart from current
        value (no jump-to-end artifacts).
      – Cards are re-used (update_session) instead of destroyed/rebuilt on
        every 4-second refresh, so hover state is never lost mid-hover.
      – Restore bar hit-test uses a stored _restore_bar_y that is
        recalculated every paintEvent instead of reading self.height()
        (which lags during animation).
  • All original functionality preserved.
"""

from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QApplication, QGraphicsDropShadowEffect,
    QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QPoint, pyqtProperty, QThread, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QPen,
    QLinearGradient, QFontMetrics,
)
import db

# ── Palette (aligned with drop_zone.py) ──────────────────────────────────────
BG_PANEL      = QColor("#111118")
BG_CARD       = QColor("#1a1a24")      # drop_zone CARD_BG
BG_CARD_HOV   = QColor("#252535")      # drop_zone CARD_HOVER_BG
BG_ITEM_ROW   = QColor("#1e1e2e")
BORDER        = QColor("#2a2a3a")
BORDER_CARD   = QColor("#2e2e42")
TEXT_PRIMARY  = QColor("#e9e9f0")
TEXT_DIM      = QColor("#888899")      # drop_zone TEXT_DIM
TEXT_MUTED    = QColor("#44445a")
ACCENT_DEL    = QColor("#e3616a")
ACCENT_GREEN  = QColor("#42d778")      # drop_zone CONFIRM_GREEN
ACCENT_AMBER  = QColor("#f59e0b")
RESTORE_BG    = QColor("#1e1e2e")
RESTORE_HOV   = QColor("#252540")

# Icon gradients — same palette used for each card (cycles through)
ICON_GRADS = [
    (QColor("#d7cfcf"), QColor("#9198e5")),  # drop_zone default: grey→indigo
    (QColor("#9198e5"), QColor("#712020")),  # indigo→red
    (QColor("#5a9e6f"), QColor("#2d6b42")),  # green
    (QColor("#5a8a9e"), QColor("#2d5a6b")),  # teal
    (QColor("#9e8a5a"), QColor("#6b5a2d")),  # amber
    (QColor("#7a5a9e"), QColor("#4a2d6b")),  # purple
]

PANEL_WIDTH      = 340
PANEL_HEIGHT     = 580
CARD_H_COLL      = 76      # collapsed height (matches drop_zone CARD_H=72 + padding)
CARD_ITEM_H      = 36
CARD_FOOTER_H    = 44
CARD_EXPAND_CAP  = 6


def _elide(text: str, font: QFont, max_px: int) -> str:
    return QFontMetrics(font).elidedText(text, Qt.TextElideMode.ElideRight, max_px)


def _time_ago(ts: str) -> str:
    if not ts:
        return ""
    try:
        s = int((datetime.now() - datetime.fromisoformat(ts)).total_seconds())
        if s < 60:    return "just now"
        if s < 3600:  return f"{s // 60}m ago"
        if s < 86400: return f"{s // 3600}h ago"
        return f"{s // 86400}d ago"
    except Exception:
        return ""


def _profile_badge(pou: str) -> tuple[str, str]:
    if pou.startswith("chrome-profile:"):
        rest = pou[len("chrome-profile:"):]
        if "|" in rest:
            return rest.split("|", 1)[0], ACCENT_GREEN.name()
    elif pou.startswith("chrome-profile-email:"):
        rest = pou[len("chrome-profile-email:"):]
        if "|" in rest:
            email = rest.split("|", 1)[0]
            short = email.split("@")[0] if "@" in email else email
            return f"⚠ {short}", ACCENT_AMBER.name()
    return "", ""


# ── Worker ────────────────────────────────────────────────────────────────────
class _RestoreWorker(QThread):
    done = pyqtSignal(dict, int)

    def __init__(self, session_id, parent=None):
        super().__init__(parent)
        self._sid = session_id
        self.finished.connect(self.deleteLater)

    def run(self):
        import restore
        self.done.emit(restore.restore_session(self._sid), self._sid)


# ── Session Card ──────────────────────────────────────────────────────────────
class SessionCard(QWidget):
    restore_requested = pyqtSignal(int)
    delete_requested  = pyqtSignal(int)
    remove_item       = pyqtSignal(int)

    TYPE_ICONS = {"url": "🔗", "file": "📄", "app": "⚡"}

    def __init__(self, session: dict, index: int, parent=None):
        super().__init__(parent)
        self._session    = session
        self._index      = index
        self._restoring  = False
        self._items: list = []

        # ── Single animation field: 0.0 = collapsed, 1.0 = expanded ──────────
        self._t = 0.0

        self._anim = QPropertyAnimation(self, b"expandT", self)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._reload_items()
        self._sync_height()

        # Cache for restore-bar hit rect (set in paintEvent)
        self._restore_bar_y = 9999

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _reload_items(self):
        self._items = db.get_items(self._session["id"])

    def _expanded_h(self) -> int:
        n = min(len(self._items), CARD_EXPAND_CAP)
        return CARD_H_COLL + 8 + n * CARD_ITEM_H + CARD_FOOTER_H

    def _target_h(self) -> int:
        """Height for current _t value."""
        return int(CARD_H_COLL + (self._expanded_h() - CARD_H_COLL) * self._t)

    def _sync_height(self):
        self.setFixedHeight(self._target_h())

    # ── Animated property ─────────────────────────────────────────────────────
    def getExpandT(self) -> float:
        return self._t

    def setExpandT(self, v: float):
        self._t = v
        self._sync_height()
        self.update()

    expandT = pyqtProperty(float, getExpandT, setExpandT)

    # ── Public update (called by WalletPanel._smart_refresh) ─────────────────
    def update_session(self, s: dict):
        self._session = s
        self._reload_items()
        # Re-sync height only when not animating (avoids fighting the anim)
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._sync_height()
        self.update()

    def set_restoring(self, v: bool):
        self._restoring = v
        self.update()

    # ── Mouse ─────────────────────────────────────────────────────────────────
    def enterEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def mousePressEvent(self, e):
        x = int(e.position().x())
        y = int(e.position().y())
        w = self.width()

        # Delete × — top-right of header area, only when partially expanded
        if self._t > 0.3 and x > w - 42 and y < CARD_H_COLL:
            self.delete_requested.emit(self._session["id"])
            return

        # Restore bar — use cached _restore_bar_y (accurate from last paint)
        if self._t > 0.5 and y >= self._restore_bar_y:
            if not self._restoring:
                self.restore_requested.emit(self._session["id"])
            return

        # Item remove ×
        if self._t > 0.3 and y > CARD_H_COLL + 4:
            row_idx = (y - CARD_H_COLL - 8) // CARD_ITEM_H
            if 0 <= row_idx < len(self._items) and x > w - 38:
                self.remove_item.emit(self._items[row_idx]["id"])

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        t    = self._t
        w    = self.width()
        h    = self.height()
        sess = self._session

        # ── Card background — interpolates BG_CARD → BG_CARD_HOV ─────────────
        def lerp_color(a: QColor, b: QColor, f: float) -> QColor:
            return QColor(
                int(a.red()   + (b.red()   - a.red())   * f),
                int(a.green() + (b.green() - a.green()) * f),
                int(a.blue()  + (b.blue()  - a.blue())  * f),
            )

        bg = lerp_color(BG_CARD, BG_CARD_HOV, t)
        card_path = QPainterPath()
        card_path.addRoundedRect(0, 0, w, h, 14, 14)
        p.fillPath(card_path, bg)
        p.setPen(QPen(BORDER_CARD, 1.0))
        bd = QPainterPath()
        bd.addRoundedRect(0.5, 0.5, w - 1, h - 1, 14, 14)
        p.drawPath(bd)

        # ── Gradient icon square (matches drop_zone icon block) ───────────────
        ic_top, ic_bot = ICON_GRADS[self._index % len(ICON_GRADS)]
        icon_x, icon_y, icon_w, icon_h = 12, 13, 50, 50
        ip = QPainterPath()
        ip.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)
        ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        ig.setColorAt(0.0, ic_top)
        ig.setColorAt(1.0, ic_bot)
        p.fillPath(ip, ig)

        # Letter initial in icon
        p.setPen(QColor(255, 255, 255, 230))
        p.setFont(QFont("Helvetica Neue", 16, QFont.Weight.Bold))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter,
                   sess.get("name", "?")[0].upper())

        # ── Session name (bold, matches drop_zone title style) ────────────────
        name_font = QFont("Helvetica Neue", 12, QFont.Weight.Bold)
        name_max  = w - 82 - 58
        p.setPen(TEXT_PRIMARY)
        p.setFont(name_font)
        p.drawText(QRect(72, 12, name_max, 22),
                   Qt.AlignmentFlag.AlignVCenter,
                   _elide(sess.get("name", "Session"), name_font, name_max))

        # ── Timestamp (dim, right-aligned) ────────────────────────────────────
        p.setPen(TEXT_MUTED)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(QRect(w - 70, 12, 58, 22),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _time_ago(sess.get("updated_at", "")))

        # ── Item summary (dim subtitle, matches drop_zone body text) ──────────
        n_a = sum(1 for i in self._items if i["type"] == "app")
        n_u = sum(1 for i in self._items if i["type"] == "url")
        n_f = sum(1 for i in self._items if i["type"] == "file")
        parts = (
            ([f"{n_a} app{'s' if n_a != 1 else ''}"]  if n_a else []) +
            ([f"{n_u} url{'s' if n_u != 1 else ''}"]  if n_u else []) +
            ([f"{n_f} file{'s' if n_f != 1 else ''}"] if n_f else [])
        )
        p.setPen(TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(QRect(72, 38, w - 82, 18),
                   Qt.AlignmentFlag.AlignVCenter,
                   " · ".join(parts) if parts else "empty")

        # ── Delete × pill (fades in with hover) ───────────────────────────────
        if t > 0.05:
            a = int(min(t * 2.5, 1.0) * 255)
            p.setOpacity(a / 255.0)
            dp = QPainterPath()
            dp.addRoundedRect(w - 38, 15, 26, 22, 5, 5)
            p.fillPath(dp, QColor(ACCENT_DEL.red(), ACCENT_DEL.green(), ACCENT_DEL.blue(), 30))
            p.setPen(QColor(ACCENT_DEL.red(), ACCENT_DEL.green(), ACCENT_DEL.blue(), a))
            p.setFont(QFont("Helvetica Neue", 14, QFont.Weight.Bold))
            p.drawText(QRect(w - 38, 15, 26, 22), Qt.AlignmentFlag.AlignCenter, "×")
            p.setOpacity(1.0)

        # ── Expanded section ──────────────────────────────────────────────────
        if t > 0.04:
            fade = min(t * 3.0, 1.0)
            p.setOpacity(fade)

            # Separator
            p.setPen(QPen(BORDER, 1.0))
            p.drawLine(10, CARD_H_COLL, w - 10, CARD_H_COLL)

            item_font  = QFont("Helvetica Neue", 10)
            badge_font = QFont("Helvetica Neue", 8)
            visible    = self._items[:CARD_EXPAND_CAP]

            for idx, item in enumerate(visible):
                ry = CARD_H_COLL + 8 + idx * CARD_ITEM_H
                rh = CARD_ITEM_H - 3

                # Row bg (matches drop_zone BG_ITEM_ROW)
                rp = QPainterPath()
                rp.addRoundedRect(8, ry, w - 16, rh, 6, 6)
                p.fillPath(rp, BG_ITEM_ROW)

                # Type icon
                p.setPen(TEXT_DIM)
                p.setFont(QFont("Helvetica Neue", 11))
                p.drawText(QRect(14, ry, 22, rh),
                           Qt.AlignmentFlag.AlignVCenter,
                           self.TYPE_ICONS.get(item["type"], "•"))

                # Label — strip [Profile] prefix
                pou     = item.get("path_or_url", "")
                display = item.get("label", "")
                if item["type"] == "url" and display.startswith("[") and "] " in display:
                    display = display.split("] ", 1)[1]
                badge_text, badge_color = (
                    _profile_badge(pou) if item["type"] == "url" else ("", "")
                )

                lbl_max = w - (118 if badge_text else 78)
                p.setPen(TEXT_PRIMARY)
                p.setFont(item_font)
                p.drawText(QRect(38, ry, lbl_max, rh),
                           Qt.AlignmentFlag.AlignVCenter,
                           _elide(display, item_font, lbl_max))

                # Profile badge pill
                if badge_text:
                    bx = w - 74
                    bp = QPainterPath()
                    bp.addRoundedRect(bx, ry + 9, 54, 14, 3, 3)
                    p.fillPath(bp, QColor(40, 40, 55))
                    p.setPen(QColor(badge_color))
                    p.setFont(badge_font)
                    p.drawText(QRect(int(bx), ry + 9, 54, 14),
                               Qt.AlignmentFlag.AlignCenter,
                               badge_text[:12])

                # Remove ×
                p.setPen(QColor(60, 60, 80))
                p.setFont(QFont("Helvetica Neue", 13))
                p.drawText(QRect(w - 30, ry, 22, rh),
                           Qt.AlignmentFlag.AlignCenter, "×")

            # ── Restore bar ───────────────────────────────────────────────────
            #   Cache _restore_bar_y so mousePressEvent hits correctly.
            bar_y = h - CARD_FOOTER_H + 6
            self._restore_bar_y = bar_y
            bp2 = QPainterPath()
            bp2.addRoundedRect(8, bar_y, w - 16, CARD_FOOTER_H - 10, 8, 8)

            restore_bg = RESTORE_HOV if t > 0.85 else RESTORE_BG
            p.fillPath(bp2, restore_bg)

            # Thin accent line at top of restore bar
            p.setPen(QPen(ACCENT_GREEN.darker(160), 1.0))
            p.drawLine(18, bar_y, w - 18, bar_y)

            p.setPen(TEXT_DIM if not self._restoring else TEXT_MUTED)
            p.setFont(QFont("Helvetica Neue", 10, QFont.Weight.Bold))
            p.drawText(QRect(8, bar_y, w - 16, CARD_FOOTER_H - 10),
                       Qt.AlignmentFlag.AlignCenter,
                       "Restoring…" if self._restoring else "↩  Restore Session")

            p.setOpacity(1.0)
        p.end()


# ── Main Panel ────────────────────────────────────────────────────────────────
class WalletPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._visible_state   = False
        self._sessions        = []
        self._session_cards: list[SessionCard] = []
        self._restore_workers = []

        self._setup_window()
        self._build_ui()
        self._position_on_screen()
        self._setup_animation()
        self._refresh()

        t = QTimer(self)
        t.timeout.connect(self._refresh)
        t.start(4000)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)
        sh = QGraphicsDropShadowEffect(self)
        sh.setBlurRadius(60)
        sh.setXOffset(0)
        sh.setYOffset(16)
        sh.setColor(QColor(0, 0, 0, 120))
        self.setGraphicsEffect(sh)

    def _position_on_screen(self):
        s = QApplication.primaryScreen()
        if not s:
            return
        g = s.geometry()
        self._final_x  = g.x() + g.width() - PANEL_WIDTH - 20
        self._final_y  = g.y() + 20
        self._hidden_x = g.x() + g.width() + 10
        self.move(self._hidden_x, self._final_y)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(300)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = _PanelHeader(self)
        outer.addWidget(self._header)

        self._scroll_area = QScrollArea(self)
        self._scroll_area.setWidgetResizable(True)
        self._scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self._scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self._scroll_area.setStyleSheet("""
            QScrollArea { background: transparent; border: none; }
            QScrollBar:vertical {
                background: transparent; width: 3px; margin: 0;
            }
            QScrollBar::handle:vertical {
                background: rgba(255,255,255,0.06);
                border-radius: 2px; min-height: 20px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(10, 10, 10, 16)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()

        self._scroll_area.setWidget(self._list_widget)
        outer.addWidget(self._scroll_area, 1)

        self._footer = _PanelFooter(self)
        outer.addWidget(self._footer)

    # ── Refresh — smart: reuse cards, only rebuild when session count changes ─
    def _refresh(self):
        sessions = db.get_all_sessions()

        # Same session IDs in same order? Just update data.
        old_ids = [c._session["id"] for c in self._session_cards]
        new_ids = [s["id"] for s in sessions]

        if old_ids == new_ids:
            for card, sess in zip(self._session_cards, sessions):
                card.update_session(sess)
        else:
            self._sessions = sessions
            self._rebuild_cards()

        self.update()

    def _rebuild_cards(self):
        # Remove old cards without deleting them instantly (avoids flicker)
        for c in self._session_cards:
            c.setParent(None)
            c.deleteLater()
        self._session_cards.clear()

        # Clear layout
        while self._list_layout.count():
            it = self._list_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()

        if not self._sessions:
            e = QLabel(
                "No sessions yet.\n"
                "Drag a window to the right\n"
                "edge to create one."
            )
            e.setAlignment(Qt.AlignmentFlag.AlignCenter)
            e.setStyleSheet(
                "color:#44445a;font-size:12px;padding:48px 20px;"
                "font-family:'Helvetica Neue',sans-serif;"
            )
            self._list_layout.addWidget(e)
            self._list_layout.addStretch()
            return

        for i, sess in enumerate(self._sessions):
            card = SessionCard(sess, i, self._list_widget)
            card.restore_requested.connect(self._on_restore)
            card.delete_requested.connect(self._on_delete)
            card.remove_item.connect(self._on_remove_item)
            self._session_cards.append(card)
            self._list_layout.addWidget(card)

        self._list_layout.addStretch()

    def _on_delete(self, sid: int):
        db.delete_session(sid)
        self._sessions = db.get_all_sessions()
        self._rebuild_cards()

    def _on_remove_item(self, item_id: int):
        db.delete_item(item_id)
        self._sessions = db.get_all_sessions()
        self._rebuild_cards()

    def _on_restore(self, sid: int):
        for c in self._session_cards:
            if c._session["id"] == sid:
                c.set_restoring(True)
                break
        w = _RestoreWorker(sid, parent=self)
        w.done.connect(self._on_restore_done)
        self._restore_workers.append(w)
        w.start()

    def _on_restore_done(self, result: dict, sid: int):
        for c in self._session_cards:
            if c._session["id"] == sid:
                c.set_restoring(False)
                break
        self._restore_workers = [w for w in self._restore_workers if w.isRunning()]

    # ── Show / hide ───────────────────────────────────────────────────────────
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

    # ── Paint panel bg ────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QPainterPath()
        bg.addRoundedRect(0, 0, w, h, 16, 16)
        p.fillPath(bg, BG_PANEL)
        p.setPen(QPen(BORDER, 1.0))
        bd = QPainterPath()
        bd.addRoundedRect(0.5, 0.5, w - 1, h - 1, 16, 16)
        p.drawPath(bd)
        p.end()


# ── Header ────────────────────────────────────────────────────────────────────
class _PanelHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 14, 0)
        lay.setSpacing(0)

        t = QLabel("Workspace Sessions")
        t.setStyleSheet(
            "color:#e9e9f0;font-size:13px;font-weight:700;"
            "font-family:'Helvetica Neue','Helvetica',sans-serif;"
            "background:transparent;"
        )
        lay.addWidget(t)
        lay.addStretch()

        for key in ["⌃", "⇧", "Spc"]:
            k = QLabel(key)
            k.setStyleSheet(
                "color:#44445a;font-size:9px;"
                "background:#1a1a24;border-radius:4px;"
                "border:1px solid #2e2e42;padding:1px 5px;margin-left:3px;"
            )
            lay.addWidget(k)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(BORDER, 1.0))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


# ── Footer ────────────────────────────────────────────────────────────────────
class _PanelFooter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 0, 16, 0)

        h = QLabel("Drag any window to the right edge to save")
        h.setStyleSheet(
            "color:#2e2e42;font-size:9px;"
            "font-family:'Helvetica Neue',sans-serif;background:transparent;"
        )
        lay.addWidget(h)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setPen(QPen(BORDER, 1.0))
        p.drawLine(0, 0, self.width(), 0)
        p.end()