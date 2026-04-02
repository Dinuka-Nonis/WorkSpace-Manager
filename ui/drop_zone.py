"""
ui/drop_zone.py — Folder-style drop zone overlay.

v8 changes:
  • "New Session" card is now pinned/fixed at the top and never scrolls
  • Sessions below are shown in a clipped viewport showing exactly 4 at a time
  • Smooth animated scrolling (_scroll_anim) replaces instant jump
  • Wheel delta accumulates into a smooth target offset
  • Cards outside the clip region are hidden cleanly
"""

from __future__ import annotations

import math
import sys
from PyQt6.QtWidgets import QWidget, QApplication, QLineEdit
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QRectF, pyqtProperty, QPoint,
    QSequentialAnimationGroup, QPauseAnimation
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QLinearGradient, QConicalGradient,
    QFont, QFontMetrics, QPen, QRadialGradient,
    QBrush
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
NEW_CARD_H      = 56
CARD_X          = 20
CARD_GAP        = 10
CARDS_START_Y   = FOLDER_H + 24

# New Session card is pinned; sessions viewport sits below it
NEW_CARD_PINNED_Y   = CARDS_START_Y                          # fixed Y for new-session card
SESSIONS_START_Y    = NEW_CARD_PINNED_Y + NEW_CARD_H + CARD_GAP  # top of scrollable session area
VISIBLE_SESSIONS    = 4                                      # max sessions visible at once
SESSIONS_VIEWPORT_H = VISIBLE_SESSIONS * (CARD_H + CARD_GAP) - CARD_GAP  # clip height

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

