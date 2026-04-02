"""
ui/wallet_panel.py — Hotkey-toggled floating wallet panel.

v10 changes:
  • Skeleton shimmer animation completely removed (no vertical line artifacts)
  • Clean solid color transition between states
  • Simplified paint logic, no timer-based background animations
"""

from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QScrollArea, QFrame, QApplication, QGraphicsDropShadowEffect,
    QSizePolicy,
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QRectF, QPoint, pyqtProperty, QThread, pyqtSignal,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QPen,
    QLinearGradient, QFontMetrics,
)
import db

# ── Grayscale Palette ─────────────────────────────────────────────────────────
GRAY_BASE     = QColor("#2a2a2a")  # Card default
GRAY_HOVER    = QColor("#454545")  # Hover state - noticeably different
GRAY_DARK     = QColor("#1f1f1f")  # Deep background
GRAY_DEEP     = QColor("#1a1a1a")  # Panel background
GRAY_ROW      = QColor("#353535")  # Item rows

BORDER        = QColor("#505050")  # Subtle borders
BORDER_CARD   = QColor("#555555")  # Card borders
TEXT_PRIMARY  = QColor("#e9e9e9")  # Near white
TEXT_DIM      = QColor("#999999")  # Medium gray
TEXT_MUTED    = QColor("#666666")  # Darker gray
ACCENT_DEL    = QColor("#e3616a")  # Keep red for delete
ACCENT_GREEN  = QColor("#5cb85c")  # Softer green
ACCENT_AMBER  = QColor("#f0ad4e")  # Softer amber

ICON_TINTS = [
    (QColor("#555555"), QColor("#2a2a2a")),
    (QColor("#4a4a4a"), QColor("#333333")),
    (QColor("#525252"), QColor("#2e2e2e")),
    (QColor("#484848"), QColor("#2c2c2c")),
    (QColor("#505050"), QColor("#303030")),
    (QColor("#464646"), QColor("#2d2d2d")),
]

PANEL_WIDTH      = 340
PANEL_HEIGHT     = 580
CARD_H_COLL      = 76
CARD_ITEM_H      = 38
CARD_FOOTER_H    = 48
CARD_EXPAND_CAP  = 6

DEL_W, DEL_H   = 26, 18
DEL_MARGIN_R   = 10
DEL_MARGIN_T   = 10

_FONT_FAMILY = "'Inter', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', sans-serif"


