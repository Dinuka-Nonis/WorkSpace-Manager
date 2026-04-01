"""
ui/drop_zone.py — Folder-style drop zone overlay.

v5 changes (New Session card):
  • The "＋ New Session" card now has a spinning conic-gradient glow border
    inspired by the CSS reference (purple #402fb5 ↔ pink #cf30aa).
  • The ＋ icon cycles through a colour animation (blue→purple→pink→blue).
  • A dark grid background sits inside the card (matches the CSS .grid).
  • On hover the border-glow rotates 180°; on idle it rests at its base angle.
  • All driven by a single QTimer + angle float — zero extra widgets needed.

Everything else is unchanged from v4.
"""

from __future__ import annotations

import math
import sys
from PyQt6.QtWidgets import QWidget, QApplication, QLineEdit
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QRectF, pyqtProperty, QPoint, QSequentialAnimationGroup,
    QParallelAnimationGroup, QPauseAnimation, QAbstractAnimation,
    QElapsedTimer,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QLinearGradient, QConicalGradient,
    QFont, QFontMetrics, QPen, QTransform, QBrush, QRadialGradient,
)

import db

# ── Dimensions ────────────────────────────────────────────────────────────────
FOLDER_W        = 130
FOLDER_H        = 108
EDGE_PEEK       = 0
TOP_MARGIN      = 60
WIDGET_W        = 360
WIDGET_H        = 600

CARD_W          = 310
CARD_H          = 72
CARD_X          = 20
CARD_GAP        = 10
CARDS_START_Y   = FOLDER_H + 24

PAPER_COUNT     = 3

# ── Colors ────────────────────────────────────────────────────────────────────
FOLDER_BODY     = QColor("#F5A623")
FOLDER_BODY2    = QColor("#E8941A")
FOLDER_TAB      = QColor("#C87A10")
FOLDER_LID      = QColor("#F5A623")

CARD_BG         = QColor("#1a1a24")
CARD_HOVER_BG   = QColor("#252535")
GRAD_TOP        = QColor("#d7cfcf")
GRAD_BOT        = QColor("#9198e5")
GRAD_HOVER_TOP  = QColor("#9198e5")
GRAD_HOVER_BOT  = QColor("#712020")
NEW_CARD_BG     = QColor("#010201")          # matches CSS input bg
NEW_CARD_HOV    = QColor("#0d0d18")
TEXT_WHITE      = QColor(255, 255, 255)
TEXT_DIM        = QColor(136, 136, 153)
CONFIRM_GREEN   = QColor("#42d778")

# Glow palette (matches CSS #402fb5 / #cf30aa)
GLOW_BLUE       = QColor("#402fb5")
GLOW_PINK       = QColor("#cf30aa")
GLOW_PURPLE     = QColor("#a099d8")
GLOW_PINK2      = QColor("#dfa2da")


class _CardState:
    def __init__(self, index: int):
        self.index   = index
        self.y_offset = 0.0
        self.hovered  = False
        self.scale    = 1.0