RGLOW_A         = QColor("#2a3fa8")
RGLOW_B         = QColor("#7a2090")


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

        # Confirmation animation: 0.0 = hidden, 1.0 = fully visible
        self._confirm_alpha = 0.0

        self._card_glow_angles:  dict[int, float] = {}
        self._card_glow_targets: dict[int, float] = {}
        self._card_glow_hovered: dict[int, bool]  = {}
        self._plus_hue = 240.0

        self._input_t      = 0.0
        self._input_open   = False

        # Smooth scrolling — tracks only the sessions list (not the pinned card)
        self._scroll_offset      = 0.0   # current rendered offset (animated)
        self._scroll_target      = 0.0   # target offset from wheel events

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_glow)
        self._anim_timer.start()
        self._is_fully_hidden = True

        self._setup_window()
        self._position_on_screen()
        self._refresh_sessions()
        self._build_slide_anim()
        self._build_input_anim()
        self._build_confirm_anim()
        self._build_scroll_anim()

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
                font-family: 'Inter', '-apple-system', 'BlinkMacSystemFont', sans-serif;
            }
            QLineEdit:focus { background: transparent; }
        """)

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self._finish_confirm)

        _ref = QTimer(self)
        _ref.timeout.connect(self._refresh_sessions)
        _ref.start(5000)

    # ── Glow helpers ──────────────────────────────────────────────────────────

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

    def _tick_glow(self):
        if self._is_fully_hidden and not self._folder_hovered:
            return

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

        if self._cards_visible or self._picker_mode:
            self._plus_hue = (self._plus_hue + 0.6) % 360
            changed = True

        # Smooth scroll interpolation (lerp toward target)
        diff = self._scroll_target - self._scroll_offset
        if abs(diff) > 0.3:
            self._scroll_offset += diff * 0.15
            changed = True
        else:
            self._scroll_offset = self._scroll_target

        if changed:
            self.update()

    # ── Confirm animation ─────────────────────────────────────────────────────

    def _build_confirm_anim(self):
        self._confirm_anim = QPropertyAnimation(self, b"confirmAlpha", self)
        self._confirm_anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._confirm_anim.setDuration(400)

    def getConfirmAlpha(self) -> float:
        return self._confirm_alpha

    def setConfirmAlpha(self, v: float):
        self._confirm_alpha = v
        self.update()

    confirmAlpha = pyqtProperty(float, getConfirmAlpha, setConfirmAlpha)

    def _trigger_confirm_animation(self):
        self._confirm_anim.stop()

        seq = QSequentialAnimationGroup(self)

        fade_in = QPropertyAnimation(self, b"confirmAlpha", self)
        fade_in.setDuration(300)
        fade_in.setStartValue(0.0)
        fade_in.setEndValue(1.0)
        fade_in.setEasingCurve(QEasingCurve.Type.OutCubic)

        pause = QPauseAnimation(800, self)

        fade_out = QPropertyAnimation(self, b"confirmAlpha", self)
        fade_out.setDuration(400)
        fade_out.setStartValue(1.0)
        fade_out.setEndValue(0.0)
        fade_out.setEasingCurve(QEasingCurve.Type.InCubic)

        seq.addAnimation(fade_in)
        seq.addAnimation(pause)
        seq.addAnimation(fade_out)
        seq.finished.connect(self._on_confirm_anim_finished)
        seq.start()

        self._current_confirm_seq = seq

    def _on_confirm_anim_finished(self):
        self._drop_confirmed = False
        self._confirmed_card_i = -1
        self._confirm_alpha = 0.0
        self.update()

    # ── Scroll animation ──────────────────────────────────────────────────────

    def _build_scroll_anim(self):
        """Scroll is now lerp-based in _tick_glow; this is a no-op placeholder."""
        pass

    def _max_scroll(self) -> float:
        """Maximum scroll distance for the sessions list."""
        n = len(self._sessions)
        total_h = n * (CARD_H + CARD_GAP) - CARD_GAP
        excess  = total_h - SESSIONS_VIEWPORT_H
        return max(0.0, float(excess))

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
        if not self._input_open and self._input_t < 0.05:
            self._new_sess_input.hide()
            return

        # Input lives inside the pinned New Session card
        card_y   = NEW_CARD_PINNED_Y
        cur_h    = self._new_card_current_h()

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

    def _new_card_current_h(self) -> int:
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

    # ── Slide animation ───────────────────────────────────────────────────────

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
        self._is_fully_hidden = False
        if not self._anim_timer.isActive():
            self._anim_timer.start()
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
        self._slide_anim.finished.connect(self._on_fully_hidden)
        try:
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass

    def _on_fully_hidden(self):
        if self._slide_x >= 0.99:
            self._is_fully_hidden = True
            self._anim_timer.stop()
        try:
            self._slide_anim.finished.disconnect(self._on_fully_hidden)
        except Exception:
            pass

    # ── Fan animation ─────────────────────────────────────────────────────────

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
        n = len(self._sessions) + 1   # +1 for pinned new-session card
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
        self._scroll_offset       = 0.0
        self._scroll_target       = 0.0
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
            if card_i == 0:
                self._open_inline_input(app_info)
            else:
                self._pending_app       = app_info
                self._picker_mode       = True
                self._active_session_id = self._sessions[card_i - 1]["id"]
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

    # ── Inline input ──────────────────────────────────────────────────────────

    def _open_inline_input(self, app_info: dict):
        self._pending_app  = app_info
        self._input_open   = True
        self._new_sess_input.clear()
        self._input_anim.stop()
        self._input_anim.setStartValue(self._input_t)
        self._input_anim.setEndValue(1.0)
        self._input_anim.start()
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

    def _refresh_sessions(self):
        self._sessions = db.get_all_sessions()[:6]
        if not self._active_session_id and self._sessions:
            self._active_session_id = self._sessions[0]["id"]
        self.update()

    # ── Save / confirm ────────────────────────────────────────────────────────

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

        self._trigger_confirm_animation()
        self._confirm_timer.start(1500)

    def _create_new_session(self):
        name = self._new_sess_input.text().strip() or "My Workspace"
        self._close_inline_input()
        sid = db.create_session(name)
        self._active_session_id = sid
        self._refresh_sessions()
        if self._pending_app:
            idx = next((i for i, s in enumerate(self._sessions) if s["id"] == sid), 0)
            self._save_to_session(self._pending_app, confirmed_card=idx + 1)

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

    # ── Geometry helpers ──────────────────────────────────────────────────────

    def _folder_rect(self) -> QRect:
        return QRect(WIDGET_W - FOLDER_W - 4, 0, FOLDER_W, FOLDER_H)

    def _card_rect(self, index: int) -> QRect:
        """Logical rect (ignores scroll/drop animation). index 0 = new-session."""
        if index == 0:
            return QRect(CARD_X, NEW_CARD_PINNED_Y, CARD_W, NEW_CARD_H)
        sess_i = index - 1
        y = SESSIONS_START_Y + sess_i * (CARD_H + CARD_GAP)
        return QRect(CARD_X, y, CARD_W, CARD_H)

    def _session_card_y(self, sess_index: int) -> int:
        """Actual painted Y for session card (sess_index 0-based), accounting for scroll."""
        base_y    = SESSIONS_START_Y + sess_index * (CARD_H + CARD_GAP)
        drop_frac = self._card_drops[sess_index + 1] if (sess_index + 1) < len(self._card_drops) else 0.0
        slide_off = int((1.0 - drop_frac) * (CARD_H + 50))
        return base_y - slide_off - int(self._scroll_offset)

    def _card_at(self, x: int, y: int) -> int | None:
        """Returns card index (0 = new-session, 1..N = sessions). None if no hit."""
        # Check pinned New Session card first
        if len(self._card_drops) > 0 and self._card_drops[0] > 0.05:
            cur_h = self._new_card_current_h()
            nr = QRect(CARD_X, NEW_CARD_PINNED_Y, CARD_W, cur_h)
            if nr.contains(x, y):
                return 0

        # Check session cards (clipped to viewport)
        clip_top    = SESSIONS_START_Y
        clip_bottom = SESSIONS_START_Y + SESSIONS_VIEWPORT_H
        if not (clip_top <= y <= clip_bottom):
            return None

        for sess_i in range(len(self._sessions)):
            card_i    = sess_i + 1
            drop_frac = self._card_drops[card_i] if card_i < len(self._card_drops) else 0.0
            if drop_frac < 0.05:
                continue
            cy = self._session_card_y(sess_i)
            r  = QRect(CARD_X, cy, CARD_W, CARD_H)
            if r.contains(x, y):
                return card_i
        return None

    # ── Events ────────────────────────────────────────────────────────────────

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

        changed = False
        total = len(self._sessions) + 1
        while len(self._card_scales) < total:
            self._card_scales.append(1.0)

        clip_top    = SESSIONS_START_Y
        clip_bottom = SESSIONS_START_Y + SESSIONS_VIEWPORT_H

        for i in range(total):
            if i == 0:
                # Pinned new-session card
                drop_frac = self._card_drops[0] if self._card_drops else 0.0
                cur_h     = self._new_card_current_h()
                r         = QRect(CARD_X, NEW_CARD_PINNED_Y, CARD_W, cur_h)
                hover     = r.contains(x, y) and drop_frac > 0.5
            else:
                sess_i    = i - 1
                drop_frac = self._card_drops[i] if i < len(self._card_drops) else 0.0
                cy        = self._session_card_y(sess_i)
                r         = QRect(CARD_X, cy, CARD_W, CARD_H)
                in_clip   = (cy + CARD_H > clip_top) and (cy < clip_bottom)
                hover     = r.contains(x, y) and drop_frac > 0.5 and in_clip

            want = 1.05 if hover else 1.0
            if abs(self._card_scales[i] - want) > 0.001:
                self._card_scales[i] = want
                changed = True
            self._set_card_glow_hover(i, hover)

        if changed:
            self.update()

    def mousePressEvent(self, event):
        x, y = int(event.position().x()), int(event.position().y())
        card_i = self._card_at(x, y)
        if card_i is not None:
            if card_i == 0:
                self._open_inline_input(self._pending_app)
            else:
                session_idx = card_i - 1
                self._active_session_id = self._sessions[session_idx]["id"]
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

    def wheelEvent(self, event):
        """Smooth-scroll the sessions list (pinned New Session stays fixed)."""
        if not (self._cards_visible or self._picker_mode):
            return

        scroll_amount = 40
        delta = event.angleDelta().y()

        if delta > 0:
            self._scroll_target = max(0.0, self._scroll_target - scroll_amount)
        else:
            self._scroll_target = min(self._max_scroll(), self._scroll_target + scroll_amount)

        # Ensure tick loop is running so the lerp fires
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        self._paint_folder(p)

        if self._cards_visible or self._picker_mode or self._drop_confirmed:
            self._paint_cards(p)

        if self._picker_mode and not self._drop_confirmed:
            self._paint_picker_hint(p)

        p.end()

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
        p.setFont(QFont("Inter", 7, QFont.Weight.Bold))
        p.drawText(QRect(fx, fy + fh - 18, fw, 16),
                   Qt.AlignmentFlag.AlignCenter, "WORKSPACE")

    def _paint_cards(self, p: QPainter):
        total = len(self._sessions) + 1
        while len(self._card_drops) < total:
            self._card_drops.append(0.0)
        while len(self._card_scales) < total:
            self._card_scales.append(1.0)

        # ── 1. Paint the pinned "New Session" card (index 0) ──────────────────
        drop_frac_0 = self._card_drops[0]
        if drop_frac_0 > 0.01:
            scale_0  = self._card_scales[0]
            cur_h    = self._new_card_current_h()
            cx_c     = CARD_X + CARD_W / 2
            cy_c     = NEW_CARD_PINNED_Y + cur_h / 2
            p.save()
            p.translate(cx_c, cy_c)
            p.scale(scale_0, scale_0)
            p.translate(-cx_c, -cy_c)
            self._paint_new_session_card(p, CARD_X, NEW_CARD_PINNED_Y, CARD_W, cur_h, scale_0, 0)
            p.restore()

        # ── 2. Clip the sessions viewport ─────────────────────────────────────
        clip_rect = QRectF(0, SESSIONS_START_Y, WIDGET_W, SESSIONS_VIEWPORT_H)
        p.save()
        clip_path = QPainterPath()
        clip_path.addRect(clip_rect)
        p.setClipPath(clip_path)

        for sess_i, sess in enumerate(self._sessions):
            card_i    = sess_i + 1
            drop_frac = self._card_drops[card_i] if card_i < len(self._card_drops) else 0.0
            if drop_frac < 0.01:
                continue

            scale      = self._card_scales[card_i] if card_i < len(self._card_scales) else 1.0
            is_active  = sess["id"] == self._active_session_id
            is_confirmed = (card_i == self._confirmed_card_i and self._drop_confirmed)

            cy        = self._session_card_y(sess_i)

            # Skip cards fully outside clip
            if cy + CARD_H < SESSIONS_START_Y or cy > SESSIONS_START_Y + SESSIONS_VIEWPORT_H:
                continue

            cx_centre = CARD_X + CARD_W / 2
            cy_centre = cy + CARD_H / 2
            p.save()
            p.translate(cx_centre, cy_centre)
            p.scale(scale, scale)
            p.translate(-cx_centre, -cy_centre)
            self._paint_session_card(
                p, CARD_X, cy, CARD_W, CARD_H,
                sess, is_active, is_confirmed, scale, card_i,
            )
            p.restore()

        p.restore()  # remove clip

        # ── 3. Fade edges to hint scrollability ───────────────────────────────
        if len(self._sessions) > VISIBLE_SESSIONS:
            self._paint_scroll_fades(p)

    def _paint_scroll_fades(self, p: QPainter):
        """Subtle gradient fades at top/bottom of sessions viewport."""
        fade_h = 24
        bg = QColor(15, 14, 20)  # approximate widget bg

        # Top fade (visible when scrolled down)
        if self._scroll_offset > 2:
            grad = QLinearGradient(0, SESSIONS_START_Y, 0, SESSIONS_START_Y + fade_h)
            c = QColor(bg); c.setAlpha(200)
            grad.setColorAt(0.0, c)
            c2 = QColor(bg); c2.setAlpha(0)
            grad.setColorAt(1.0, c2)
            p.fillRect(QRectF(CARD_X, SESSIONS_START_Y, CARD_W, fade_h), grad)

        # Bottom fade (visible when more cards below)
        if self._scroll_offset < self._max_scroll() - 2:
            bot_y = SESSIONS_START_Y + SESSIONS_VIEWPORT_H
            grad = QLinearGradient(0, bot_y - fade_h, 0, bot_y)
            c2 = QColor(bg); c2.setAlpha(0)
            grad.setColorAt(0.0, c2)
            c = QColor(bg); c.setAlpha(220)
            grad.setColorAt(1.0, c)
            p.fillRect(QRectF(CARD_X, bot_y - fade_h, CARD_W, fade_h), grad)

    def _paint_glow_border(
        self,
        p: QPainter,
        cx: float, cy: float, cw: int, ch: int,
        angle: float,
        glow_a: QColor, glow_b: QColor,
        dark_a: str, dark_b: str,
        hover_strength: float,
        r: float = 14.0,
    ):
        cx_mid = cx + cw / 2
        cy_mid = cy + ch / 2
        alpha_mul = hover_strength

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

    def _paint_session_card(
        self, p, cx, cy, cw, ch,
        sess, is_active, is_confirmed, scale, card_index,
    ):
        r    = 14.0
        cr   = QRectF(cx, cy, cw, ch)
        bg_path = QPainterPath()
        bg_path.addRoundedRect(cr, r, r)

        hover_strength = max(0.0, (scale - 1.0) / 0.05)
        angle = self._glow_angle(card_index)

        if hover_strength > 0.01:
            self._paint_glow_border(
                p, cx, cy, cw, ch, angle,
                RGLOW_A, RGLOW_B,
                "#0e0c3a", "#3d1050",
                hover_strength, r,
            )

        if scale > 1.01:
            p.fillPath(bg_path, CARD_HOVER_BG)
        else:
            p.fillPath(bg_path, CARD_BG)

        icon_x, icon_y, icon_w, icon_h = cx + 10, cy + 10, 50, 50
        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)

        if is_confirmed and self._confirm_alpha > 0.01:
            ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
            ig.setColorAt(0, QColor("#42d778"))
            ig.setColorAt(1, QColor("#1a8a40"))
        elif scale > 1.01:
            ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
            ig.setColorAt(0, GRAD_HOVER_TOP)
            ig.setColorAt(1, GRAD_HOVER_BOT)
        else:
            ig = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
            ig.setColorAt(0, GRAD_TOP)
            ig.setColorAt(1, GRAD_BOT)
        p.fillPath(icon_path, ig)

        if is_confirmed and self._confirm_alpha > 0.01:
            p.setOpacity(self._confirm_alpha)
            p.setPen(TEXT_WHITE)
            p.setFont(QFont("Inter", 16))
            p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                       Qt.AlignmentFlag.AlignCenter, "✓")
            p.setOpacity(1.0)
        else:
            p.setPen(TEXT_WHITE)
            p.setFont(QFont("Inter", 16))
            p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                       Qt.AlignmentFlag.AlignCenter, "◈")

        tx = cx + 70
        tw = cw - 80

        name    = sess.get("name", "Session") if sess else "Session"
        items   = db.get_items(sess["id"]) if sess else []
        n_items = len(items)

        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        fm = QFontMetrics(p.font())
        name_width = tw - 60
        p.drawText(QRect(tx, cy + 10, name_width, 22),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   fm.elidedText(name, Qt.TextElideMode.ElideRight, name_width))

        if is_confirmed:
            slide_offset = int((1.0 - self._confirm_alpha) * 20)
            badge_x = cx + cw - 60 - slide_offset
            badge_rect = QRect(badge_x, cy + 10, 50, 20)

            p.setOpacity(self._confirm_alpha)
            p.setPen(CONFIRM_GREEN)
            p.setFont(QFont("Inter", 10, QFont.Weight.Bold))
            p.drawText(badge_rect,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       "Saved!")
            p.setOpacity(1.0)

            if self._confirm_alpha > 0.1:
                glow_rect = QRectF(badge_x - 5, cy + 8, 60, 24)
                glow_color = QColor(66, 215, 120, int(40 * self._confirm_alpha))
                p.fillRect(glow_rect, glow_color)
        else:
            time_str = "active" if is_active else f"{n_items} items"
            p.setPen(TEXT_DIM)
            p.setFont(QFont("Inter", 8))
            p.drawText(QRect(tx, cy + 10, tw - 4, 22),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                       time_str)

        p.setPen(TEXT_DIM)
        p.setFont(QFont("Inter", 9))
        if is_confirmed and self._confirm_alpha > 0.01 and self._confirmed_label:
            subtitle_text   = f"{n_items} item{'s' if n_items != 1 else ''} saved"
            confirmed_text  = self._confirmed_label

            p.setOpacity(1.0 - self._confirm_alpha * 0.8)
            p.drawText(QRect(tx, cy + 36, tw, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       subtitle_text)

            p.setOpacity(self._confirm_alpha)
            p.setPen(QColor(100, 200, 140))
            elided = QFontMetrics(p.font()).elidedText(
                confirmed_text, Qt.TextElideMode.ElideRight, tw)
            p.drawText(QRect(tx, cy + 36, tw, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       elided)
            p.setOpacity(1.0)
        else:
            p.drawText(QRect(tx, cy + 36, tw, 20),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       f"{n_items} item{'s' if n_items != 1 else ''} saved")

    def _paint_new_session_card(
        self, p: QPainter,
        cx: int, cy: int, cw: int, ch: int,
        scale: float, card_index: int,
    ):
        angle          = self._glow_angle(card_index)
        is_hovered     = scale > 1.01
        hover_strength = max(0.0, (scale - 1.0) / 0.05)
        t_input        = self._input_t
        r              = 14.0

        glow_mul = max(0.08, hover_strength) * (1.0 - t_input * 0.5)
        self._paint_glow_border(
            p, cx, cy, cw, ch, angle,
            GLOW_BLUE, GLOW_PINK,
            "#18116a", "#6e1b60",
            glow_mul, r,
        )

        card_path = QPainterPath()
        card_path.addRoundedRect(QRectF(cx, cy, cw, ch), r, r)
        bg = NEW_CARD_HOV if (is_hovered or self._input_open) else NEW_CARD_BG
        p.fillPath(card_path, bg)

        self._paint_card_grid(p, cx + 2, cy + 2, cw - 4, ch - 4)

        content_alpha = max(0.0, 1.0 - t_input * 2.5)
        if content_alpha > 0.01:
            p.setOpacity(content_alpha)
            self._paint_new_card_content(p, cx, cy, cw, ch, angle)
            p.setOpacity(1.0)

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
        icon_x, icon_y, icon_w = cx + 10, cy + (ch - 40) // 2, 40
        icon_h = 40

        icon_path = QPainterPath()
        icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 9, 9)

        icon_bg = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
        icon_bg.setColorAt(0.0, QColor("#161329"))
        icon_bg.setColorAt(1.0, QColor("#1d1b4b"))
        p.fillPath(icon_path, icon_bg)

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
        p.setFont(QFont("Inter", 18, QFont.Weight.Bold))
        p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                   Qt.AlignmentFlag.AlignCenter, "＋")

        tx = cx + icon_x - cx + icon_w + 10
        tw = cw - (tx - cx) - 10

        p.setPen(TEXT_WHITE)
        p.setFont(QFont("Inter", 11, QFont.Weight.Bold))
        p.drawText(QRect(tx, cy + 8, tw, 20),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "New Session")
        p.setPen(TEXT_DIM)
        p.setFont(QFont("Inter", 9))
        p.drawText(QRect(tx, cy + 30, tw, 18),
                   Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                   "Create a new workspace")

    def _paint_inline_input_bg(
        self, p: QPainter,
        cx: int, cy: int, cw: int, ch: int,
    ):
        p.setPen(TEXT_DIM)
        p.setFont(QFont("Inter", 9))
        p.drawText(
            QRect(cx + 14, cy + 10, cw - 28, 16),
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            "New workspace name",
        )

        input_y = cy + int(ch * 0.52)
        line_y  = input_y + 28
        p.setPen(QPen(QColor(80, 60, 140, 180), 1.0))
        p.drawLine(cx + 14, line_y, cx + cw - 14, line_y)

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

    def _paint_picker_hint(self, p: QPainter):
        fr = self._folder_rect()
        p.setPen(QColor(136, 136, 153, 200))
        p.setFont(QFont("Inter", 8))
        p.drawText(QRect(fr.x() - 10, fr.y() + FOLDER_H + 4, FOLDER_W + 20, 16),
                   Qt.AlignmentFlag.AlignCenter, "tap a session ↓")


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