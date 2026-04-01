"""
ui/drop_zone.py — Folder-style drop zone overlay.

v6 changes:
  • New Session card height reduced (NEW_CARD_H = 58).
  • Input field now expands INLINE inside the New Session card with a smooth
    height animation — the card grows, the label/subtitle fades out, and a
    borderless QLineEdit fades in.  No floating overlay card any more.
  • All session cards (regular + new) show the spinning conic-gradient glow
    border on hover, matching the New Session card's existing glow logic.
  • _glow_angle/target now tracked per-card via _card_glow_angles[i] and
    _card_glow_targets[i] dicts so each card glows independently.
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
NEW_CARD_H      = 56          # ← reduced height for New Session card
CARD_X          = 20
CARD_GAP        = 10
CARDS_START_Y   = FOLDER_H + 24

# Height the New Session card expands to when showing the inline input
NEW_CARD_EXPANDED_H = 96

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
NEW_CARD_BG     = QColor("#010201")
NEW_CARD_HOV    = QColor("#0d0d18")
TEXT_WHITE      = QColor(255, 255, 255)
TEXT_DIM        = QColor(136, 136, 153)
CONFIRM_GREEN   = QColor("#42d778")

# Glow palette
GLOW_BLUE       = QColor("#402fb5")
GLOW_PINK       = QColor("#cf30aa")
GLOW_PURPLE     = QColor("#a099d8")
GLOW_PINK2      = QColor("#dfa2da")

# Regular card glow palette (cooler, less saturated than new-session card)
RGLOW_A         = QColor("#2a3fa8")   # blue-ish
RGLOW_B         = QColor("#7a2090")   # purple-ish


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

        # ── Per-card glow state ───────────────────────────────────────────────
        # Keyed by card index: angle (current), target, hovered flag
        self._card_glow_angles:  dict[int, float] = {}
        self._card_glow_targets: dict[int, float] = {}
        self._card_glow_hovered: dict[int, bool]  = {}
        self._plus_hue = 240.0   # HSV hue for the + icon colour cycle

        # ── Inline input state ────────────────────────────────────────────────
        # _input_t: 0.0 = collapsed (normal new-session card)
        #           1.0 = fully expanded (showing inline QLineEdit)
        self._input_t      = 0.0
        self._input_open   = False

        # Master animation timer — 60 fps
        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_glow)
        self._anim_timer.start()

        self._setup_window()
        self._position_on_screen()
        self._refresh_sessions()
        self._build_slide_anim()
        self._build_input_anim()

        # Inline input embedded inside the widget (positioned over new-card area)
        self._new_sess_input = QLineEdit(self)
        self._new_sess_input.setPlaceholderText("Session name…")
        self._new_sess_input.setFixedHeight(28)
        self._new_sess_input.hide()
        self._new_sess_input.returnPressed.connect(self._create_new_session)
        self._new_sess_input.setStyleSheet("""
            QLineEdit {
                background: transparent; color: #ffffff;
                border: none; border-radius: 0px;
                padding: 0 4px; font-size: 12px;
                font-family: 'Helvetica Neue', 'Helvetica', sans-serif;
            }
            QLineEdit:focus { background: transparent; }
        """)

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self._finish_confirm)

        _ref = QTimer(self)
        _ref.timeout.connect(self._refresh_sessions)
        _ref.start(5000)

    # ── Per-card glow helpers ─────────────────────────────────────────────────
    def _glow_angle(self, i: int) -> float:
        return self._card_glow_angles.get(i, 83.0)

    def _set_card_glow_hover(self, i: int, hovered: bool):
        was = self._card_glow_hovered.get(i, False)
        if hovered == was:
            return
        self._card_glow_hovered[i] = hovered
        cur = self._card_glow_angles.get(i, 83.0)
        if hovered:
            self._card_glow_targets[i] = cur + 180.0
        else:
            self._card_glow_targets[i] = round(cur / 360) * 360 + 83.0

    # ── Glow tick ─────────────────────────────────────────────────────────────
    def _tick_glow(self):
        changed = False
        total = len(self._sessions) + 1

        for i in range(total):
            cur    = self._card_glow_angles.get(i, 83.0)
            target = self._card_glow_targets.get(i, 83.0)
            diff   = target - cur
            if abs(diff) > 0.3:
                self._card_glow_angles[i] = cur + diff * 0.06
                changed = True
            else:
                self._card_glow_angles[i] = target

        # + icon hue cycles continuously
        if self._cards_visible or self._picker_mode:
            self._plus_hue = (self._plus_hue + 0.6) % 360
            changed = True

        if changed:
            self.update()

    # ── Input animation ───────────────────────────────────────────────────────
    def _build_input_anim(self):
        self._input_anim = QPropertyAnimation(self, b"inputT", self)
        self._input_anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._input_anim.setDuration(260)

    def getInputT(self) -> float:
        return self._input_t

    def setInputT(self, v: float):
        self._input_t = v
        self._reposition_inline_input()
        self.update()

    inputT = pyqtProperty(float, getInputT, setInputT)

    def _reposition_inline_input(self):
        """Keep the QLineEdit centred inside the expanded new-session card."""
        if not self._input_open and self._input_t < 0.05:
            self._new_sess_input.hide()
            return

        n_cards  = len(self._sessions)
        card_y   = self._new_card_y(n_cards)
        cur_h    = self._new_card_current_h()

        # Position input in the lower portion of the card
        input_y = card_y + int(cur_h * 0.52)
        self._new_sess_input.setGeometry(
            CARD_X + 14,
            input_y,
            CARD_W - 28,
            28,
        )
        alpha = int(min(self._input_t * 2.0, 1.0) * 255)
        if alpha > 10:
            self._new_sess_input.show()
        else:
            self._new_sess_input.hide()

    def _new_card_y(self, card_index: int) -> int:
        """Y position of new-session card accounting for drop animation."""
        drop_frac = (
            self._card_drops[card_index]
            if card_index < len(self._card_drops) else 0.0
        )
        base_y    = CARDS_START_Y + card_index * (CARD_H + CARD_GAP)
        slide_off = int((1.0 - drop_frac) * (NEW_CARD_H + 50))
        return base_y - slide_off

    def _new_card_current_h(self) -> int:
        """Interpolated height of new-session card."""
        return int(NEW_CARD_H + (NEW_CARD_EXPANDED_H - NEW_CARD_H) * self._input_t)

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
        self._close_inline_input()
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
                self._open_inline_input(app_info)
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
        self._close_inline_input()
        if not self._drop_confirmed:
            self._slide_out()

    def set_active_session(self, session_id: int):
        self._active_session_id = session_id
        self._refresh_sessions()
        self.update()

    # ── Inline input open/close ───────────────────────────────────────────────
    def _open_inline_input(self, app_info: dict):
        self._pending_app  = app_info
        self._input_open   = True
        self._new_sess_input.clear()
        # Animate expansion
        self._input_anim.stop()
        self._input_anim.setStartValue(self._input_t)
        self._input_anim.setEndValue(1.0)
        self._input_anim.start()
        # Show input after brief delay (let expansion start)
        QTimer.singleShot(80, self._focus_input)
        self.update()

    def _focus_input(self):
        self._new_sess_input.show()
        self._new_sess_input.setFocus()
        self._reposition_inline_input()

    def _close_inline_input(self):
        self._input_open = False
        self._new_sess_input.clearFocus()
        self._input_anim.stop()
        self._input_anim.setStartValue(self._input_t)
        self._input_anim.setEndValue(0.0)
        self._input_anim.start()

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

    def _create_new_session(self):
        name = self._new_sess_input.text().strip() or "My Workspace"
        self._close_inline_input()
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
        self._close_inline_input()
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
            is_new   = (i == len(self._sessions))
            card_h   = self._new_card_current_h() if is_new else CARD_H
            base_y   = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            actual_y = base_y - int((1.0 - drop_frac) * (card_h + 40))
            r = QRect(CARD_X, actual_y, CARD_W, card_h)
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

        # Update card hover states and per-card glow
        changed = False
        total = len(self._sessions) + 1
        while len(self._card_scales) < total:
            self._card_scales.append(1.0)

        for i in range(total):
            is_new    = (i == len(self._sessions))
            card_h    = self._new_card_current_h() if is_new else CARD_H
            base_y    = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            drop_frac = self._card_drops[i] if i < len(self._card_drops) else 0.0
            actual_y  = base_y - int((1.0 - drop_frac) * (card_h + 40))
            r         = QRect(CARD_X, actual_y, CARD_W, card_h)
            hover     = r.contains(x, y) and drop_frac > 0.5
            want      = 1.05 if hover else 1.0
            if abs(self._card_scales[i] - want) > 0.001:
                self._card_scales[i] = want
                changed = True
            # Drive per-card glow
            self._set_card_glow_hover(i, hover)

        if changed:
            self.update()

    def mousePressEvent(self, event):
        x, y = int(event.position().x()), int(event.position().y())
        card_i = self._card_at(x, y)
        if card_i is not None:
            if card_i == len(self._sessions):
                self._open_inline_input(self._pending_app)
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
        total = len(self._sessions) + 1
        for i in range(total):
            self._set_card_glow_hover(i, False)
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

            card_h    = self._new_card_current_h() if is_new else CARD_H
            base_y    = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            slide_off = int((1.0 - drop_frac) * (card_h + 50))
            cy        = base_y - slide_off

            cx_centre = CARD_X + CARD_W / 2
            cy_centre = cy + card_h / 2
            p.save()
            p.translate(cx_centre, cy_centre)
            p.scale(scale, scale)
            p.translate(-cx_centre, -cy_centre)

            if is_new:
                self._paint_new_session_card(p, CARD_X, cy, CARD_W, card_h, scale, i)
            else:
                self._paint_session_card(
                    p, CARD_X, cy, CARD_W, CARD_H,
                    sess, is_active, is_confirmed, scale, i,
                )
            p.restore()

    # ── Shared glow border painter ────────────────────────────────────────────
    def _paint_glow_border(
        self,
        p: QPainter,
        cx: float, cy: float, cw: int, ch: int,
        angle: float,
        glow_a: QColor, glow_b: QColor,
        dark_a: str, dark_b: str,
        hover_strength: float,   # 0..1 how much glow to show
        r: float = 14.0,
    ):
        """Paint the layered conic glow border.  Works for any card size."""
        cx_mid = cx + cw / 2
        cy_mid = cy + ch / 2
        alpha_mul = hover_strength   # fade in with hover

        # Outer radial glow
        for color, radius, base_alpha in [
            (glow_a, cw * 0.9, 30),
            (glow_b, cw * 0.7, 25),
        ]:
            a = int(base_alpha * alpha_mul)
            if a < 2:
                continue
            rg = QRadialGradient(cx_mid, cy_mid, radius)
            rg.setColorAt(0.0, QColor(color.red(), color.green(), color.blue(), a))
            rg.setColorAt(1.0, QColor(0, 0, 0, 0))
            glow_path = QPainterPath()
            glow_path.addRoundedRect(
                QRectF(cx - 20, cy - 14, cw + 40, ch + 28), r + 8, r + 8)
            p.fillPath(glow_path, rg)

        # darkBorderBg
        dark_path = QPainterPath()
        dark_path.addRoundedRect(QRectF(cx - 1, cy - 1, cw + 2, ch + 2), r + 1, r + 1)
        cg_dark = QConicalGradient(cx_mid, cy_mid, angle + 2)
        cg_dark.setColorAt(0.00, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.05, QColor(dark_a))
        cg_dark.setColorAt(0.10, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(0.60, QColor(dark_b))
        cg_dark.setColorAt(0.65, QColor(0, 0, 0, 0))
        cg_dark.setColorAt(1.00, QColor(0, 0, 0, 0))
        p.setOpacity(alpha_mul)
        p.fillPath(dark_path, cg_dark)
        p.setOpacity(1.0)

        # Conic border ring
        border_outer = QPainterPath()
        border_outer.addRoundedRect(QRectF(cx - 2, cy - 2, cw + 4, ch + 4), r + 2, r + 2)
        border_inner = QPainterPath()
        border_inner.addRoundedRect(QRectF(cx, cy, cw, ch), r, r)
        border_ring  = border_outer.subtracted(border_inner)

        cg_border = QConicalGradient(cx_mid, cy_mid, angle)
        cg_border.setColorAt(0.00, QColor("#1c191c"))
        cg_border.setColorAt(0.05, glow_a)
        cg_border.setColorAt(0.14, QColor("#1c191c"))
        cg_border.setColorAt(0.50, QColor("#1c191c"))
        cg_border.setColorAt(0.60, glow_b)
        cg_border.setColorAt(0.64, QColor("#1c191c"))
        cg_border.setColorAt(1.00, QColor("#1c191c"))
        p.setOpacity(alpha_mul)
        p.fillPath(border_ring, cg_border)
        p.setOpacity(1.0)

        # Soft inner white ring
        white_outer = QPainterPath()
        white_outer.addRoundedRect(QRectF(cx, cy, cw, ch), r, r)
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
        p.setOpacity(alpha_mul * 0.7)
        p.fillPath(white_ring, cg_white)
        p.setOpacity(1.0)

    # ── Regular session card ──────────────────────────────────────────────────
    def _paint_session_card(
        self, p, cx, cy, cw, ch,
        sess, is_active, is_confirmed, scale, card_index,
    ):
        r    = 14.0
        cr   = QRectF(cx, cy, cw, ch)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(cr, r, r)

        hover_strength = max(0.0, (scale - 1.0) / 0.05)  # 0..1
        angle = self._glow_angle(card_index)

        # Paint glow border (fades in with hover)
        if hover_strength > 0.01:
            self._paint_glow_border(
                p, cx, cy, cw, ch, angle,
                RGLOW_A, RGLOW_B,
                "#0e0c3a", "#3d1050",
                hover_strength, r,
            )

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

    # ── NEW SESSION CARD ──────────────────────────────────────────────────────
    def _paint_new_session_card(
        self, p: QPainter,
        cx: int, cy: int, cw: int, ch: int,
        scale: float, card_index: int,
    ):
        angle          = self._glow_angle(card_index)
        is_hovered     = scale > 1.01
        hover_strength = max(0.0, (scale - 1.0) / 0.05)
        t_input        = self._input_t   # 0 = normal, 1 = input open
        r              = 14.0

        # Glow border (always present for new-session card; fades further with input)
        glow_mul = max(0.08, hover_strength) * (1.0 - t_input * 0.5)
        self._paint_glow_border(
            p, cx, cy, cw, ch, angle,
            GLOW_BLUE, GLOW_PINK,
            "#18116a", "#6e1b60",
            glow_mul, r,
        )

        # Card body
        card_path = QPainterPath()
        card_path.addRoundedRect(QRectF(cx, cy, cw, ch), r, r)
        bg = NEW_CARD_HOV if (is_hovered or self._input_open) else NEW_CARD_BG
        p.fillPath(card_path, bg)

        # Grid pattern
        self._paint_card_grid(p, cx + 2, cy + 2, cw - 4, ch - 4)

        # ── Content fades out as input opens ─────────────────────────────────
        content_alpha = max(0.0, 1.0 - t_input * 2.5)
        if content_alpha > 0.01:
            p.setOpacity(content_alpha)
            self._paint_new_card_content(p, cx, cy, cw, ch, angle)
            p.setOpacity(1.0)

        # ── Inline input area fades in ────────────────────────────────────────
        if t_input > 0.1:
            input_alpha = min(1.0, (t_input - 0.1) / 0.4)
            p.setOpacity(input_alpha)
            self._paint_inline_input_bg(p, cx, cy, cw, ch)
            p.setOpacity(1.0)

    def _paint_new_card_content(
        self, p: QPainter,
        cx: int, cy: int, cw: int, ch: int,
        angle: float,
    ):
        """Draws the icon + text label inside the new-session card."""
        icon_x, icon_y, icon_w = cx + 10, cy + (ch - 40) // 2, 40
        icon_h = 40

        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 9, 9)

        icon_bg = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        icon_bg.setColorAt(0.0, QColor("#161329"))
        icon_bg.setColorAt(1.0, QColor("#1d1b4b"))
        p.fillPath(icon_path, icon_bg)

        # Spinning icon border
        icon_border_outer = QPainterPath()
        icon_border_outer.addRoundedRect(icon_x - 1, icon_y - 1, icon_w + 2, icon_h + 2, 10, 10)
        icon_border_inner = QPainterPath()
        icon_border_inner.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 9, 9)
        icon_border_ring  = icon_border_outer.subtracted(icon_border_inner)
        cg_icon = QConicalGradient(icon_x + icon_w / 2, icon_y + icon_h / 2, angle * 1.5)
        cg_icon.setColorAt(0.00, QColor("#3d3a4f"))
        cg_icon.setColorAt(0.50, QColor(0, 0, 0, 0))
        cg_icon.setColorAt(0.51, QColor("#3d3a4f"))
        cg_icon.setColorAt(1.00, QColor("#3d3a4f"))
        p.fillPath(icon_border_ring, cg_icon)

        plus_color = QColor.fromHsvF((self._plus_hue % 360) / 360.0, 0.75, 1.0)
        p.setPen(plus_color)
        p.setFont(QFont("Helvetica Neue", 18, QFont.Weight.Bold))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter, "＋")

        tx = cx + icon_x - cx + icon_w + 10
        tw = cw - (tx - cx) - 10

        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
        p.drawText(QRect(tx, cy + 8, tw, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "New Session")
        p.setPen(TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(QRect(tx, cy + 30, tw, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Create a new workspace")

    def _paint_inline_input_bg(
        self, p: QPainter,
        cx: int, cy: int, cw: int, ch: int,
    ):
        """Draws the prompt label + input underline inside the expanded card."""
        # Prompt label at top
        p.setPen(TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(
            QRect(cx + 14, cy + 10, cw - 28, 16),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "New workspace name",
        )

        # Underline where QLineEdit sits
        input_y = cy + int(ch * 0.52)
        line_y  = input_y + 28
        p.setPen(QPen(QColor(80, 60, 140, 180), 1.0))
        p.drawLine(cx + 14, line_y, cx + cw - 14, line_y)

        # Subtle glow under the line
        line_glow = QLinearGradient(cx + 14, line_y, cx + cw - 14, line_y)
        line_glow.setColorAt(0.0,  QColor(64, 47, 181, 0))
        line_glow.setColorAt(0.35, QColor(64, 47, 181, 80))
        line_glow.setColorAt(0.65, QColor(207, 48, 170, 80))
        line_glow.setColorAt(1.0,  QColor(207, 48, 170, 0))
        pen = QPen(QBrush(line_glow), 2.0)
        p.setPen(pen)
        p.drawLine(cx + 14, line_y + 1, cx + cw - 14, line_y + 1)

    def _paint_card_grid(self, p: QPainter, x: int, y: int, w: int, h: int):
        grid_size = 16
        p.setPen(QPen(QColor(15, 15, 16, 180), 0.5))
        xi = x + (x % grid_size)
        while xi < x + w:
            p.drawLine(int(xi), int(y), int(xi), int(y + h))
            xi += grid_size
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