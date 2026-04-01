"""
ui/drop_zone.py — Folder-style drop zone overlay.

Behaviour:
  • A macOS-style folder icon peeks from the top-right edge at all times.
  • When a window drag starts the folder slides fully into view.
  • When the cursor hovers over the folder, the paper tabs fan open AND
    session cards drop down one-by-one like iOS notifications.
  • Dropping onto a card saves the item to that session.
  • Dropping onto the folder body when only one session exists auto-saves.
  • "＋ New Session" card always appears below existing session cards.
  • Esc / Cancel dismisses at any time.

Public API (unchanged from original):
  on_drag_started(app_info)
  on_dropped(app_info)
  on_drag_cancelled()
  drop_zone_final_rect() -> tuple[int,int,int,int]
"""

from __future__ import annotations

import sys
from PyQt6.QtWidgets import QWidget, QApplication, QLineEdit
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, QRectF, pyqtProperty, QPoint, QSequentialAnimationGroup,
    QParallelAnimationGroup, QPauseAnimation, QAbstractAnimation
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QLinearGradient,
    QFont, QFontMetrics, QPen, QTransform, QBrush
)

import db

# ── Dimensions ────────────────────────────────────────────────────────────────
FOLDER_W        = 130          # folder icon width
FOLDER_H        = 108          # folder icon height
EDGE_PEEK       = 0            # px visible when hidden — fully off screen
TOP_MARGIN      = 60           # distance from screen top
WIDGET_W        = 360          # total overlay width (folder + cards)
WIDGET_H        = 600          # total overlay height

CARD_W          = 310
CARD_H          = 72
CARD_X          = 20           # x offset of cards inside widget
CARD_GAP        = 10
CARDS_START_Y   = FOLDER_H + 24   # y where first card rests (fully dropped)

# Paper layers (3 sheets that fan out behind folder lid)
PAPER_COUNT     = 3

# ── Colors ────────────────────────────────────────────────────────────────────
FOLDER_BODY     = QColor("#F5A623")   # amber body
FOLDER_BODY2    = QColor("#E8941A")   # darker gradient end
FOLDER_TAB      = QColor("#C87A10")   # tab / top flap
FOLDER_LID      = QColor("#F5A623")
PAPER_COLORS    = [QColor("#E0E0E0"), QColor("#ECECEC"), QColor("#F5F5F5")]

# Card colors — match wallet_panel dark theme
CARD_BG         = QColor("#1a1a24")
CARD_HOVER_BG   = QColor("#252535")
GRAD_TOP        = QColor("#d7cfcf")
GRAD_BOT        = QColor("#9198e5")
GRAD_HOVER_TOP  = QColor("#9198e5")
GRAD_HOVER_BOT  = QColor("#712020")
NEW_CARD_BG     = QColor("#1a1a24")
NEW_CARD_ICON   = QColor("#635bff")
TEXT_WHITE      = QColor(255, 255, 255)
TEXT_DIM        = QColor(136, 136, 153)   # matches wallet #888899
CONFIRM_GREEN   = QColor("#42d778")


class _CardState:
    """Runtime state for one animated session card."""
    def __init__(self, index: int):
        self.index       = index
        self.y_offset    = 0.0     # 0 = fully dropped, negative = hidden above
        self.hovered     = False
        self.scale       = 1.0