def _font(size: int, bold: bool = False) -> QFont:
    f = QFont("Inter", size)
    if bold:
        f.setWeight(QFont.Weight.Bold)
    return f


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

        # Expand animation (height only)
        self._t = 0.0
        self._anim = QPropertyAnimation(self, b"expandT", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._reload_items()
        self._sync_height()
        self._restore_bar_y = 9999

    def _reload_items(self):
        self._items = db.get_items(self._session["id"])

    def _expanded_h(self) -> int:
        n = min(len(self._items), CARD_EXPAND_CAP)
        return CARD_H_COLL + 12 + n * CARD_ITEM_H + CARD_FOOTER_H

    def _target_h(self) -> int:
        return int(CARD_H_COLL + (self._expanded_h() - CARD_H_COLL) * self._t)

    def _sync_height(self):
        self.setFixedHeight(self._target_h())

    def _del_rect(self) -> QRect:
        w = self.width()
        x = w - DEL_MARGIN_R - DEL_W
        return QRect(x, DEL_MARGIN_T, DEL_W, DEL_H)

    def getExpandT(self) -> float:
        return self._t

    def setExpandT(self, v: float):
        self._t = v
        self._sync_height()
        self.update()

    expandT = pyqtProperty(float, getExpandT, setExpandT)

    def update_session(self, s: dict):
        self._session = s
        self._reload_items()
        if self._anim.state() != QPropertyAnimation.State.Running:
            self._sync_height()
        self.update()

    def set_restoring(self, v: bool):
        self._restoring = v
        self.update()

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

        # Delete button
        dr = self._del_rect()
        if dr.contains(x, y) and self._t > 0.05:
            self.delete_requested.emit(self._session["id"])
            return

        # Restore bar
        if self._t > 0.5 and y >= self._restore_bar_y:
            if not self._restoring:
                self.restore_requested.emit(self._session["id"])
            return

        # Item row remove
        if self._t > 0.3 and y > CARD_H_COLL + 8:
            row_idx = (y - CARD_H_COLL - 12) // CARD_ITEM_H
            if 0 <= row_idx < len(self._items) and x > w - 38:
                self.remove_item.emit(self._items[row_idx]["id"])

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        t    = self._t
        w    = self.width()
        h    = self.height()
        sess = self._session
        r    = 18.0

        # ── Clean Solid Background ────────────────────────────────────────────
        # Simple interpolation between base and hover color - no animations
        def lerp_color(a: QColor, b: QColor, f: float) -> QColor:
            return QColor(
                int(a.red()   + (b.red()   - a.red())   * f),
                int(a.green() + (b.green() - a.green()) * f),
                int(a.blue()  + (b.blue()  - a.blue())  * f),
            )
        
        bg = lerp_color(GRAY_BASE, GRAY_HOVER, t)
        
        card_path = QPainterPath()
        card_path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.fillPath(card_path, bg)

        # ── Clean 1px Border ──────────────────────────────────────────────────
        border_alpha = int(70 + 50 * t)
        p.setPen(QPen(QColor(85, 85, 85, border_alpha), 1.0))
        border_path = QPainterPath()
        border_path.addRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), r, r)
        p.drawPath(border_path)

        # ── Icon ──────────────────────────────────────────────────────────────
        ic_top, ic_bot = ICON_TINTS[self._index % len(ICON_TINTS)]
        icon_x, icon_y, icon_w, icon_h = 12, 13, 50, 50
        
        ip = QPainterPath()
        ip.addRoundedRect(QRectF(icon_x, icon_y, icon_w, icon_h), 14, 14)
        ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        ig.setColorAt(0.0, ic_top)
        ig.setColorAt(1.0, ic_bot)
        p.fillPath(ip, ig)

        p.setPen(QColor(255, 255, 255, 240))
        p.setFont(_font(16, bold=True))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter,
                   sess.get("name", "?")[0].upper())

        # ── Session Name ──────────────────────────────────────────────────────
        name_font = _font(12, bold=True)
        name_max  = w - 82 - DEL_W - DEL_MARGIN_R - 10
        p.setPen(TEXT_PRIMARY)
        p.setFont(name_font)
        p.drawText(QRect(72, 10, name_max, 24),
                   Qt.AlignmentFlag.AlignVCenter,
                   _elide(sess.get("name", "Session"), name_font, name_max))

        # ── Timestamp ─────────────────────────────────────────────────────────
        p.setPen(TEXT_MUTED)
        p.setFont(_font(9))
        p.drawText(QRect(72, 34, w - 82, 20),
                   Qt.AlignmentFlag.AlignVCenter,
                   _time_ago(sess.get("updated_at", "")))

        # ── Item Summary ──────────────────────────────────────────────────────
        n_a = sum(1 for i in self._items if i["type"] == "app")
        n_u = sum(1 for i in self._items if i["type"] == "url")
        n_f = sum(1 for i in self._items if i["type"] == "file")
        parts = (
            ([f"{n_a} app{'s' if n_a != 1 else ''}"]  if n_a else []) +
            ([f"{n_u} url{'s' if n_u != 1 else ''}"]  if n_u else []) +
            ([f"{n_f} file{'s' if n_f != 1 else ''}"] if n_f else [])
        )
        p.setPen(TEXT_DIM)
        p.setFont(_font(9))
        p.drawText(QRect(72, 54, w - 82, 18),
                   Qt.AlignmentFlag.AlignVCenter,
                   " · ".join(parts) if parts else "empty")

        # ── Delete Button ─────────────────────────────────────────────────────
        if t > 0.05:
            a = int(min(t * 2.5, 1.0) * 220)
            dr = self._del_rect()
            p.setOpacity(a / 255.0)
            dp = QPainterPath()
            dp.addRoundedRect(QRectF(dr), 6, 6)
            p.fillPath(dp, QColor(ACCENT_DEL.red(), ACCENT_DEL.green(),
                                  ACCENT_DEL.blue(), 30))
            p.setPen(QColor(ACCENT_DEL.red(), ACCENT_DEL.green(),
                            ACCENT_DEL.blue(), a))
            p.setFont(_font(9, bold=True))
            p.drawText(dr, Qt.AlignmentFlag.AlignCenter, "✕")
            p.setOpacity(1.0)

        # ── Expanded Section ──────────────────────────────────────────────────
        if t > 0.04:
            fade = min(t * 3.0, 1.0)
            p.setOpacity(fade)

            # Separator
            sep_grad = QLinearGradient(0, CARD_H_COLL, w, CARD_H_COLL)
            sep_grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
            sep_grad.setColorAt(0.15, QColor(90, 90, 90, 60))
            sep_grad.setColorAt(0.85, QColor(90, 90, 90, 60))
            sep_grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.setPen(QPen(sep_grad, 1.0))
            p.drawLine(0, CARD_H_COLL, w, CARD_H_COLL)

            item_font  = _font(10)
            badge_font = _font(8)
            visible    = self._items[:CARD_EXPAND_CAP]

            for idx, item in enumerate(visible):
                ry = CARD_H_COLL + 12 + idx * CARD_ITEM_H
                rh = CARD_ITEM_H - 4

                # Row background
                row_grad = QLinearGradient(0, ry, w, ry)
                row_grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
                row_grad.setColorAt(0.04, QColor(GRAY_ROW.red(),
                                                  GRAY_ROW.green(),
                                                  GRAY_ROW.blue(), 100))
                row_grad.setColorAt(0.96, QColor(GRAY_ROW.red(),
                                                  GRAY_ROW.green(),
                                                  GRAY_ROW.blue(), 100))
                row_grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
                rp = QPainterPath()
                rp.addRoundedRect(QRectF(0, ry, w, rh), 12, 12)
                p.fillPath(rp, row_grad)

                p.setPen(TEXT_DIM)
                p.setFont(_font(11))
                p.drawText(QRect(14, ry, 22, rh),
                           Qt.AlignmentFlag.AlignVCenter,
                           self.TYPE_ICONS.get(item["type"], "•"))

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

                if badge_text:
                    bx = w - 74
                    bp = QPainterPath()
                    bp.addRoundedRect(bx, ry + 10, 54, 14, 6, 6)
                    p.fillPath(bp, QColor(60, 60, 60, 180))
                    p.setPen(QColor(badge_color))
                    p.setFont(badge_font)
                    p.drawText(QRect(int(bx), ry + 10, 54, 14),
                               Qt.AlignmentFlag.AlignCenter,
                               badge_text[:12])

                p.setPen(QColor(100, 100, 100, 120))
                p.setFont(_font(13))
                p.drawText(QRect(w - 28, ry, 20, rh),
                           Qt.AlignmentFlag.AlignCenter, "×")

            # ── Restore Bar ───────────────────────────────────────────────────
            bar_y = h - CARD_FOOTER_H + 6
            self._restore_bar_y = bar_y

            bar_grad = QLinearGradient(0, bar_y, 0, bar_y + CARD_FOOTER_H - 10)
            hover_f = max(0.0, (t - 0.75) / 0.25)
            r_base = GRAY_BASE
            r_hov = QColor("#505050")
            r1 = QColor(
                int(r_base.red()   + (r_hov.red()   - r_base.red())   * hover_f),
                int(r_base.green() + (r_hov.green() - r_base.green()) * hover_f),
                int(r_base.blue()  + (r_hov.blue()  - r_base.blue())  * hover_f),
            )
            bar_grad.setColorAt(0.0, QColor(r1.red(), r1.green(), r1.blue(), 0))
            bar_grad.setColorAt(0.3, r1)
            bar_grad.setColorAt(1.0, r1)

            bp2 = QPainterPath()
            bp2.addRoundedRect(QRectF(8, bar_y, w - 16, CARD_FOOTER_H - 10), 12, 12)
            p.fillPath(bp2, bar_grad)

            p.setPen(TEXT_DIM if not self._restoring else TEXT_MUTED)
            p.setFont(_font(10, bold=True))
            p.drawText(QRect(8, bar_y, w - 16, CARD_FOOTER_H - 10),
                       Qt.AlignmentFlag.AlignCenter,
                       "Restoring…" if self._restoring else "↩  Restore Session")

            p.setOpacity(1.0)
        p.end()


