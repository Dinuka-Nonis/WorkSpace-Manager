"""
ui/drop_zone.py — Right-edge drop zone overlay.

Fixes vs original:
  • drop_zone_final_rect() — returns the FULLY VISIBLE rect, not the
    animated/partial current position. This was the root cause of drops
    not saving: the watcher was checking against the wrong coordinates.
  • Session cards shown during active drag so the user can click to
    switch the target session before releasing.
  • "New Session" button shown when no sessions exist, with an inline
    name input so the user never gets a silent auto-created session.
  • Session picker shown after drop when multiple sessions exist and
    none was explicitly pre-selected during the drag.
  • Snapshot feature removed entirely.

State machine:
  HIDDEN  → drag_started  → VISIBLE  (slide in, show session cards)
  VISIBLE → drag_cancelled → HIDDEN   (slide out)
  VISIBLE → dropped       → PICK/SAVE → CONFIRM → HIDDEN
"""

import sys
from PyQt6.QtWidgets import (
    QWidget, QApplication, QLineEdit, QPushButton,
    QHBoxLayout, QVBoxLayout
)
from PyQt6.QtCore import (
    Qt, QTimer, QPropertyAnimation, QEasingCurve,
    QRect, pyqtProperty, QPoint
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QLinearGradient,
    QFont, QFontMetrics, QPen
)

import db

# ── Design tokens ─────────────────────────────────────────────────────────────
WALLET_BG       = QColor("#1a2e1a")
WALLET_BG2      = QColor("#1e341e")
WALLET_STITCH   = QColor("#3d5635")
WALLET_GLOW     = QColor("#42d778")
WALLET_TEXT     = QColor("#a7c59e")
WALLET_TEXT_DIM = QColor("#698263")
WALLET_CARD_COLORS = [
    QColor("#635bff"),  # purple
    QColor("#9bd86a"),  # green
    QColor("#f59e0b"),  # amber
    QColor("#ef4444"),  # red
    QColor("#06b6d4"),  # cyan
]

ZONE_WIDTH  = 280
EDGE_HANDLE = 6   # px strip visible when fully hidden

# Vertical layout constants
HEADER_H        = 80
APP_CARD_Y      = HEADER_H + 10
APP_CARD_H      = 72
SESSION_LIST_Y  = APP_CARD_Y + APP_CARD_H + 16
CARD_H          = 52
CARD_GAP        = 8
NEW_BTN_H       = 40