class DropZoneOverlay(QWidget):
    """Folder-style drop zone that slides in from the top-right edge."""

    def __init__(self, parent=None):
        super().__init__(parent)

        self._sessions:        list[dict]   = []
        self._card_states:     list[_CardState] = []
        self._pending_app:     dict | None  = None
        self._active_session_id: int | None = None
        self._picker_mode      = False
        self._drop_confirmed   = False
        self._confirmed_label  = ""
        self._confirmed_card_i = -1
        self._folder_hovered   = False
        self._cards_visible    = False

        # Folder slide (0 = fully in, 1 = fully hidden)
        self._slide_x = 1.0

        # Paper fan angle (0 = flat, 1 = fanned open)
        self._fan     = 0.0

        # Per-card drop progress (0 = hidden above, 1 = fully dropped)
        self._card_drops: list[float] = []

        # Hover scale per card
        self._card_scales: list[float] = []

        # Confirm flash alpha
        self._confirm_alpha = 0.0

        self._setup_window()
        self._position_on_screen()
        self._refresh_sessions()
        self._build_slide_anim()

        # Inline new-session input
        self._new_sess_input = QLineEdit(self)
        self._new_sess_input.setPlaceholderText("Session name…")
        self._new_sess_input.setFixedHeight(32)
        self._new_sess_input.hide()
        self._new_sess_input.returnPressed.connect(self._create_new_session)
        self._new_sess_input.setStyleSheet("""
            QLineEdit {
                background: #252535; color: #ffffff;
                border: none; border-radius: 10px;
                padding: 0 12px; font-size: 13px;
                font-family: 'Helvetica Neue', 'Helvetica', sans-serif;
            }
            QLineEdit:focus {
                background: #2e2e42;
            }
        """)

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self._finish_confirm)

        _ref = QTimer(self)
        _ref.timeout.connect(self._refresh_sessions)
        _ref.start(5000)

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
            WIDGET_H
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
        # v=0 → fully visible, v=1 → completely off screen (no peek)
        offset = int(WIDGET_W * v)
        self.move(
            geo.x() + geo.width() - WIDGET_W + offset,
            geo.y() + TOP_MARGIN
        )

    def _slide_in(self):
        self._slide_anim.stop()
        self._slide_anim.setStartValue(self._slide_x)
        self._slide_anim.setEndValue(0.0)
        self._slide_anim.start()
        # Install global event filter so Esc works without focus
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
        # Remove global event filter once hidden
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
        """Drop session cards down one by one with stagger.
        Cards already at 1.0 are NOT re-animated — they stay put."""
        n = len(self._sessions) + 1  # +1 for New Session card

        # Grow lists without resetting existing values
        while len(self._card_drops) < n:
            self._card_drops.append(0.0)
        while len(self._card_scales) < n:
            self._card_scales.append(1.0)
        self._card_drops  = self._card_drops[:n]
        self._card_scales = self._card_scales[:n]

        # Kill old pending anims and timers
        if hasattr(self, "_drop_anims"):
            for a in self._drop_anims:
                a.stop()
        if hasattr(self, "_drop_timers"):
            for t in self._drop_timers:
                t.stop()

        self._drop_anims  = []
        self._drop_timers = []

        for i in range(n):
            # Skip cards that are already fully dropped
            if self._card_drops[i] >= 0.99:
                continue

            anim = _CardDropAnim(self, i, self._card_drops)
            anim.setDuration(340)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            anim.setStartValue(self._card_drops[i])   # resume from wherever they are
            anim.setEndValue(1.0)

            delay_timer = QTimer(self)
            delay_timer.setSingleShot(True)
            def _start(a=anim): a.start()
            delay_timer.timeout.connect(_start)
            delay_timer.start(i * 80)
            self._drop_anims.append(anim)
            self._drop_timers.append(delay_timer)

    def _hide_cards(self):
        """Slide all cards back up and reset drop state fully."""
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
        self._pending_app      = app_info
        self._drop_confirmed   = False
        self._picker_mode      = False
        self._cards_visible    = False
        self._cards_dropped_once = False   # reset so first hover re-animates
        self._folder_hovered   = False
        self._new_sess_input.hide()
        # Fully reset card drop state for fresh animation
        self._hide_cards()
        self._fan = 0.0
        self._refresh_sessions()
        self._slide_in()
        self.update()

    def on_dropped(self, app_info: dict):
        """Called when user releases inside our zone."""
        cursor_local = self.mapFromGlobal(self.cursor().pos())
        cx, cy = cursor_local.x(), cursor_local.y()

        # Check if dropped on a session card
        card_i = self._card_at(cx, cy)
        if card_i is not None:
            if card_i == len(self._sessions):
                # New session card
                self._show_new_session_input(app_info)
            else:
                # Always show cards and enter picker mode to confirm
                self._pending_app   = app_info
                self._picker_mode   = True
                self._active_session_id = self._sessions[card_i]["id"]
                self.update()
            return

        # Dropped on folder body — enter picker mode always (ask user)
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
            print(f"[DropZone] Saved '{item['label']}' → session {sid}")
        else:
            print(f"[DropZone] Skipped — empty path_or_url for '{item['label']}'")

        self._confirmed_label   = item["label"]
        self._confirmed_card_i  = confirmed_card
        self._drop_confirmed    = True
        self._pending_app       = None
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
        """The folder body rect in widget coordinates."""
        return QRect(WIDGET_W - FOLDER_W - 4, 0, FOLDER_W, FOLDER_H)

    def _card_rect(self, index: int) -> QRect:
        """Rect for card[index] at its fully-dropped position."""
        y = CARDS_START_Y + index * (CARD_H + CARD_GAP)
        return QRect(CARD_X, y, CARD_W, CARD_H)

    def _card_at(self, x: int, y: int) -> int | None:
        """Return card index under (x,y) or None. Includes New Session card."""
        total = len(self._sessions) + 1
        for i in range(total):
            if i >= len(self._card_drops):
                continue
            drop_frac = self._card_drops[i]
            if drop_frac < 0.05:
                continue
            base_y   = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            # Cards animate from above — start_y offset
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
            # Only animate cards dropping the very first time per drag session
            if not getattr(self, "_cards_dropped_once", False):
                self._cards_dropped_once = True
                self._cards_visible = True
                self._drop_cards()
            self.update()
        elif not now_over_folder and self._folder_hovered:
            self._folder_hovered = False
            # Cards stay visible once shown — don't hide or re-trigger

        # Update card hover states
        changed = False
        total = len(self._sessions) + 1
        while len(self._card_scales) < total:
            self._card_scales.append(1.0)
        for i in range(total):
            r     = self._card_rect(i)
            hover = r.contains(x, y) and (i < len(self._card_drops) and self._card_drops[i] > 0.5)
            want  = 1.05 if hover else 1.0
            if abs(self._card_scales[i] - want) > 0.001:
                self._card_scales[i] = want
                changed = True
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

        # Cancel button area (bottom of widget)
        if y > WIDGET_H - 52:
            self._cancel()

    def eventFilter(self, obj, event):
        """Global event filter — catches Esc from any focused widget."""
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
        fan  = self._fan
        fr   = self._folder_rect()
        fx   = fr.x()
        fy   = fr.y()
        fw   = fr.width()
        fh   = fr.height()

        # ── Paper sheets — fan UPWARD out of the open folder ──────────────────
        # When fan=0 papers are hidden inside body. fan=1 they stick up above.
        for sheet in range(PAPER_COUNT):
            if fan < 0.05:
                break
            # Each sheet sticks up a different amount and angles slightly
            angle       = (sheet - 1) * 6 * fan           # -6, 0, +6 degrees
            rise        = int(fan * (14 + sheet * 8))      # how far above body top
            paper_h     = int(fh * 0.55)
            paper_w     = fw - 14
            paper_x     = fx + 7
            paper_y     = fy + 14 - rise                   # rises upward
            color       = PAPER_COLORS[PAPER_COUNT - 1 - sheet]

            p.save()
            p.translate(fx + fw / 2, fy + 14)             # rotate from hinge
            p.rotate(angle)
            p.translate(-(fx + fw / 2), -(fy + 14))
            pp = QPainterPath()
            pp.addRoundedRect(paper_x, paper_y, paper_w, paper_h, 6, 6)
            p.fillPath(pp, color)
            p.restore()

        # ── Folder body ───────────────────────────────────────────────────────
        body = QPainterPath()
        body.addRoundedRect(fx, fy + 14, fw, fh - 14, 12, 12)
        grad = QLinearGradient(fx, fy + 14, fx, fy + fh)
        grad.setColorAt(0, FOLDER_BODY)
        grad.setColorAt(1, FOLDER_BODY2)
        p.fillPath(body, grad)

        # Tab (top-left bump on back of folder)
        tab = QPainterPath()
        tab.addRoundedRect(fx, fy + 4, fw * 0.42, 14, 6, 6)
        p.fillPath(tab, FOLDER_TAB)

        # ── Lid — flips BACKWARD (upward) from hinge at top of body ──────────
        # fan=0: lid is flat covering the top of the body.
        # fan=1: lid has rotated ~180deg back (scale_y goes 1 → 0 → slightly negative).
        # We clamp at a small positive so it never fully disappears.
        hinge_y = fy + 14
        p.save()
        p.translate(fx + fw / 2, hinge_y)
        # scale_y: 1.0 at fan=0 (closed), shrinks to 0 at fan=0.5, then flips
        # We only show the closing sweep (fan 0→0.5 → lid shrinks to nothing)
        # beyond that the lid is behind the folder — invisible.
        raw_scale = 1.0 - fan * 2.0          # 1 → -1
        scale_y   = max(-0.08, raw_scale)    # allow a tiny flip-past for realism
        p.scale(1.0, scale_y)
        p.translate(-(fx + fw / 2), -hinge_y)

        lid = QPainterPath()
        lid.addRoundedRect(fx + 1, fy, fw - 2, 18, 6, 6)
        lid_grad = QLinearGradient(fx, fy, fx, fy + 18)
        lid_grad.setColorAt(0, FOLDER_LID.lighter(118))
        lid_grad.setColorAt(1, FOLDER_LID)
        p.fillPath(lid, lid_grad)
        p.restore()

        # ── Interior shadow when open — gives depth ───────────────────────────
        if fan > 0.5:
            alpha = int((fan - 0.5) * 2 * 60)
            inner = QPainterPath()
            inner.addRoundedRect(fx + 4, fy + 16, fw - 8, 20, 4, 4)
            p.fillPath(inner, QColor(0, 0, 0, alpha))

        # Label
        p.setPen(QColor(100, 60, 10))
        f = QFont("Helvetica Neue", 7, QFont.Weight.Bold)
        p.setFont(f)
        p.drawText(QRect(fx, fy + fh - 20, fw, 18),
                   Qt.AlignmentFlag.AlignCenter, "WORKSPACE")

    # ── Session / notification cards ──────────────────────────────────────────

    def _paint_cards(self, p: QPainter):
        total = len(self._sessions) + 1   # +1 for New Session

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
            is_sess  = not is_new
            sess     = self._sessions[i] if is_sess else None
            is_active = is_sess and sess and sess["id"] == self._active_session_id
            is_confirmed = (i == self._confirmed_card_i and self._drop_confirmed)

            base_y   = CARDS_START_Y + i * (CARD_H + CARD_GAP)
            # Slide in from above
            slide_off = int((1.0 - drop_frac) * (CARD_H + 50))
            cy        = base_y - slide_off

            # Scale around card centre
            cx_centre = CARD_X + CARD_W / 2
            cy_centre = cy + CARD_H / 2
            p.save()
            p.translate(cx_centre, cy_centre)
            p.scale(scale, scale)
            p.translate(-cx_centre, -cy_centre)

            # Card background — hover just lightens, no outline ever
            cr = QRectF(CARD_X, cy, CARD_W, CARD_H)
            bg_path = QPainterPath()
            bg_path.addRoundedRect(cr, 14, 14)

            if is_confirmed:
                p.fillPath(bg_path, CONFIRM_GREEN.darker(110))
            elif is_new:
                # New session card — same dark background, purple icon accent
                hover_alpha = 255 if scale > 1.01 else 230
                bg = QColor(CARD_BG)
                bg.setAlpha(hover_alpha)
                new_bg = QColor("#1e1e2e") if scale <= 1.01 else QColor("#262638")
                p.fillPath(bg_path, new_bg)
            else:
                if scale > 1.01:
                    p.fillPath(bg_path, CARD_HOVER_BG)
                else:
                    p.fillPath(bg_path, CARD_BG)

            # Gradient square (icon area)  — matches your HTML .img
            icon_x = CARD_X + 10
            icon_y = cy + 10
            icon_w = 50
            icon_h = 50
            icon_path = QPainterPath()
            icon_path.addRoundedRect(icon_x, icon_y, icon_w, icon_h, 10, 10)

            if is_confirmed:
                icon_grad = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
                icon_grad.setColorAt(0, QColor("#42d778"))
                icon_grad.setColorAt(1, QColor("#1a8a40"))
            elif is_new:
                icon_grad = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
                icon_grad.setColorAt(0, QColor("#7c74ff"))
                icon_grad.setColorAt(1, QColor("#635bff"))
            elif scale > 1.01:
                icon_grad = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
                icon_grad.setColorAt(0, GRAD_HOVER_TOP)
                icon_grad.setColorAt(1, GRAD_HOVER_BOT)
            else:
                icon_grad = QLinearGradient(icon_x, icon_y, icon_x, icon_y + icon_h)
                icon_grad.setColorAt(0, GRAD_TOP)
                icon_grad.setColorAt(1, GRAD_BOT)
            p.fillPath(icon_path, icon_grad)

            # Icon centre text
            p.setPen(TEXT_WHITE)
            p.setFont(QFont("Helvetica Neue", 16))
            p.drawText(QRect(icon_x, icon_y, icon_w, icon_h),
                       Qt.AlignmentFlag.AlignCenter,
                       "✓" if is_confirmed else ("＋" if is_new else "◈"))

            # Text area — mirrors your HTML .textBox
            tx = CARD_X + 70
            tw = CARD_W - 80

            if is_confirmed:
                # Title
                p.setPen(TEXT_WHITE)
                p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
                p.drawText(QRect(tx, cy + 10, tw, 22),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           "Saved!")
                # Body
                p.setPen(TEXT_DIM)
                p.setFont(QFont("Helvetica Neue", 9))
                fm  = QFontMetrics(p.font())
                lbl = fm.elidedText(self._confirmed_label,
                                    Qt.TextElideMode.ElideRight, tw)
                p.drawText(QRect(tx, cy + 36, tw, 20),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           lbl)

            elif is_new:
                p.setPen(TEXT_WHITE)
                p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
                p.drawText(QRect(tx, cy + 10, tw - 10, 22),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           "New Session")
                p.setPen(TEXT_DIM)
                p.setFont(QFont("Helvetica Neue", 9))
                p.drawText(QRect(tx, cy + 36, tw, 20),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           "Create a new workspace")
            else:
                name     = sess.get("name", "Session") if sess else "Session"
                items    = db.get_items(sess["id"]) if sess else []
                n_items  = len(items)
                time_str = "active" if is_active else f"{n_items} items"

                p.setPen(TEXT_WHITE)
                p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
                fm   = QFontMetrics(p.font())
                name_elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, tw - 60)
                p.drawText(QRect(tx, cy + 10, tw - 60, 22),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           name_elided)

                p.setPen(TEXT_DIM)
                p.setFont(QFont("Helvetica Neue", 8))
                p.drawText(QRect(tx, cy + 10, tw - 4, 22),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                           time_str)

                p.setPen(TEXT_DIM)
                p.setFont(QFont("Helvetica Neue", 9))
                p.drawText(QRect(tx, cy + 36, tw, 20),
                           Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                           f"{n_items} item{'s' if n_items != 1 else ''} saved")

            p.restore()

    # ── Confirm overlay ───────────────────────────────────────────────────────

    def _paint_confirm_overlay(self, p: QPainter):
        # The confirmed card already shows green in _paint_cards
        # Just add a subtle full-widget dim + tick near folder
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
    """
    Animates a single float in a list (self._parent._card_drops[index]).
    We can't use pyqtProperty on a list element directly, so we subclass
    QPropertyAnimation and override update delivery.
    """
    def __init__(self, widget: DropZoneOverlay, index: int, store: list):
        super().__init__()
        self._widget = widget
        self._index  = index
        self._store  = store

    def updateCurrentValue(self, value):
        if self._index < len(self._store):
            self._store[self._index] = value
        self._widget.update()