"""
ui/wallet_panel.py — Hotkey-toggled floating wallet panel.

v6 changes:
  • Fixed square bottom corners — panel now fully rounded everywhere
  • Glow animation is more vivid and visible (higher opacity, brighter colours)
  • Animation duration slowed to 420 ms (expand) and 400 ms (slide-in)
  • Delete × moved below the session name so it never overlaps the timestamp
  • Item rows use soft blended backgrounds — no harsh separator lines
  • Header simplified to just the title (keyboard hint removed)
  • Font: Helvetica Neue Bold throughout
  • "Restore Session" bar uses a blended gradient, no hard top line
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
    QLinearGradient, QConicalGradient, QRadialGradient,
    QFontMetrics,
)
import db

# ── Palette ───────────────────────────────────────────────────────────────────
BG_PANEL      = QColor("#0d0d14")
BG_CARD       = QColor("#13131e")
BG_CARD_HOV   = QColor("#1c1c2e")
BG_ITEM_ROW   = QColor("#181828")
BORDER        = QColor("#1e1e2e")
BORDER_CARD   = QColor("#252538")
TEXT_PRIMARY  = QColor("#e9e9f0")
TEXT_DIM      = QColor("#7a7a90")
TEXT_MUTED    = QColor("#3a3a54")
ACCENT_DEL    = QColor("#e3616a")
ACCENT_GREEN  = QColor("#42d778")
ACCENT_AMBER  = QColor("#f59e0b")
RESTORE_BG    = QColor("#14142a")
RESTORE_HOV   = QColor("#1e1e40")

# Vivid glow colours — brighter so the animation is clearly visible
GLOW_A        = QColor("#3a55cc")
GLOW_B        = QColor("#9a28b8")
GLOW_PURPLE   = QColor("#b8a8f0")
GLOW_PINK2    = QColor("#f0b8e8")

ICON_GRADS = [
    (QColor("#d7cfcf"), QColor("#9198e5")),
    (QColor("#9198e5"), QColor("#712020")),
    (QColor("#5a9e6f"), QColor("#2d6b42")),
    (QColor("#5a8a9e"), QColor("#2d5a6b")),
    (QColor("#9e8a5a"), QColor("#6b5a2d")),
    (QColor("#7a5a9e"), QColor("#4a2d6b")),
]

PANEL_WIDTH      = 340
PANEL_HEIGHT     = 580
CARD_H_COLL      = 76
CARD_ITEM_H      = 38
CARD_FOOTER_H    = 48
CARD_EXPAND_CAP  = 6

_FONT_FAMILY = "'Helvetica Neue', Helvetica, Arial, sans-serif"


def _font(size: int, bold: bool = False) -> QFont:
    f = QFont("Helvetica Neue", size)
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

        # ── Expand animation (slower: 420 ms) ────────────────────────────────
        self._t = 0.0
        self._anim = QPropertyAnimation(self, b"expandT", self)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        # ── Glow angle state ──────────────────────────────────────────────────
        self._glow_angle  = 83.0
        self._glow_target = 83.0

        self._glow_timer = QTimer(self)
        self._glow_timer.setInterval(16)
        self._glow_timer.timeout.connect(self._tick_glow)

        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._reload_items()
        self._sync_height()
        self._restore_bar_y = 9999

    # ── Glow tick ─────────────────────────────────────────────────────────────
    def _tick_glow(self):
        diff = self._glow_target - self._glow_angle
        if abs(diff) > 0.3:
            # Slower lerp factor (0.04 vs 0.06) for a more languid spin
            self._glow_angle += diff * 0.04
            self.update()
        else:
            self._glow_angle = self._glow_target
            if self._t < 0.01:
                self._glow_timer.stop()

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _reload_items(self):
        self._items = db.get_items(self._session["id"])

    def _expanded_h(self) -> int:
        n = min(len(self._items), CARD_EXPAND_CAP)
        return CARD_H_COLL + 12 + n * CARD_ITEM_H + CARD_FOOTER_H

    def _target_h(self) -> int:
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

    def update_session(self, s: dict):
        self._session = s
        self._reload_items()
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
        self._glow_target = self._glow_angle + 180.0
        self._glow_timer.start()

    def leaveEvent(self, e):
        self._anim.stop()
        self._anim.setStartValue(self._t)
        self._anim.setEndValue(0.0)
        self._anim.start()
        self._glow_target = round(self._glow_angle / 360) * 360 + 83.0
        self._glow_timer.start()

    def mousePressEvent(self, e):
        x = int(e.position().x())
        y = int(e.position().y())
        w = self.width()

        # Delete button is now in the lower-left of the collapsed header area
        if self._t > 0.3 and x < 48 and CARD_H_COLL - 24 < y < CARD_H_COLL - 4:
            self.delete_requested.emit(self._session["id"])
            return

        if self._t > 0.5 and y >= self._restore_bar_y:
            if not self._restoring:
                self.restore_requested.emit(self._session["id"])
            return

        if self._t > 0.3 and y > CARD_H_COLL + 8:
            row_idx = (y - CARD_H_COLL - 12) // CARD_ITEM_H
            if 0 <= row_idx < len(self._items) and x > w - 38:
                self.remove_item.emit(self._items[row_idx]["id"])

    # ── Glow border painter ────────────────────────────────────────────────────
    def _paint_glow_border(
        self, p: QPainter, w: int, h: int,
        angle: float, strength: float, r: float = 14.0,
    ):
        cx_mid = w / 2
        cy_mid = h / 2

        # Outer ambient radial glow (more opaque)
        for color, radius, base_alpha in [
            (GLOW_A, w * 1.0, 60),
            (GLOW_B, w * 0.8, 45),
        ]:
            a = int(base_alpha * strength)
            if a < 2:
                continue
            rg = QRadialGradient(cx_mid, cy_mid, radius)
            rg.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), a))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            glow_path = QPainterPath()
            glow_path.addRoundedRect(QRectF(-20, -12, w + 40, h + 24), r + 8, r + 8)
            p.setOpacity(1.0)
            p.fillPath(glow_path, rg)

        # Dark inner shadow ring
        dark_path = QPainterPath()
        dark_path.addRoundedRect(QRectF(-1, -1, w + 2, h + 2), r + 1, r + 1)
        cg_dark = QConicalGradient(cx_mid, cy_mid, angle + 2)
        cg_dark.setColorAt(0.00, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.05, QColor("#0a0830"))
        cg_dark.setColorAt(0.10, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.60, QColor("#2d0840"))
        cg_dark.setColorAt(0.65, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.setOpacity(strength)
        p.fillPath(dark_path, cg_dark)

        # Conic border ring (brighter stops)
        border_outer = QPainterPath()
        border_outer.addRoundedRect(QRectF(-2, -2, w + 4, h + 4), r + 2, r + 2)
        border_inner = QPainterPath()
        border_inner.addRoundedRect(QRectF(0, 0, w, h), r, r)
        border_ring = border_outer.subtracted(border_inner)

        cg_border = QConicalGradient(cx_mid, cy_mid, angle)
        cg_border.setColorAt(0.00, QColor("#181420"))
        cg_border.setColorAt(0.05, GLOW_A)
        cg_border.setColorAt(0.14, QColor("#181420"))
        cg_border.setColorAt(0.50, QColor("#181420"))
        cg_border.setColorAt(0.60, GLOW_B)
        cg_border.setColorAt(0.64, QColor("#181420"))
        cg_border.setColorAt(1.00, QColor("#181420"))
        p.setOpacity(strength)
        p.fillPath(border_ring, cg_border)

        # Soft inner highlight ring
        white_outer = QPainterPath()
        white_outer.addRoundedRect(QRectF(0, 0, w, h), r, r)
        white_inner = QPainterPath()
        white_inner.addRoundedRect(QRectF(2, 2, w - 4, h - 4), r - 2, r - 2)
        white_ring = white_outer.subtracted(white_inner)

        cg_white = QConicalGradient(cx_mid, cy_mid, angle + 3)
        cg_white.setColorAt(0.00, QColor(0, 0, 0, 0))
        cg_white.setColorAt(0.04, GLOW_PURPLE)
        cg_white.setColorAt(0.08, QColor(0, 0, 0, 0))
        cg_white.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_white.setColorAt(0.55, GLOW_PINK2)
        cg_white.setColorAt(0.60, QColor(0, 0, 0, 0))
        cg_white.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.setOpacity(strength * 0.8)
        p.fillPath(white_ring, cg_white)

        p.setOpacity(1.0)

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        t    = self._t
        w    = self.width()
        h    = self.height()
        sess = self._session
        r    = 14.0

        glow_strength = min(t * 1.6, 1.0)

        # ── Glow border ───────────────────────────────────────────────────────
        if glow_strength > 0.02:
            self._paint_glow_border(p, w, h, self._glow_angle, glow_strength, r)

        # ── Card background (blended gradient) ────────────────────────────────
        def lerp_color(a: QColor, b: QColor, f: float) -> QColor:
            return QColor(
                int(a.red()   + (b.red()   - a.red())   * f),
                int(a.green() + (b.green() - a.green()) * f),
                int(a.blue()  + (b.blue()  - a.blue())  * f),
            )

        bg_top = lerp_color(BG_CARD, BG_CARD_HOV, t)
        bg_bot = lerp_color(
            QColor("#0f0f1a"), QColor("#161626"), t
        )
        card_path = QPainterPath()
        card_path.addRoundedRect(0, 0, w, h, r, r)

        card_grad = QLinearGradient(0, 0, 0, h)
        card_grad.setColorAt(0.0, bg_top)
        card_grad.setColorAt(1.0, bg_bot)
        p.fillPath(card_path, card_grad)

        # Subtle border
        border_alpha = int(80 + 60 * t)
        p.setPen(QPen(QColor(BORDER_CARD.red(), BORDER_CARD.green(),
                             BORDER_CARD.blue(), border_alpha), 1.0))
        bd = QPainterPath()
        bd.addRoundedRect(0.5, 0.5, w - 1, h - 1, r, r)
        p.drawPath(bd)

        # ── Gradient icon ─────────────────────────────────────────────────────
        ic_top, ic_bot = ICON_GRADS[self._index % len(ICON_GRADS)]
        icon_x, icon_y, icon_w, icon_h = 12, 13, 50, 50
        ip = QPainterPath()
        ip.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)
        ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        ig.setColorAt(0.0, ic_top)
        ig.setColorAt(1.0, ic_bot)
        p.fillPath(ip, ig)

        p.setPen(QColor(255, 255, 255, 230))
        p.setFont(_font(16, bold=True))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter,
                   sess.get("name", "?")[0].upper())

        # ── Session name ──────────────────────────────────────────────────────
        name_font = _font(12, bold=True)
        name_max  = w - 82 - 70
        p.setPen(TEXT_PRIMARY)
        p.setFont(name_font)
        p.drawText(QRect(72, 10, name_max, 24),
                   Qt.AlignmentFlag.AlignVCenter,
                   _elide(sess.get("name", "Session"), name_font, name_max))

        # ── Timestamp (top-right, always visible, no overlap) ─────────────────
        p.setPen(TEXT_MUTED)
        p.setFont(_font(9))
        p.drawText(QRect(w - 68, 10, 56, 24),
                   Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                   _time_ago(sess.get("updated_at", "")))

        # ── Item summary ──────────────────────────────────────────────────────
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
        p.drawText(QRect(72, 38, w - 82, 20),
                   Qt.AlignmentFlag.AlignVCenter,
                   " · ".join(parts) if parts else "empty")

        # ── Delete × — now tucked below name, left side, fades in on hover ───
        if t > 0.05:
            a = int(min(t * 2.5, 1.0) * 200)
            p.setOpacity(a / 255.0)
            # Small pill in the lower-left corner of the header row
            del_x, del_y = 72, CARD_H_COLL - 22
            dp = QPainterPath()
            dp.addRoundedRect(del_x, del_y, 22, 14, 4, 4)
            p.fillPath(dp, QColor(ACCENT_DEL.red(), ACCENT_DEL.green(),
                                  ACCENT_DEL.blue(), 28))
            p.setPen(QColor(ACCENT_DEL.red(), ACCENT_DEL.green(),
                            ACCENT_DEL.blue(), a))
            p.setFont(_font(9, bold=True))
            p.drawText(QRect(del_x, del_y, 22, 14),
                       Qt.AlignmentFlag.AlignCenter, "✕")
            p.setOpacity(1.0)

        # ── Expanded section ──────────────────────────────────────────────────
        if t > 0.04:
            fade = min(t * 3.0, 1.0)
            p.setOpacity(fade)

            # Soft gradient separator instead of a hard line
            sep_grad = QLinearGradient(0, CARD_H_COLL, w, CARD_H_COLL)
            sep_grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
            sep_grad.setColorAt(0.15, QColor(60, 60, 90, 80))
            sep_grad.setColorAt(0.85, QColor(60, 60, 90, 80))
            sep_grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
            p.setPen(QPen(sep_grad, 1.0))
            p.drawLine(0, CARD_H_COLL, w, CARD_H_COLL)

            item_font  = _font(10)
            badge_font = _font(8)
            visible    = self._items[:CARD_EXPAND_CAP]

            for idx, item in enumerate(visible):
                ry = CARD_H_COLL + 12 + idx * CARD_ITEM_H
                rh = CARD_ITEM_H - 4

                # Blended row — subtle gradient, no hard outline
                row_grad = QLinearGradient(0, ry, w, ry)
                row_grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
                row_grad.setColorAt(0.04, QColor(BG_ITEM_ROW.red(),
                                                  BG_ITEM_ROW.green(),
                                                  BG_ITEM_ROW.blue(), 120))
                row_grad.setColorAt(0.96, QColor(BG_ITEM_ROW.red(),
                                                  BG_ITEM_ROW.green(),
                                                  BG_ITEM_ROW.blue(), 120))
                row_grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
                rp = QPainterPath()
                rp.addRoundedRect(0, ry, w, rh, 8, 8)
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
                    bp.addRoundedRect(bx, ry + 10, 54, 14, 3, 3)
                    p.fillPath(bp, QColor(30, 30, 50, 180))
                    p.setPen(QColor(badge_color))
                    p.setFont(badge_font)
                    p.drawText(QRect(int(bx), ry + 10, 54, 14),
                               Qt.AlignmentFlag.AlignCenter,
                               badge_text[:12])

                # Row remove × — dimmer, blends in
                p.setPen(QColor(70, 70, 100, 160))
                p.setFont(_font(13))
                p.drawText(QRect(w - 28, ry, 20, rh),
                           Qt.AlignmentFlag.AlignCenter, "×")

            # ── Restore bar — blended gradient, no hard separator line ────────
            bar_y = h - CARD_FOOTER_H + 6
            self._restore_bar_y = bar_y

            bar_grad = QLinearGradient(0, bar_y, 0, bar_y + CARD_FOOTER_H - 10)
            hover_f = max(0.0, (t - 0.75) / 0.25)
            r1 = QColor(
                int(RESTORE_BG.red()   + (RESTORE_HOV.red()   - RESTORE_BG.red())   * hover_f),
                int(RESTORE_BG.green() + (RESTORE_HOV.green() - RESTORE_BG.green()) * hover_f),
                int(RESTORE_BG.blue()  + (RESTORE_HOV.blue()  - RESTORE_BG.blue())  * hover_f),
            )
            bar_grad.setColorAt(0.0, QColor(r1.red(), r1.green(), r1.blue(), 0))
            bar_grad.setColorAt(0.3, r1)
            bar_grad.setColorAt(1.0, r1)

            bp2 = QPainterPath()
            bp2.addRoundedRect(8, bar_y, w - 16, CARD_FOOTER_H - 10, 10, 10)
            p.fillPath(bp2, bar_grad)

            p.setPen(TEXT_DIM if not self._restoring else TEXT_MUTED)
            p.setFont(_font(10, bold=True))
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
        sh.setBlurRadius(72)
        sh.setXOffset(0)
        sh.setYOffset(20)
        sh.setColor(QColor(0, 0, 0, 160))
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
        self._anim.setDuration(400)

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
                background: rgba(255,255,255,0.05);
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
        self._list_layout.addStretch()

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
                "color:#2e2e44;font-size:12px;padding:48px 20px;"
                f"font-family:{_FONT_FAMILY};"
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

        # Fully rounded panel — gradient top-to-bottom for depth
        bg = QPainterPath()
        bg.addRoundedRect(0, 0, w, h, 18, 18)
        panel_grad = QLinearGradient(0, 0, 0, h)
        panel_grad.setColorAt(0.0, QColor("#13131e"))
        panel_grad.setColorAt(1.0, QColor("#0a0a12"))
        p.fillPath(bg, panel_grad)

        p.setPen(QPen(BORDER, 1.0))
        bd = QPainterPath()
        bd.addRoundedRect(0.5, 0.5, w - 1, h - 1, 18, 18)
        p.drawPath(bd)
        p.end()


# ── Header — clean title only ─────────────────────────────────────────────────
class _PanelHeader(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(52)
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)

        t = QLabel("Workspace Sessions")
        t.setStyleSheet(
            "color:#c8c8d8;"
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
        # Soft gradient separator instead of hard line
        grad = QLinearGradient(0, self.height() - 1, self.width(), self.height() - 1)
        grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
        grad.setColorAt(0.1,  QColor(40, 40, 60, 120))
        grad.setColorAt(0.9,  QColor(40, 40, 60, 120))
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
            "color:#222238;"
            "font-size:9px;"
            f"font-family:{_FONT_FAMILY};"
            "background:transparent;"
        )
        lay.addWidget(h)

    def paintEvent(self, e):
        p = QPainter(self)
        grad = QLinearGradient(0, 0, self.width(), 0)
        grad.setColorAt(0.0,  QColor(0, 0, 0, 0))
        grad.setColorAt(0.1,  QColor(30, 30, 50, 80))
        grad.setColorAt(0.9,  QColor(30, 30, 50, 80))
        grad.setColorAt(1.0,  QColor(0, 0, 0, 0))
        p.setPen(QPen(grad, 1.0))
        p.drawLine(0, 0, self.width(), 0)
        p.end()