class DropZoneOverlay(QWidget):
    """
    Wallet-style drop zone that slides in from the right edge during window drags.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active_session_id: int | None = None
        self._sessions: list[dict] = []
        self._pending_app: dict | None = None
        self._hovered           = False
        self._drop_confirmed    = False
        self._confirmed_label   = ""
        self._user_selected_session = False   # True once user clicks a card

        self._confirm_timer = QTimer(self)
        self._confirm_timer.setSingleShot(True)
        self._confirm_timer.timeout.connect(self._hide_after_confirm)

        self._slide_x = 1.0  # 0=fully visible, 1=fully hidden

        self._setup_window()
        self._setup_animation()
        self._position_on_screen()
        self._refresh_sessions()

        # Build the "new session" inline input (hidden until needed)
        self._new_sess_input = QLineEdit(self)
        self._new_sess_input.setPlaceholderText("Session name…")
        self._new_sess_input.setFixedHeight(32)
        self._new_sess_input.hide()
        self._new_sess_input.returnPressed.connect(self._create_new_session)
        self._new_sess_input.setStyleSheet("""
            QLineEdit {
                background: #2a3e2a; color: #a7c59e;
                border: 1px solid #3d5635; border-radius: 6px;
                padding: 0 8px; font-size: 12px;
            }
        """)

        _ref = QTimer(self)
        _ref.timeout.connect(self._refresh_sessions)
        _ref.start(5000)

    # ── Window / animation setup ──────────────────────────────────────────────

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

    def _setup_animation(self):
        self._anim = QPropertyAnimation(self, b"slideX", self)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.setDuration(300)

    def _position_on_screen(self):
        screen = QApplication.primaryScreen()
        if not screen:
            return
        geo = screen.geometry()
        self._screen_geo = geo
        self.setGeometry(
            geo.x() + geo.width() - ZONE_WIDTH,
            geo.y(),
            ZONE_WIDTH,
            geo.height()
        )
        self._apply_slide(1.0)

    # ── Slide property ────────────────────────────────────────────────────────

    def getSlideX(self) -> float:
        return self._slide_x

    def setSlideX(self, value: float):
        self._slide_x = value
        self._apply_slide(value)
        self.update()

    slideX = pyqtProperty(float, getSlideX, setSlideX)

    def _apply_slide(self, value: float):
        if not hasattr(self, "_screen_geo"):
            return
        geo    = self._screen_geo
        offset = int((ZONE_WIDTH - EDGE_HANDLE) * value)
        self.move(geo.x() + geo.width() - ZONE_WIDTH + offset, geo.y())

    # ── Public API ────────────────────────────────────────────────────────────

    def drop_zone_final_rect(self) -> tuple[int, int, int, int]:
        """
        Return the rect for the FULLY VISIBLE position.

        This is what the DragWatcher must use for its cursor check.
        Do NOT use geometry() here — during animation it is wrong.
        """
        if not hasattr(self, "_screen_geo"):
            s = QApplication.primaryScreen()
            geo = s.geometry() if s else QApplication.primaryScreen().geometry()
        else:
            geo = self._screen_geo
        return (
            geo.x() + geo.width() - ZONE_WIDTH,
            geo.y(),
            ZONE_WIDTH,
            geo.height(),
        )

    def on_drag_started(self, app_info: dict):
        self._pending_app           = app_info
        self._drop_confirmed        = False
        self._hovered               = False
        self._user_selected_session = False
        self._new_sess_input.hide()
        self._refresh_sessions()
        self._slide_in()
        self.update()

    def on_dropped(self, app_info: dict):
        """Called when the user releases inside our zone."""
        # Check if release was over the "+ New Session" button
        cursor_y = self.mapFromGlobal(self.cursor().pos()).y()
        new_btn_y = SESSION_LIST_Y + len(self._sessions) * (CARD_H + CARD_GAP) + 8
        over_new_btn = (new_btn_y <= cursor_y <= new_btn_y + NEW_BTN_H)

        if not self._sessions or over_new_btn:
            # No sessions, or explicitly dropped on "New Session"
            self._show_new_session_input(app_info)
        elif not self._user_selected_session and len(self._sessions) > 1:
            # Multiple sessions, nothing pre-selected — keep overlay open
            # so user can pick; show a small "tap a card to save" hint.
            self._pending_app = app_info
            self._show_session_picker(app_info)
        else:
            # Either one session or user already clicked a card
            self._save_to_session(app_info)

    def request_new_session(self):
        """Called when the user taps '+ New Session' even when sessions exist."""
        self._show_new_session_input(self._pending_app)

    def on_drag_cancelled(self):
        self._pending_app = None
        self._new_sess_input.hide()
        if not self._drop_confirmed:
            self._slide_out()

    def set_active_session(self, session_id: int):
        self._active_session_id     = session_id
        self._user_selected_session = True
        self._refresh_sessions()
        self.update()

    # ── Session picker mode (shown after drop when ambiguous) ─────────────────

    def _show_session_picker(self, app_info: dict):
        """
        Keep the overlay open after the drop and wait for the user to click
        a session card. A small instruction replaces the "DROP HERE" header.
        """
        self._pending_app = app_info
        self.update()
        # Auto-save to first session if user doesn't pick within 8 s
        self._confirm_timer.start(8000)

    def _show_new_session_input(self, app_info: dict):
        """Show the inline name input for a brand-new session.
        Positions the input below any existing session cards."""
        self._pending_app = app_info
        # Position below existing cards so the input never overlaps them
        input_y = SESSION_LIST_Y + len(self._sessions) * (CARD_H + CARD_GAP) + 8
        self._new_sess_input.setGeometry(20, input_y, ZONE_WIDTH - 40, 32)
        self._new_sess_input.clear()
        self._new_sess_input.show()
        self._new_sess_input.setFocus()
        self.update()

    def _create_new_session(self):
        name = self._new_sess_input.text().strip() or "My Workspace"
        self._new_sess_input.hide()
        sid = db.create_session(name)
        self._active_session_id     = sid
        self._user_selected_session = True
        self._refresh_sessions()
        if self._pending_app:
            self._save_to_session(self._pending_app)

    # ── Slide helpers ─────────────────────────────────────────────────────────

    def _slide_in(self):
        self._anim.stop()
        self._anim.setStartValue(self._slide_x)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _slide_out(self):
        self._anim.stop()
        self._anim.setStartValue(self._slide_x)
        self._anim.setEndValue(1.0)
        self._anim.start()

    def _hide_after_confirm(self):
        self._drop_confirmed        = False
        self._user_selected_session = False
        if self._pending_app:
            # Timer fired from picker mode — auto-save to first session
            app = self._pending_app
            self._pending_app = None
            if self._sessions:
                self._active_session_id = self._sessions[0]["id"]
            self._save_to_session(app)
        else:
            self._slide_out()

    # ── Data ──────────────────────────────────────────────────────────────────

    def _refresh_sessions(self):
        self._sessions = db.get_all_sessions()[:6]
        if self._active_session_id is None and self._sessions:
            self._active_session_id = self._sessions[0]["id"]
        self.update()

    def _save_to_session(self, app_info: dict):
        self._confirm_timer.stop()

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

        self._confirmed_label       = item["label"]
        self._drop_confirmed        = True
        self._pending_app           = None
        self._user_selected_session = False
        self._refresh_sessions()
        self.update()
        self._confirm_timer.start(2200)

    # ── Mouse events ──────────────────────────────────────────────────────────

    def enterEvent(self, event):
        self._hovered = True
        self.update()

    def leaveEvent(self, event):
        self._hovered = False
        self.update()

    def mousePressEvent(self, event):
        y = event.position().y()

        # Clicking a session card always selects it as active target
        for i, sess in enumerate(self._sessions):
            card_y = SESSION_LIST_Y + i * (CARD_H + CARD_GAP)
            if card_y <= y <= card_y + CARD_H:
                self._active_session_id     = sess["id"]
                self._user_selected_session = True
                self.update()

                # If a drop is pending (picker mode), save immediately
                if self._pending_app is not None:
                    app = self._pending_app
                    self._pending_app = None
                    self._save_to_session(app)
                return

        # "+ New Session" button — shown at the bottom of the card list
        # regardless of whether sessions already exist.
        new_btn_y = SESSION_LIST_Y + len(self._sessions) * (CARD_H + CARD_GAP) + 8
        if new_btn_y <= y <= new_btn_y + NEW_BTN_H and self._new_sess_input.isHidden():
            self._show_new_session_input(self._pending_app)

    # ── Paint ─────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()

        # Background
        bg = QPainterPath()
        bg.addRoundedRect(8, 0, w - 8, h, 20, 20)
        p.fillPath(bg, WALLET_BG)

        # Stitched border
        sp = QPen(WALLET_STITCH, 1.2, Qt.PenStyle.DashLine)
        sp.setDashPattern([4, 3])
        p.setPen(sp)
        inner = QPainterPath()
        inner.addRoundedRect(14, 6, w - 20, h - 12, 15, 15)
        p.drawPath(inner)

        if self._drop_confirmed:
            self._paint_confirmed(p, w, h)
        elif self._pending_app is not None:
            self._paint_active(p, w, h)
        else:
            self._paint_idle(p, w, h)

        p.end()

    # ── Idle state ────────────────────────────────────────────────────────────

    def _paint_idle(self, p, w, h):
        p.setPen(WALLET_TEXT)
        p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
        p.drawText(QRect(20, 24, w - 40, 28), Qt.AlignmentFlag.AlignLeft, "WORKSPACE")

        p.setPen(WALLET_TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 9))
        p.drawText(QRect(20, 50, w - 40, 20), Qt.AlignmentFlag.AlignLeft,
                   "Drag a window to the right edge to save")

        self._paint_session_cards(p, w, show_active_dot=True)

        # Bottom hint
        p.setPen(WALLET_TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 8))
        p.drawText(QRect(20, h - 55, w - 40, 40), Qt.AlignmentFlag.AlignCenter,
                   "Click a card to switch target session")

    # ── Active drag state ─────────────────────────────────────────────────────

    def _paint_active(self, p, w, h):
        app = self._pending_app
        if not app:
            return

        # Glow when hovered
        if self._hovered:
            gp = QPainterPath()
            gp.addRoundedRect(8, 0, w - 8, h, 20, 20)
            gc = QColor(WALLET_GLOW)
            gc.setAlpha(18)
            p.fillPath(gp, gc)
            border = QPainterPath()
            border.addRoundedRect(10, 2, w - 14, h - 4, 18, 18)
            p.setPen(QPen(WALLET_GLOW, 2.0))
            p.drawPath(border)

        # Header
        if not self._user_selected_session and len(self._sessions) > 1 and \
                self._pending_app is not None and self._pending_app == app:
            # Picker mode hint
            p.setPen(WALLET_GLOW)
            p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
            p.drawText(QRect(20, 18, w - 40, 24), Qt.AlignmentFlag.AlignLeft, "CHOOSE SESSION")
            p.setPen(WALLET_TEXT_DIM)
            p.setFont(QFont("Helvetica Neue", 9))
            p.drawText(QRect(20, 44, w - 40, 18), Qt.AlignmentFlag.AlignLeft,
                       "Tap a card below to save there")
        else:
            p.setPen(WALLET_GLOW)
            p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
            p.drawText(QRect(20, 18, w - 40, 24), Qt.AlignmentFlag.AlignLeft, "DROP HERE")
            p.setPen(WALLET_TEXT_DIM)
            p.setFont(QFont("Helvetica Neue", 9))
            p.drawText(QRect(20, 44, w - 40, 18), Qt.AlignmentFlag.AlignLeft,
                       "Release to save to session")

        # App preview card
        ap = QPainterPath()
        ap.addRoundedRect(20, APP_CARD_Y, w - 40, APP_CARD_H, 12, 12)
        p.fillPath(ap, WALLET_CARD_COLORS[0])

        p.setPen(QColor(255, 255, 255))
        lf = QFont("Helvetica Neue", 10, QFont.Weight.Bold)
        p.setFont(lf)
        label = app.get("label", "Unknown")
        label = QFontMetrics(lf).elidedText(label, Qt.TextElideMode.ElideRight, w - 70)
        p.drawText(QRect(30, APP_CARD_Y + 12, w - 60, 26),
                   Qt.AlignmentFlag.AlignVCenter, label)
        p.setPen(QColor(255, 255, 255, 130))
        p.setFont(QFont("Helvetica Neue", 8))
        p.drawText(QRect(30, APP_CARD_Y + 38, w - 60, 20),
                   Qt.AlignmentFlag.AlignVCenter, app.get("type", "app").upper())

        # Session list (always visible during drag for pre-selection)
        self._paint_session_cards(p, w, show_active_dot=True)

        # "+ New Session" button — always shown so user can create a new session
        if self._new_sess_input.isHidden():
            self._paint_new_session_btn(p, w)

    # ── Confirmed state ───────────────────────────────────────────────────────

    def _paint_confirmed(self, p, w, h):
        gp = QPainterPath()
        gp.addRoundedRect(8, 0, w - 8, h, 20, 20)
        gc = QColor(WALLET_GLOW)
        gc.setAlpha(22)
        p.fillPath(gp, gc)
        border = QPainterPath()
        border.addRoundedRect(10, 2, w - 14, h - 4, 18, 18)
        p.setPen(QPen(WALLET_GLOW, 2.0))
        p.drawPath(border)

        cx, cy = w // 2, h // 2 - 60
        cp = QPainterPath()
        cp.addEllipse(cx - 28, cy - 28, 56, 56)
        p.fillPath(cp, WALLET_GLOW)
        p.setPen(QColor(255, 255, 255))
        p.setFont(QFont("Helvetica Neue", 22, QFont.Weight.Bold))
        p.drawText(QRect(cx - 28, cy - 28, 56, 56), Qt.AlignmentFlag.AlignCenter, "✓")

        p.setPen(WALLET_GLOW)
        p.setFont(QFont("Helvetica Neue", 11, QFont.Weight.Bold))
        p.drawText(QRect(20, h // 2 + 10, w - 40, 28), Qt.AlignmentFlag.AlignCenter, "SAVED")

        lf = QFont("Helvetica Neue", 9)
        p.setPen(WALLET_TEXT)
        p.setFont(lf)
        label = QFontMetrics(lf).elidedText(self._confirmed_label,
                                             Qt.TextElideMode.ElideRight, w - 60)
        p.drawText(QRect(20, h // 2 + 42, w - 40, 22), Qt.AlignmentFlag.AlignCenter, label)

        sess_name = next((s["name"] for s in self._sessions
                          if s["id"] == self._active_session_id), "Session")
        p.setPen(WALLET_TEXT_DIM)
        p.setFont(QFont("Helvetica Neue", 8))
        p.drawText(QRect(20, h // 2 + 68, w - 40, 20),
                   Qt.AlignmentFlag.AlignCenter, f"→ {sess_name}")

    # ── Shared: session card list ─────────────────────────────────────────────

    def _paint_session_cards(self, p, w, show_active_dot: bool = False):
        """Draw clickable session cards starting at SESSION_LIST_Y."""
        for i, sess in enumerate(self._sessions):
            color    = WALLET_CARD_COLORS[i % len(WALLET_CARD_COLORS)]
            is_active = (sess["id"] == self._active_session_id)
            card_y   = SESSION_LIST_Y + i * (CARD_H + CARD_GAP)

            # Shadow
            sh = QPainterPath()
            sh.addRoundedRect(22, card_y + 3, w - 44, CARD_H, 10, 10)
            sc = QColor(0, 0, 0, 40)
            p.fillPath(sh, sc)

            # Body — brighter when active
            cp = QPainterPath()
            cp.addRoundedRect(20, card_y, w - 40, CARD_H, 10, 10)
            cc = QColor(color)
            if is_active:
                cc = cc.lighter(115)
            p.fillPath(cp, cc)

            # Active dot
            if is_active and show_active_dot:
                dp = QPainterPath()
                dp.addEllipse(w - 28, card_y + 8, 7, 7)
                p.fillPath(dp, QColor(255, 255, 255, 200))

            # Name
            brightness = (cc.red() * 299 + cc.green() * 587 + cc.blue() * 114) / 1000
            text_color = QColor(0, 0, 0) if brightness > 160 else QColor(255, 255, 255)
            p.setPen(text_color)
            p.setFont(QFont("Helvetica Neue", 9, QFont.Weight.Bold))
            p.drawText(QRect(30, card_y, w - 60, CARD_H),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       sess.get("name", "Session"))

            # Item count
            items = db.get_items(sess["id"])
            tc    = QColor(text_color)
            tc.setAlpha(140)
            p.setPen(tc)
            p.setFont(QFont("Helvetica Neue", 8))
            p.drawText(QRect(30, card_y + 28, w - 60, 18),
                       Qt.AlignmentFlag.AlignLeft,
                       f"{len(items)} items")

    def _paint_new_session_btn(self, p, w):
        """Paint a '+  New Session' button below all existing session cards."""
        by = SESSION_LIST_Y + len(self._sessions) * (CARD_H + CARD_GAP) + 8
        bp = QPainterPath()
        bp.addRoundedRect(20, by, w - 40, NEW_BTN_H, 10, 10)
        bc = QColor(WALLET_GLOW)
        bc.setAlpha(30)
        p.fillPath(bp, bc)
        p.setPen(QPen(WALLET_GLOW, 1.0))
        p.drawPath(bp)
        p.setPen(WALLET_GLOW)
        p.setFont(QFont("Helvetica Neue", 10, QFont.Weight.Bold))
        p.drawText(QRect(20, by, w - 40, NEW_BTN_H),
                   Qt.AlignmentFlag.AlignCenter, "+  New Session")