class DropZoneOverlay(QWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self._sessions:           list[dict]  = []
        self._card_states:        list[_CardState] = []
        self._pending_app:        dict | None = None
        self._active_session_id:  int | None  = None
        self._picker_mode         = False
        self._drop_confirmed      = False
        self._confirmed_label     = ""
        self._confirmed_card_i    = -1
        self._folder_hovered      = False
        self._cards_visible       = False

        self._slide_x = 1.0
        self._fan     = 0.0

        self._card_drops:  list[float] = []
        self._card_scales: list[float] = []
        self._confirm_alpha = 0.0

        # ── Glow animation state ──────────────────────────────────────────────
        # _glow_angle: current rotation of the conic gradient (degrees)
        # _glow_target: where it should animate to
        # _glow_hovered: whether new-session card is hovered
        self._glow_angle   = 83.0     # resting angle (matches CSS rotate(83deg))
        self._glow_target  = 83.0
        self._glow_hovered = False
        self._plus_hue     = 240.0    # HSV hue for the + icon colour cycle

        # Master animation timer — 60 fps, drives glow rotation + + colour
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)   # ~60 fps
        self._anim_timer.timeout.connect(self._tick_glow)
        self._anim_timer.start()

        self._setup_window()
        self._position_on_screen()
        self._refresh_sessions()
        self._build_slide_anim()

        self._new_sess_input = QLineEdit(self)
        self._new_sess_input.setPlaceholderText("Session name…")
        self._new_sess_input.setFixedHeight(32)
        self._new_sess_input.hide()
        self._new_sess_input.returnPressed.connect(self._create_new_session)
        self._new_sess_input.setStyleSheet("""
            QLineEdit {
                background: #0d0d18; color: #ffffff;
                border: none; border-radius: 10px;
                padding: 0 12px; font-size: 13px;
                font-family: 'Helvetica Neue', 'Helvetica', sans-serif;
            }
            QLineEdit:focus { background: #12122a; }
        """)

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self._finish_confirm)

        _ref = QTimer(self)
        _ref.timeout.connect(self._refresh_sessions)
        _ref.start(5000)

    # ── Glow tick ─────────────────────────────────────────────────────────────
    def _tick_glow(self):
        """Animate glow_angle toward target and cycle + icon hue."""
        changed = False

        # Angle easing
        diff = self._glow_target - self._glow_angle
        if abs(diff) > 0.3:
            self._glow_angle += diff * 0.06   # smooth lerp
            changed = True
        else:
            self._glow_angle = self._glow_target

        # + icon hue cycles continuously when card is visible
        if self._cards_visible or self._picker_mode:
            self._plus_hue = (self._plus_hue + 0.6) % 360
            changed = True

        if changed:
            self.update()

    def _set_glow_hover(self, hovered: bool):
        if hovered == self._glow_hovered:
            return
        self._glow_hovered = hovered
        if hovered:
            # Spin 180° forward on hover (matches CSS -97deg offset)
            self._glow_target = self._glow_angle + 180.0
        else:
            # Spin back to nearest resting position
            self._glow_target = round(self._glow_angle / 360) * 360 + 83.0

    # ── Window setup ──────────────────────────────────────────────────────────
    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

    def _position_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        self._screen_geo = geo
        self.setGeometry(
            geo.x() + geo.width() - WIDGET_W,
            geo.y() + TOP_MARGIN,
            WIDGET_W,
            WIDGET_H,
        )
        self._apply_slide(1.0)

    # ── Slide property ────────────────────────────────────────────────────────
    def _build_slide_anim(self):
        self._slide_anim = QPropertyAnimation(self, b"slideX", self)
        self._slide_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._slide_anim.setDuration(320)

    def getSlideX(self) -> float:
        return self._slide_x

    def setSlideX(self, v: float):
        self._slide_x = v
        self._apply_slide(v)
        self.update()

    slideX = pyqtProperty(float, getSlideX, setSlideX)

    def _apply_slide(self, v: float):
        if not hasattr(self, "_screen_geo"):
            return
        geo    = self._screen_geo
        offset = int(WIDGET_W * v)
        self.move(
            geo.x() + geo.width() - WIDGET_W + offset,
            geo.y() + TOP_MARGIN,
        )

    def _slide_in(self):
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide_x)
        self._slide_anim.setEndValue(0.0)
        self._slide_anim.start()
        QApplication.instance().installEventFilter(self)

    def _slide_out(self):
        self._cards_visible = False
        self._hide_cards()
        self._close_fan()
        QTimer.singleShot(250, self.__do_slide_out)

    def __do_slide_out(self):
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide_x)
        self._slide_anim.setEndValue(1.0)
        self._slide_anim.start()
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass

    # ── Fan property ──────────────────────────────────────────────────────────
    def getFan(self) -> float:
        return self._fan

    def setFan(self, v: float):
        self._fan = v
        self.update()

    fan = pyqtProperty(float, getFan, setFan)

    def _open_fan(self):
        if not hasattr(self, "_fan_anim"):
            self._fan_anim = QPropertyAnimation(self, b"fan", self)
            self._fan_anim.setEasingCurve(QEasingCurve.Type.OutBack)
            self._fan_anim.setDuration(380)
        self._fan_anim.stop()
        self._fan_anim.setStartValue(self._fan)
        self._fan_anim.setEndValue(1.0)
        self._fan_anim.start()

    def _close_fan(self):
        if not hasattr(self, "_fan_anim"):
            return
        self._fan_anim.stop()
        self._fan_anim.setEasingCurve(QEasingCurve.Type.InCubic)
        self._fan_anim.setDuration(220)
        self._fan_anim.setStartValue(self._fan)
        self._fan_anim.setEndValue(0.0)
        self._fan_anim.start()

    # ── Card drop animations ──────────────────────────────────────────────────
    def _drop_cards(self):
        n = len(self._sessions) + 1
        while len(self._card_drops) < n:
            self._card_drops.append(0.0)
        while len(self._card_scales) < n:
            self._card_scales.append(1.0)
        self._card_drops  = self._card_drops[:n]
        self._card_scales = self._card_scales[:n]

        if hasattr(self, "_drop_anims"):
            for a in self._drop_anims:
                a.stop()
        if hasattr(self, "_drop_timers"):
            for t in self._drop_timers:
                t.stop()

        self._drop_anims  = []
        self._drop_timers = []

        for i in range(n):
            if self._card_drops[i] >= 0.99:
                continue
            anim = _CardDropAnim(self, i, self._card_drops)
            anim.setDuration(340)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(self._card_drops[i])
            anim.setEndValue(1.0)

            delay_timer = QTimer(self)
            delay_timer.setSingleShot(True)
            def _start(a=anim): a.start()
            delay_timer.timeout.connect(_start)
            delay_timer.start(i * 80)
            self._drop_anims.append(anim)
            self._drop_timers.append(delay_timer)

    def _hide_cards(self):
        if hasattr(self, "_drop_timers"):
            for t in self._drop_timers:
                t.stop()
        if hasattr(self, "_drop_anims"):
            for a in self._drop_anims:
                a.stop()
        self._card_drops  = []
        self._card_scales = []
        self.update()

    # ── Public API ────────────────────────────────────────────────────────────
    def drop_zone_final_rect(self) -> tuple[int, int, int, int]:
        if not hasattr(self, "_screen_geo"):
            s = QApplication.primaryScreen()
            geo = s.geometry()
        else:
            geo = self._screen_geo
        return (
            geo.x() + geo.width() - WIDGET_W,
            geo.y() + TOP_MARGIN,
            WIDGET_W,
            WIDGET_H,
        )

    def on_drag_started(self, app_info: dict):
        self._pending_app         = app_info
        self._drop_confirmed      = False
        self._picker_mode         = False
        self._cards_visible       = False
        self._cards_dropped_once  = False
        self._folder_hovered      = False
        self._new_sess_input.hide()
        self._hide_cards()
        self._fan = 0.0
        self._refresh_sessions()
        self._slide_in()
        self.update()

    def on_dropped(self, app_info: dict):
        cursor_local = self.mapFromGlobal(self.cursor().pos())
        cx, cy = cursor_local.x(), cursor_local.y()
        card_i = self._card_at(cx, cy)
        if card_i is not None:
            if card_i == len(self._sessions):
                self._show_new_session_input(app_info)
            else:
                self._pending_app       = app_info
                self._picker_mode       = True
                self._active_session_id = self._sessions[card_i]["id"]
                self.update()
            return
        self._pending_app = app_info
        self._picker_mode = True
        if not self._cards_visible:
            self._cards_visible = True
            self._open_fan()
            self._drop_cards()
        self.update()

    def on_drag_cancelled(self):
        self._pending_app        = None
        self._picker_mode        = False
        self._cards_dropped_once = False
        self._new_sess_input.hide()
        if not self._drop_confirmed:
            self._slide_out()

    def set_active_session(self, session_id: int):
        self._active_session_id = session_id
        self._refresh_sessions()
        self.update()

    # ── Internal session ops ──────────────────────────────────────────────────
    def _refresh_sessions(self):
        self._sessions = db.get_all_sessions()[:6]
        if not self._active_session_id and self._sessions:
            self._active_session_id = self._sessions[0]["id"]
        self.update()

    def _save_to_session(self, app_info: dict, confirmed_card: int = 0):
        self._confirm_timer.stop()
        self._picker_mode = False
        sid = self._active_session_id
        if sid is None:
            if self._sessions:
                sid = self._sessions[0]["id"]
            else:
                sid = db.create_session("My Workspace")
                self._active_session_id = sid
        item = {
            "type":        app_info.get("type", "app"),
            "path_or_url": app_info.get("path_or_url", ""),
            "label":       app_info.get("label", "Unknown"),
        }
        if item["path_or_url"]:
            db.add_items_bulk(sid, [item])
        self._confirmed_label  = item["label"]
        self._confirmed_card_i = confirmed_card
        self._drop_confirmed   = True
        self._pending_app      = None
        self._refresh_sessions()
        self.update()
        self._confirm_timer.start(2000)

    def _show_new_session_input(self, app_info: dict):
        self._pending_app = app_info
        n_cards = len(self._sessions)
        input_y = CARDS_START_Y + n_cards * (CARD_H + CARD_GAP) + 8
        self._new_sess_input.setGeometry(CARD_X, input_y, CARD_W, 36)
        self._new_sess_input.clear()
        self._new_sess_input.show()
        self._new_sess_input.setFocus()
        self.update()

    def _create_new_session(self):
        name = self._new_sess_input.text().strip() or "My Workspace"
        self._new_sess_input.hide()
        sid = db.create_session(name)
        self._active_session_id = sid
        self._refresh_sessions()
        if self._pending_app:
            idx = next((i for i, s in enumerate(self._sessions) if s["id"] == sid), 0)
            self._save_to_session(self._pending_app, confirmed_card=idx)

    def _finish_confirm(self):
        self._drop_confirmed     = False
        self._confirmed_card_i   = -1
        self._cards_dropped_once = False
        self._slide_out()

    def _cancel(self):
        self._confirm_timer.stop()
        self._pending_app        = None
        self._picker_mode        = False
        self._drop_confirmed     = False
        self._cards_dropped_once = False
        self._new_sess_input.hide()
        self._slide_out()

    # ── Hit-testing ───────────────────────────────────────────────────────────
    def _folder_rect(self) -> QRect:
        return QRect(WIDGET_W - FOLDER_W - 4, 0, FOLDER_W, FOLDER_H)

    def _card_rect(self, index: int) -> QRect:
        y = CARDS_START_Y + index * (CARD_H + CARD_GAP)
        return QRect(CARD_X, y, CARD_W, CARD_H)

    def _card_at(self, x: int, y: int) -> int | None:
        total = len(self._sessions) + 1
        for i in range(total):
            if i >= len(self._card_drops):
                continue
            drop_frac = self._card_drops[i]
            if drop_frac < 0.05:
                continue
            base_y   = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            actual_y = base_y - int((1.0 - drop_frac) * (CARD_H + 40))
            r = QRect(CARD_X, actual_y, CARD_W, CARD_H)
            if r.contains(x, y):
                return i
        return None

    # ── Mouse ─────────────────────────────────────────────────────────────────
    def mouseMoveEvent(self, event):
        x, y = int(event.position().x()), int(event.position().y())
        fr   = self._folder_rect()
        now_over_folder = fr.contains(x, y)

        if now_over_folder and not self._folder_hovered:
            self._folder_hovered = True
            self._open_fan()
            if not getattr(self, "_cards_dropped_once", False):
                self._cards_dropped_once = True
                self._cards_visible = True
                self._drop_cards()
            self.update()
        elif not now_over_folder and self._folder_hovered:
            self._folder_hovered = False

        # Update card hover states
        changed = False
        total = len(self._sessions) + 1
        while len(self._card_scales) < total:
            self._card_scales.append(1.0)

        new_card_i = len(self._sessions)
        for i in range(total):
            base_y   = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            drop_frac = self._card_drops[i] if i < len(self._card_drops) else 0.0
            actual_y = base_y - int((1.0 - drop_frac) * (CARD_H + 40))
            r     = QRect(CARD_X, actual_y, CARD_W, CARD_H)
            hover = r.contains(x, y) and drop_frac > 0.5
            want  = 1.05 if hover else 1.0
            if abs(self._card_scales[i] - want) > 0.001:
                self._card_scales[i] = want
                changed = True
            # Glow hover for new-session card
            if i == new_card_i:
                self._set_glow_hover(hover)

        if changed:
            self.update()

    def mousePressEvent(self, event):
        x, y = int(event.position().x()), int(event.position().y())
        card_i = self._card_at(x, y)
        if card_i is not None:
            if card_i == len(self._sessions):
                self._show_new_session_input(self._pending_app)
            else:
                self._active_session_id = self._sessions[card_i]["id"]
                if self._pending_app or self._picker_mode:
                    app = self._pending_app
                    self._pending_app = None
                    self._picker_mode = False
                    self._save_to_session(app, confirmed_card=card_i)
                else:
                    self.update()
            return
        if y > WIDGET_H - 52:
            self._cancel()

    def eventFilter(self, obj, event):
        from PyQt6.QtCore import QEvent
        if event.type() == QEvent.Type.KeyPress:
            if event.key() == Qt.Key.Key_Escape:
                self._cancel()
                return True
        return False

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
        else:
            super().keyPressEvent(event)

    def enterEvent(self, event):
        self.update()

    def leaveEvent(self, event):
        self._folder_hovered = False
        self._set_glow_hover(False)
        self.update()

    # ── Paint ─────────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        if self._drop_confirmed:
            self._paint_folder(p)
            self._paint_cards(p)
            self._paint_confirm_overlay(p)
        else:
            self._paint_folder(p)
            if self._cards_visible or self._picker_mode:
                self._paint_cards(p)
            if self._picker_mode:
                self._paint_picker_hint(p)

        self._paint_cancel_hint(p)
        p.end()

    # ── Folder painting ───────────────────────────────────────────────────────
    def _paint_folder(self, p: QPainter):
        fan = self._fan
        fr  = self._folder_rect()
        fx, fy, fw, fh = fr.x(), fr.y(), fr.width(), fr.height()
        r = 12

        amber_600 = QColor("#d97706")
        amber_500 = QColor("#f59e0b")
        amber_400 = QColor("#fbbf24")
        zinc_400  = QColor("#a1a1aa")
        zinc_300  = QColor("#d4d4d8")
        zinc_200  = QColor("#e4e4e7")

        back = QPainterPath()
        back.moveTo(fx,        fy + 16)
        back.lineTo(fx + fw - r, fy + 16)
        back.quadTo(fx + fw,   fy + 16,  fx + fw, fy + 16 + r)
        back.lineTo(fx + fw,   fy + fh - r)
        back.quadTo(fx + fw,   fy + fh,  fx + fw - r, fy + fh)
        back.lineTo(fx + r,    fy + fh)
        back.quadTo(fx,        fy + fh,  fx, fy + fh - r)
        back.lineTo(fx,        fy + 16)
        back.closeSubpath()
        p.fillPath(back, amber_600)

        tw, th = int(fw * 0.42), int(fh * 0.135)
        tab = QPainterPath()
        tab.moveTo(fx,        fy + 16)
        tab.lineTo(fx + tw,   fy + 16)
        tab.lineTo(fx + tw,   fy + 16 - th + r)
        tab.quadTo(fx + tw,   fy + 16 - th, fx + tw - r, fy + 16 - th)
        tab.lineTo(fx + r,    fy + 16 - th)
        tab.quadTo(fx,        fy + 16 - th, fx, fy + 16 - th + r)
        tab.lineTo(fx,        fy + 16)
        tab.closeSubpath()
        p.fillPath(tab, amber_600)

        notch = QPainterPath()
        notch.moveTo(fx + tw,            fy + 16 - th + th * 0.35)
        notch.lineTo(fx + tw,            fy + 16)
        notch.lineTo(fx + tw + th * 0.5, fy + 16)
        notch.closeSubpath()
        p.fillPath(notch, amber_600)

        inset   = 5
        px, py_bot = fx + inset, fy + fh
        pw, ph  = fw - inset * 2, fh - inset * 2

        for angle_max, color in [(20, zinc_400), (30, zinc_300), (38, zinc_200)]:
            angle_rad = math.radians(fan * angle_max)
            sy        = math.cos(angle_rad)
            p_top = py_bot - ph * sy
            pp = QPainterPath()
            pp.addRoundedRect(px, p_top, pw, ph * sy, 10, 10)
            p.fillPath(pp, color)

        lid_h         = fh * 0.975
        lid_bot       = fy + fh
        lid_angle_rad = math.radians(fan * 46.0)
        lid_sy        = math.cos(lid_angle_rad)
        lid_top       = lid_bot - lid_h * lid_sy

        lid_path = QPainterPath()
        lid_path.moveTo(fx + fw,  lid_top)
        lid_path.lineTo(fx + fw,  lid_bot - r)
        lid_path.quadTo(fx + fw,  lid_bot,  fx + fw - r, lid_bot)
        lid_path.lineTo(fx + r,   lid_bot)
        lid_path.quadTo(fx,       lid_bot,  fx, lid_bot - r)
        lid_path.lineTo(fx,       lid_top + r * lid_sy)
        lid_path.quadTo(fx,       lid_top,  fx + r, lid_top)
        lid_path.lineTo(fx + fw,  lid_top)
        lid_path.closeSubpath()

        lid_grad = QLinearGradient(fx, lid_top, fx, lid_bot)
        lid_grad.setColorAt(0.0, amber_500)
        lid_grad.setColorAt(1.0, amber_400)
        p.fillPath(lid_path, lid_grad)

        if fan > 0.05:
            ga = int(fan * 100)
            top_glow = QLinearGradient(fx, lid_top, fx, lid_top + lid_h * lid_sy * 0.4)
            top_glow.setColorAt(0.0, QColor(251, 191, 36, ga))
            top_glow.setColorAt(1.0, QColor(251, 191, 36, 0))
            gp = QPainterPath()
            gp.addRoundedRect(fx + 2, lid_top, fw - 4, lid_h * lid_sy * 0.4, 8, 8)
            p.fillPath(gp, top_glow)

            bot_glow = QLinearGradient(fx, lid_bot - lid_h * lid_sy * 0.4, fx, lid_bot)
            bot_glow.setColorAt(0.0, QColor(217, 119, 6, 0))
            bot_glow.setColorAt(1.0, QColor(217, 119, 6, ga))
            gp2 = QPainterPath()
            gp2.addRoundedRect(fx + 2,
                               lid_bot - lid_h * lid_sy * 0.4,
                               fw - 4, lid_h * lid_sy * 0.4, 8, 8)
            p.fillPath(gp2, bot_glow)

        rtw    = int(fw * 0.61)
        rth    = int(fh * 0.115)
        rtx    = fx + fw - rtw
        rt_bot = lid_top
        rt_top = rt_bot - rth * lid_sy

        rtab = QPainterPath()
        rtab.moveTo(rtx,        rt_bot)
        rtab.lineTo(rtx + rtw,  rt_bot)
        rtab.lineTo(rtx + rtw,  rt_top + r * lid_sy)
        rtab.quadTo(rtx + rtw,  rt_top,  rtx + rtw - r, rt_top)
        rtab.lineTo(rtx + r,    rt_top)
        rtab.quadTo(rtx,        rt_top,  rtx, rt_top + r * lid_sy)
        rtab.lineTo(rtx,        rt_bot)
        rtab.closeSubpath()
        p.fillPath(rtab, amber_400)

        rnotch = QPainterPath()
        rnotch.moveTo(rtx,                    rt_top + rth * lid_sy * 0.14)
        rnotch.lineTo(rtx - rth * lid_sy * 0.5, rt_bot)
        rnotch.lineTo(rtx,                    rt_bot)
        rnotch.closeSubpath()
        p.fillPath(rnotch, amber_400)

        p.setPen(QColor(120, 70, 5, 200))
        p.setFont(QFont("Helvetica Neue", 7, QFont.Weight.Bold))
        p.drawText(QRect(fx, fy + fh - 18, fw, 16),
                   Qt.AlignmentFlag.AlignCenter, "WORKSPACE")

    # ── Card painting ─────────────────────────────────────────────────────────
    def _paint_cards(self, p: QPainter):
        total = len(self._sessions) + 1
        while len(self._card_drops) < total:
            self._card_drops.append(0.0)
        while len(self._card_scales) < total:
            self._card_scales.append(1.0)

        for i in range(total):
            drop_frac = self._card_drops[i] if i < len(self._card_drops) else 0.0
            if drop_frac < 0.01:
                continue
            scale    = self._card_scales[i] if i < len(self._card_scales) else 1.0
            is_new   = (i == len(self._sessions))
            sess     = self._sessions[i] if not is_new else None
            is_active      = not is_new and sess and sess["id"] == self._active_session_id
            is_confirmed   = (i == self._confirmed_card_i and self._drop_confirmed)

            base_y    = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            slide_off = int((1.0 - drop_frac) * (CARD_H + 50))
            cy        = base_y - slide_off

            cx_centre = CARD_X + CARD_W / 2
            cy_centre = cy + CARD_H / 2
            p.save()
            p.translate(cx_centre, cy_centre)
            p.scale(scale, scale)
            p.translate(-cx_centre, -cy_centre)

            if is_new:
                self._paint_new_session_card(p, CARD_X, cy, CARD_W, CARD_H, scale)
            else:
                self._paint_session_card(
                    p, CARD_X, cy, CARD_W, CARD_H,
                    sess, is_active, is_confirmed, scale,
                )
            p.restore()

    # ── Regular session card ──────────────────────────────────────────────────
    def _paint_session_card(
        self, p, cx, cy, cw, ch,
        sess, is_active, is_confirmed, scale,
    ):
        cr   = QRectF(cx, cy, cw, ch)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(cr, 14, 14)

        if is_confirmed:
            p.fillPath(bg_path, CONFIRM_GREEN.darker(110))
        elif scale > 1.01:
            p.fillPath(bg_path, CARD_HOVER_BG)
        else:
            p.fillPath(bg_path, CARD_BG)

        # Icon
        icon_x, icon_y, icon_w, icon_h = cx + 10, cy + 10, 50, 50
        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)

        if is_confirmed:
            ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
            ig.setColorAt(0, QColor("#42d778")); ig.setColorAt(1, QColor("#1a8a40"))
        elif scale > 1.01:
            ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
            ig.setColorAt(0, GRAD_HOVER_TOP); ig.setColorAt(1, GRAD_HOVER_BOT)
        else:
            ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
            ig.setColorAt(0, GRAD_TOP); ig.setColorAt(1, GRAD_BOT)
        p.fillPath(icon_path, ig)

        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Helvetica Neue", 16))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter,
                   "✓" if is_confirmed else "◈")

        tx = cx + 70; tw = cw - 80
        if is_confirmed:
            p.setPen(TEXT_WHITE)
            p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
            p.drawText(QRect(tx, cy + 10, tw, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       "Saved!")
            p.setPen(TEXT_DIM)
            p.setFont(QFont("Helvetica Neue", 9))
            lbl = QFontMetrics(p.font()).elidedText(
                self._confirmed_label, Qt.TextElideMode.ElideRight, tw)
            p.drawText(QRect(tx, cy + 36, tw, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, lbl)
        else:
            name    = sess.get("name", "Session") if sess else "Session"
            items   = db.get_items(sess["id"]) if sess else []
            n_items = len(items)
            time_str = "active" if is_active else f"{n_items} items"

            p.setPen(TEXT_WHITE)
            p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
            fm = QFontMetrics(p.font())
            p.drawText(QRect(tx, cy + 10, tw - 60, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       fm.elidedText(name, Qt.TextElideMode.ElideRight, tw - 60))

            p.setPen(TEXT_DIM)
            p.setFont(QFont("Helvetica Neue", 8))
            p.drawText(QRect(tx, cy + 10, tw - 4, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       time_str)
            p.setFont(QFont("Helvetica Neue", 9))
            p.drawText(QRect(tx, cy + 36, tw, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"{n_items} item{'s' if n_items != 1 else ''} saved")

    # ── NEW SESSION CARD — glowing conic border ───────────────────────────────
    def _paint_new_session_card(
        self, p: QPainter,
        cx: int, cy: int, cw: int, ch: int,
        scale: float,
    ):
        """
        Replicates the CSS layered glow effect:
          .glow    — blurred outer radial glow (blue+pink, opacity 0.4)
          .darkBorderBg — dark conic halo
          .border  — conic gradient rotating border
          .white   — soft bright inner ring
          card bg  — dark #010201 fill
          icon     — ＋ with animated hue-cycling colour
        All layers share the same border-radius and conic angle (self._glow_angle).
        """
        angle = self._glow_angle
        is_hovered = scale > 1.01

        card_rect = QRectF(cx, cy, cw, ch)
        r = 14.0  # border radius

        # ── Layer 1: outer glow (matches .glow — blurred, opacity 0.4) ────────
        # We simulate blur with a large radial gradient at low opacity
        cx_mid = cx + cw / 2
        cy_mid = cy + ch / 2
        for color, radius, alpha in [
            (GLOW_BLUE,  cw * 0.9, 35),
            (GLOW_PINK,  cw * 0.7, 30),
        ]:
            rg = QRadialGradient(cx_mid, cy_mid, radius)
            rg.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), alpha))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            glow_path = QPainterPath()
            glow_path.addRoundedRect(
                QRectF(cx - 20, cy - 14, cw + 40, ch + 28), r + 8, r + 8)
            p.fillPath(glow_path, rg)

        # ── Layer 2: darkBorderBg — dark conic halo ───────────────────────────
        dark_path = QPainterPath()
        dark_path.addRoundedRect(QRectF(cx - 1, cy - 1, cw + 2, ch + 2), r + 1, r + 1)
        cg_dark = QConicalGradient(cx_mid, cy_mid, angle + 2)
        cg_dark.setColorAt(0.00, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.05, QColor("#18116a"))
        cg_dark.setColorAt(0.10, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.60, QColor("#6e1b60"))
        cg_dark.setColorAt(0.65, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.fillPath(dark_path, cg_dark)

        # ── Layer 3: .border — conic gradient border ──────────────────────────
        border_outer = QPainterPath()
        border_outer.addRoundedRect(QRectF(cx - 2, cy - 2, cw + 4, ch + 4), r + 2, r + 2)
        border_inner = QPainterPath()
        border_inner.addRoundedRect(card_rect, r, r)
        border_ring = QPainterPath()
        border_ring = border_outer.subtracted(border_inner)

        cg_border = QConicalGradient(cx_mid, cy_mid, angle)
        cg_border.setColorAt(0.00, QColor("#1c191c"))
        cg_border.setColorAt(0.05, GLOW_BLUE)
        cg_border.setColorAt(0.14, QColor("#1c191c"))
        cg_border.setColorAt(0.50, QColor("#1c191c"))
        cg_border.setColorAt(0.60, GLOW_PINK)
        cg_border.setColorAt(0.64, QColor("#1c191c"))
        cg_border.setColorAt(1.00, QColor("#1c191c"))
        p.fillPath(border_ring, cg_border)

        # ── Layer 4: .white — soft bright inner ring ──────────────────────────
        white_outer = QPainterPath()
        white_outer.addRoundedRect(card_rect, r, r)
        white_inner = QPainterPath()
        white_inner.addRoundedRect(
            QRectF(cx + 2, cy + 2, cw - 4, ch - 4), r - 2, r - 2)
        white_ring = white_outer.subtracted(white_inner)

        cg_white = QConicalGradient(cx_mid, cy_mid, angle + 3)
        cg_white.setColorAt(0.00, QColor(0, 0, 0, 0))
        cg_white.setColorAt(0.04, GLOW_PURPLE)
        cg_white.setColorAt(0.08, QColor(0, 0, 0, 0))
        cg_white.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_white.setColorAt(0.55, GLOW_PINK2)
        cg_white.setColorAt(0.60, QColor(0, 0, 0, 0))
        cg_white.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.fillPath(white_ring, cg_white)

        # ── Card body ─────────────────────────────────────────────────────────
        bg = NEW_CARD_HOV if is_hovered else NEW_CARD_BG
        p.fillPath(border_inner, bg)

        # Subtle grid pattern (matches CSS .grid)
        self._paint_card_grid(p, cx + 2, cy + 2, cw - 4, ch - 4)

        # ── Icon block (left, matching other cards) ───────────────────────────
        icon_x, icon_y, icon_w, icon_h = cx + 10, cy + 11, 50, 50
        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)

        # Dark icon bg with subtle purple tint
        icon_bg = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        icon_bg.setColorAt(0.0, QColor("#161329"))
        icon_bg.setColorAt(1.0, QColor("#1d1b4b"))
        p.fillPath(icon_path, icon_bg)

        # Thin spinning border on icon (matches CSS #filter-icon border gradient)
        icon_border_outer = QPainterPath()
        icon_border_outer.addRoundedRect(icon_x - 1, icon_y - 1, icon_w + 2, icon_h + 2, 11, 11)
        icon_border_inner = QPainterPath()
        icon_border_inner.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)
        icon_border_ring = icon_border_outer.subtracted(icon_border_inner)
        cg_icon = QConicalGradient(icon_x + icon_w / 2, icon_y + icon_h / 2, angle * 1.5)
        cg_icon.setColorAt(0.00, QColor("#3d3a4f"))
        cg_icon.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_icon.setColorAt(0.51, QColor("#3d3a4f"))
        cg_icon.setColorAt(1.00, QColor("#3d3a4f"))
        p.fillPath(icon_border_ring, cg_icon)

        # ＋ icon — hue cycles (blue→purple→pink→blue)
        plus_color = QColor.fromHsvF(
            (self._plus_hue % 360) / 360.0,
            0.75,
            1.0,
        )
        p.setPen(plus_color)
        p.setFont(QFont("Helvetica Neue", 22, QFont.Weight.Bold))
        p.drawText(
            QRect(icon_x, icon_y, icon_w, icon_h),
            Qt.AlignmentFlag.AlignCenter,
            "＋",
        )

        # ── Text (right side) ─────────────────────────────────────────────────
        tx = cx + 70; tw = cw - 80

        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
        p.drawText(
            QRect(tx, cy + 10, tw - 10, 22),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "New Session",
        )
        p.setPen(TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(
            QRect(tx, cy + 36, tw, 20),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "Create a new workspace",
        )

    def _paint_card_grid(self, p: QPainter, x: int, y: int, w: int, h: int):
        """Subtle dot-grid inside the new session card (CSS .grid reference)."""
        grid_size = 16
        p.setPen(QPen(QColor(15, 15, 16, 180), 0.5))
        # Vertical lines
        xi = x + (x % grid_size)
        while xi < x + w:
            p.drawLine(int(xi), int(y), int(xi), int(y + h))
            xi += grid_size
        # Horizontal lines
        yi = y + (y % grid_size)
        while yi < y + h:
            p.drawLine(int(x), int(yi), int(x + w), int(yi))
            yi += grid_size

    # ── Confirm overlay ───────────────────────────────────────────────────────
    def _paint_confirm_overlay(self, p: QPainter):
        fr = self._folder_rect()
        cx = fr.x() + fr.width() // 2
        cy = fr.y() + fr.height() // 2
        dot = QPainterPath()
        dot.addEllipse(cx - 14, cy - 14, 28, 28)
        p.fillPath(dot, CONFIRM_GREEN)
        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Segoe UI", 14, QFont.Weight.Bold))
        p.drawText(QRect(cx - 14, cy - 14, 28, 28),
                   Qt.AlignmentFlag.AlignCenter, "✓")

    def _paint_picker_hint(self, p: QPainter):
        fr = self._folder_rect()
        p.setPen(QColor(136, 136, 153, 200))
        p.setFont(QFont("Helvetica Neue", 8))
        p.drawText(QRect(fr.x() - 10, fr.y() + FOLDER_H + 4, FOLDER_W + 20, 16),
                   Qt.AlignmentFlag.AlignCenter, "tap a session ↓")

    def _paint_cancel_hint(self, p: QPainter):
        if self._pending_app or self._picker_mode:
            p.setPen(QColor(136, 136, 153, 140))
            p.setFont(QFont("Helvetica Neue", 8))
            p.drawText(QRect(0, WIDGET_H - 28, WIDGET_W, 20),
                       Qt.AlignmentFlag.AlignCenter, "Esc to cancel")


# ── Per-card animation helper ─────────────────────────────────────────────────
class _CardDropAnim(QPropertyAnimation):
    def __init__(self, widget: DropZoneOverlay, index: int, store: list):
        super().__init__()
        self._widget = widget
        self._index  = index
        self._store  = store

    def updateCurrentValue(self, value):
        if self._index < len(self._store):
            self._store[self._index] = value
        self._widget.update()