# ── New Session Button ────────────────────────────────────────────────────────
class _NewSessionButton(QWidget):
    """Fixed 'New Session' button that appears at the top of the list"""
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(CARD_H_COLL)
        self.setStyleSheet("background: transparent;")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)
        self._hovered = False

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def mousePressEvent(self, e):
        # Trigger the new session creation in drop_zone
        # This would need to be connected from WalletPanel
        pass

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        w = self.width()
        h = self.height()
        r = 18.0

        # Background - hover effect
        bg_color = GRAY_HOVER if self._hovered else GRAY_BASE
        card_path = QPainterPath()
        card_path.addRoundedRect(QRectF(0, 0, w, h), r, r)
        p.fillPath(card_path, bg_color)

        # Border
        p.setPen(QPen(BORDER_CARD, 1.0))
        p.drawPath(card_path)

        # Icon (plus symbol) on the left
        icon_x, icon_y, icon_w, icon_h = 10, (h - 40) // 2, 40, 40
        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 9, 9)
        
        icon_bg = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        icon_bg.setColorAt(0.0, QColor("#5c4ba8"))
        icon_bg.setColorAt(1.0, QColor("#3d2d6b"))
        p.fillPath(icon_path, icon_bg)
        
        p.setPen(TEXT_PRIMARY)
        p.setFont(_font(18, bold=True))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter, "+")

        # Text on the right
        tx = icon_x + icon_w + 14
        tw = w - tx - 10

        p.setPen(TEXT_PRIMARY)
        p.setFont(_font(11, bold=True))
        p.drawText(QRect(tx, 8, tw, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "New Session")
        
        p.setPen(TEXT_DIM)
        p.setFont(_font(9))
        p.drawText(QRect(tx, 30, tw, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Create a new workspace")
        
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


    def _position_on_screen(self):
        s = QApplication.primaryScreen()
        if not s:
            return
        g = s.geometry()
        self._final_x  = g.x() + g.width() - PANEL_WIDTH - 20
        # Position at bottom instead of top
        self._final_y  = g.y() + g.height() - PANEL_HEIGHT - 20
        self._hidden_x = g.x() + g.width() + 10
        self.move(self._hidden_x, self._final_y)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"pos", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(400)

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self._header = _PanelHeader(self)
        outer.addWidget(self._header)

        # Scrollable area containing both new session button and existing sessions
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
                background: rgba(255,255,255,0.08);
                border-radius: 2px; min-height: 20px;
            }
            QScrollBar::add-line:vertical,
            QScrollBar::sub-line:vertical { height: 0; }
        """)

        self._list_widget = QWidget()
        self._list_widget.setStyleSheet("background: transparent;")
        self._list_layout = QVBoxLayout(self._list_widget)
        self._list_layout.setContentsMargins(10, 10, 10, 20)
        self._list_layout.setSpacing(8)

        # Add "New Session" button at the very top
        self._new_session_btn = _NewSessionButton(self)
        self._list_layout.addWidget(self._new_session_btn)

        self._scroll_area.setWidget(self._list_widget)
        outer.addWidget(self._scroll_area, 1)

        self._footer = _PanelFooter(self)
        outer.addWidget(self._footer)

    def _refresh(self):
        sessions = db.get_all_sessions()
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
        for c in self._session_cards:
            c.setParent(None)
            c.deleteLater()
        self._session_cards.clear()

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
                "color:#666;font-size:12px;padding:48px 20px;"
                f"font-family:{_FONT_FAMILY};"
            )
            self._list_layout.addWidget(e)
            self._list_layout.addStretch()
            return

        # Add all sessions - scrollbar will appear if needed
        for i, sess in enumerate(self._sessions):
            card = SessionCard(sess, i, self._list_widget)
            card.restore_requested.connect(self._on_restore)
            card.delete_requested.connect(self._on_delete)
            card.remove_item.connect(self._on_remove_item)
            self._session_cards.append(card)
            self._list_layout.addWidget(card)

        # Add stretch at end to push cards to top
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
        w, h = self.width(), self.height()
        r = 16

        shadow_offset = 8

        shadow_path = QPainterPath()
        shadow_path.addRoundedRect(
            shadow_offset/2,
            shadow_offset,
            w - shadow_offset,
            h - shadow_offset,
            r,
            r
        )
        p.fillPath(shadow_path, QColor(0, 0, 0, 80))

        # Main panel background
        bg = QPainterPath()
        bg.addRoundedRect(0, 0, w, h, r, r)
        panel_grad = QLinearGradient(0, 0, 0, h)
        panel_grad.setColorAt(0.0, QColor("#252525"))
        panel_grad.setColorAt(1.0, QColor("#1a1a1a"))
        p.fillPath(bg, panel_grad)

        p.setPen(QPen(BORDER, 1.0))
        bd = QPainterPath()
        bd.addRoundedRect(0.5, 0.5, w - 1, h - 1, r, r)
        p.drawPath(bd)
        p.end()
        
# ── Header ────────────────────────────────────────────────────────────────────
class _PanelHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)

        t = QLabel("Workspace Sessions")
        t.setStyleSheet(
            "color:#b0b0b0;"
            "font-size:13px;"
            "font-weight:700;"
            f"font-family:{_FONT_FAMILY};"
            "background:transparent;"
            "letter-spacing:0.3px;"
        )
        lay.addWidget(t)
        lay.addStretch()

    def paintEvent(self, e):
        p = QPainter(self)
        grad = QLinearGradient(0, self.height() - 1, self.width(), self.height() - 1)
        grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
        grad.setColorAt(0.1,  QColor(80, 80, 80, 100))
        grad.setColorAt(0.9,  QColor(80, 80, 80, 100))
        grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setPen(QPen(grad, 1.0))
        p.drawLine(0, self.height() - 1, self.width(), self.height() - 1)
        p.end()


# ── Footer ────────────────────────────────────────────────────────────────────
class _PanelFooter(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(38)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)

        h = QLabel("Drag any window to the right edge to save")
        h.setStyleSheet(
            "color:#555;"
            "font-size:9px;"
            f"font-family:{_FONT_FAMILY};"
            "background:transparent;"
        )
        lay.addWidget(h)

    def paintEvent(self, e):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
        grad.setColorAt(0.1,  QColor(60, 60, 60, 60))
        grad.setColorAt(0.9,  QColor(60, 60, 60, 60))
        grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setPen(QPen(grad, 1.0))
        p.drawLine(0, 0, self.width(), 0)
        p.end()