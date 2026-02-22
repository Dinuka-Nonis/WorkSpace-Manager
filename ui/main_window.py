"""
ui/main_window.py — Full session dashboard.
Shows all sessions in card grid, stats, restore/delete actions.
Matches the HTML mockup design closely.
"""

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QFrame, QGraphicsDropShadowEffect,
    QSizePolicy, QMessageBox, QGridLayout, QApplication
)
from PyQt6.QtCore import (
    Qt, pyqtSignal, QSize, QTimer
)
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QLinearGradient,
    QPen, QPixmap, QIcon, QBrush
)

import db
import restore as restorer
from snapshot import friendly_app_name
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER, ACCENT, ACCENT2, ACCENT_DIM,
    TEXT, MUTED, MUTED2, GREEN, AMBER, RED,
    WHITE_005, ACCENT_010, ACCENT_020
)

STATUS_COLORS = {"active": GREEN, "paused": AMBER, "idle": MUTED}
STATUS_BG = {
    "active": "rgba(74,222,128,0.12)",
    "paused": "rgba(251,191,36,0.12)",
    "idle": "rgba(107,107,128,0.08)",
}


class ToastNotification(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint |
                            Qt.WindowType.WindowStaysOnTopHint |
                            Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(300, 44)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.hide)
        self._icon = ""
        self._msg = ""

    def show_toast(self, icon: str, msg: str, duration=2500):
        self._icon = icon
        self._msg = msg
        screen = QApplication.primaryScreen().availableGeometry()
        self.move(screen.center().x() - 150, screen.bottom() - 80)
        self.show()
        self.raise_()
        self.update()
        self._timer.start(duration)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)
        p.fillPath(path, QColor(20, 20, 32, 240))
        pen = QPen(QColor(ACCENT), 1)
        p.setPen(pen)
        p.drawPath(path)
        p.setPen(QColor(TEXT))
        p.setFont(QFont("Segoe UI Variable", 12))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                   f"  {self._icon}  {self._msg}")


class SessionFullCard(QWidget):
    restore_clicked = pyqtSignal(int)
    delete_clicked = pyqtSignal(int)

    def __init__(self, session: dict, stats: dict, parent=None):
        super().__init__(parent)
        self.session_id = session["id"]
        self.status = session.get("status", "idle")
        self._hovered = False
        self.setFixedHeight(230)
        self.setCursor(Qt.CursorShape.ArrowCursor)
        self._build(session, stats)

    def _build(self, session: dict, stats: dict):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # ── Top: icon + name + status ──
        top = QHBoxLayout()
        top.setSpacing(10)

        icon_w = QLabel(session.get("icon", "🗂"))
        icon_w.setFixedSize(42, 42)
        icon_w.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_w.setStyleSheet(f"""
            background: {STATUS_BG.get(self.status, 'rgba(124,106,247,0.1)')};
            border-radius: 12px;
            font-size: 20px;
        """)
        top.addWidget(icon_w)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        name = QLabel(session["name"])
        name.setStyleSheet(f"""
            color: {TEXT};
            font-size: 14px;
            font-weight: 700;
            font-family: "Segoe UI Variable";
            letter-spacing: -0.3px;
        """)
        title_col.addWidget(name)

        from datetime import datetime
        try:
            dt = datetime.fromisoformat(session.get("created_at", ""))
            date_str = dt.strftime("%b %d, %H:%M")
        except Exception:
            date_str = "—"
        date_lbl = QLabel(date_str)
        date_lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        title_col.addWidget(date_lbl)
        top.addLayout(title_col)
        top.addStretch()

        color = STATUS_COLORS.get(self.status, MUTED)
        status_badge = QLabel(self.status.upper())
        status_badge.setStyleSheet(f"""
            color: {color};
            background: {color}22;
            border-radius: 12px;
            padding: 2px 10px;
            font-size: 9px;
            font-weight: 700;
            letter-spacing: 1px;
            font-family: "Cascadia Mono", monospace;
        """)
        top.addWidget(status_badge)
        layout.addLayout(top)

        # ── App chips row ──
        chips = QHBoxLayout()
        chips.setSpacing(5)
        chips.setContentsMargins(0, 0, 0, 0)

        tab_count = stats.get("tab_count", 0)
        if tab_count > 0:
            chips.addWidget(self._chip(f"🌐 {tab_count} tab{'s' if tab_count != 1 else ''}", "#4285f4"))

        for app in stats.get("apps", [])[:5]:
            chips.addWidget(self._chip(f"🪟 {app}"))

        chips.addStretch()
        layout.addLayout(chips)

        # ── Description (from last snapshot title) ──
        desc = QLabel(f"Windows: {stats.get('window_count',0)}  ·  Apps: {stats.get('app_count',0)}")
        desc.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        layout.addWidget(desc)

        # ── Stats row ──
        stats_row = QHBoxLayout()
        for val, lbl in [
            (str(tab_count), "tabs"),
            (str(stats.get("window_count", 0)), "windows"),
            (stats.get("duration", "—"), "time"),
        ]:
            col = QVBoxLayout()
            col.setSpacing(1)
            v = QLabel(val)
            v.setStyleSheet(f"""
                color: {STATUS_COLORS.get(self.status, ACCENT)};
                font-size: 16px;
                font-weight: 700;
                font-family: "Segoe UI Variable";
            """)
            v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            l = QLabel(lbl)
            l.setStyleSheet(f"color: {MUTED}; font-size: 10px;")
            l.setAlignment(Qt.AlignmentFlag.AlignCenter)
            col.addWidget(v)
            col.addWidget(l)
            stats_row.addLayout(col)
            if lbl != "time":
                stats_row.addWidget(self._vline())
        layout.addLayout(stats_row)

        # ── Action buttons ──
        actions = QHBoxLayout()
        actions.setSpacing(8)

        restore_btn = QPushButton("↩  Restore Session")
        restore_btn.setStyleSheet(f"""
            QPushButton {{
                background: {ACCENT};
                border: none;
                color: white;
                border-radius: 9px;
                padding: 8px 0;
                font-size: 12px;
                font-weight: 700;
                font-family: "Segoe UI Variable";
            }}
            QPushButton:hover {{
                background: {ACCENT2};
            }}
        """)
        restore_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restore_btn.clicked.connect(lambda: self.restore_clicked.emit(self.session_id))
        actions.addWidget(restore_btn, 3)

        del_btn = QPushButton("🗑 Delete")
        del_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(248,113,113,0.1);
                border: 1px solid rgba(248,113,113,0.2);
                color: {RED};
                border-radius: 9px;
                padding: 8px 0;
                font-size: 12px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background: rgba(248,113,113,0.22);
                border-color: {RED};
            }}
        """)
        del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        del_btn.clicked.connect(lambda: self.delete_clicked.emit(self.session_id))
        actions.addWidget(del_btn, 1)

        layout.addLayout(actions)

    def _chip(self, text: str, color: str = None) -> QLabel:
        lbl = QLabel(text)
        c = color or MUTED
        lbl.setStyleSheet(f"""
            color: {c};
            background: {c}18;
            border: 1px solid {c}28;
            border-radius: 5px;
            padding: 1px 7px;
            font-size: 10px;
            font-family: "Cascadia Mono", monospace;
        """)
        return lbl

    def _vline(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedWidth(1)
        f.setStyleSheet(f"background: {BORDER}; border: none;")
        return f

    def _hovered_bg(self):
        return "rgba(124,106,247,0.06)"

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 16, 16)

        if self.status == "active":
            bg = QColor(74, 222, 128, 10) if not self._hovered else QColor(74, 222, 128, 18)
        else:
            bg = QColor(255, 255, 255, 6 if not self._hovered else 10)

        p.fillPath(path, bg)

        border_color = QColor(ACCENT) if self._hovered and self.status == "active" else QColor(BORDER)
        p.setPen(QPen(border_color, 1))
        p.drawPath(path)


class EmptyState(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QColor(MUTED))
        p.setFont(QFont("Segoe UI Variable", 48))
        p.drawText(self.rect().adjusted(0, -40, 0, 0),
                   Qt.AlignmentFlag.AlignCenter, "⊞")
        p.setFont(QFont("Segoe UI Variable", 15))
        p.drawText(self.rect().adjusted(0, 60, 0, 0),
                   Qt.AlignmentFlag.AlignCenter, "No sessions yet")
        p.setFont(QFont("Segoe UI Variable", 11))
        p.setPen(QColor(MUTED2))
        p.drawText(self.rect().adjusted(0, 100, 0, 0),
                   Qt.AlignmentFlag.AlignCenter,
                   "Press  Ctrl + Win + D  to create a new virtual desktop\nand start tracking a session")


class MainWindow(QMainWindow):
    """
    Full WorkSpace Manager dashboard window.
    """
    def __init__(self):
        super().__init__()
        self._setup_window()
        self._build_ui()
        self.toast = ToastNotification()
        self.refresh()

    def _setup_window(self):
        self.setWindowTitle("WorkSpace Manager")
        self.setMinimumSize(900, 650)
        self.resize(1100, 750)
        self.setStyleSheet(f"QMainWindow {{ background: {BG}; }}")

    def _build_ui(self):
        central = QWidget()
        central.setStyleSheet(f"background: {BG};")
        self.setCentralWidget(central)

        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # ── Top bar ──
        main_layout.addWidget(self._build_topbar())

        # ── Content ──
        content = QWidget()
        content.setStyleSheet(f"background: {BG};")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(32, 28, 32, 28)
        cl.setSpacing(20)

        # Hero stats row
        cl.addWidget(self._build_hero())

        # Section label
        sec_lbl = QLabel("ACTIVE & RECENT SESSIONS")
        sec_lbl.setStyleSheet(f"""
            color: {MUTED};
            font-size: 10px;
            font-weight: 700;
            letter-spacing: 2.5px;
            font-family: "Cascadia Mono", monospace;
        """)
        cl.addWidget(sec_lbl)

        # Sessions grid (scrollable)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.grid_container = QWidget()
        self.grid_container.setStyleSheet("background: transparent;")
        self.grid_layout = QGridLayout(self.grid_container)
        self.grid_layout.setSpacing(14)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)

        scroll.setWidget(self.grid_container)
        cl.addWidget(scroll)

        main_layout.addWidget(content)

    def _build_topbar(self) -> QWidget:
        bar = QWidget()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"""
            background: {SURFACE};
            border-bottom: 1px solid {BORDER};
        """)
        hl = QHBoxLayout(bar)
        hl.setContentsMargins(24, 0, 24, 0)
        hl.setSpacing(12)

        # Logo
        logo = QLabel("⊞ WorkSpace")
        logo.setStyleSheet(f"""
            color: {TEXT};
            font-size: 15px;
            font-weight: 700;
            letter-spacing: -0.4px;
            font-family: "Segoe UI Variable";
        """)
        hl.addWidget(logo)

        # Version badge
        ver = QLabel("beta")
        ver.setStyleSheet(f"""
            color: {ACCENT2};
            background: {ACCENT_010};
            border: 1px solid {ACCENT}44;
            border-radius: 8px;
            padding: 1px 8px;
            font-size: 10px;
            font-weight: 700;
            font-family: "Cascadia Mono", monospace;
        """)
        hl.addWidget(ver)
        hl.addStretch()

        # Hotkey hints
        for key, hint in [("Ctrl+Win+D", "New Session"), ("Win+`", "Toggle HUD")]:
            k = QLabel(key)
            k.setStyleSheet(f"""
                color: {MUTED};
                background: rgba(255,255,255,0.05);
                border: 1px solid {BORDER};
                border-radius: 5px;
                padding: 2px 8px;
                font-size: 10px;
                font-family: "Cascadia Mono", monospace;
            """)
            h = QLabel(hint)
            h.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
            hl.addWidget(k)
            hl.addWidget(h)
            hl.addSpacing(12)

        # Refresh
        refresh_btn = QPushButton("⟳  Refresh")
        refresh_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1px solid {BORDER};
                color: {MUTED};
                border-radius: 8px;
                padding: 4px 14px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                border-color: {MUTED2};
                color: {TEXT};
                background: {WHITE_005};
            }}
        """)
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self.refresh)
        hl.addWidget(refresh_btn)

        return bar

    def _build_hero(self) -> QWidget:
        hero = QWidget()
        hl = QHBoxLayout(hero)
        hl.setContentsMargins(0, 0, 0, 0)
        hl.setSpacing(14)

        sessions = db.get_all_sessions()
        total = len(sessions)
        active = sum(1 for s in sessions if s["status"] == "active")
        total_time = sum(s.get("total_seconds", 0) for s in sessions)
        hours = total_time // 3600

        for val, label, color in [
            (str(total), "Total Sessions", ACCENT2),
            (str(active), "Active Now", GREEN),
            (f"{hours}h", "Total Time", AMBER),
        ]:
            card = self._stat_card(val, label, color)
            hl.addWidget(card)

        return hero

    def _stat_card(self, value: str, label: str, color: str) -> QWidget:
        card = QWidget()
        card.setFixedHeight(80)
        card.setStyleSheet(f"""
            background: {SURFACE};
            border: 1px solid {BORDER};
            border-radius: 14px;
        """)
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 12, 20, 12)
        cl.setSpacing(4)

        v = QLabel(value)
        v.setStyleSheet(f"""
            color: {color};
            font-size: 24px;
            font-weight: 700;
            font-family: "Segoe UI Variable";
            letter-spacing: -1px;
        """)
        cl.addWidget(v)

        l = QLabel(label)
        l.setStyleSheet(f"color: {MUTED}; font-size: 11px;")
        cl.addWidget(l)

        return card

    # ── Public API ────────────────────────────────────────────────────────────

    def refresh(self):
        """Reload all sessions and rebuild the grid."""
        sessions = db.get_all_sessions()

        # Clear grid
        while self.grid_layout.count():
            item = self.grid_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not sessions:
            empty = EmptyState()
            empty.setFixedHeight(300)
            self.grid_layout.addWidget(empty, 0, 0, 1, 2)
            return

        cols = 2
        for i, session in enumerate(sessions):
            stats = db.get_session_stats(session["id"])
            card = SessionFullCard(session, stats)
            card.restore_clicked.connect(self._on_restore)
            card.delete_clicked.connect(self._on_delete)
            self.grid_layout.addWidget(card, i // cols, i % cols)

        # Rebuild hero
        old_hero = self.centralWidget().layout().itemAt(1).widget().layout().itemAt(0).widget()
        if old_hero:
            old_hero.setParent(None)
        # Simple stats update via toast

    def show_toast(self, icon: str, msg: str):
        self.toast.show_toast(icon, msg)

    def _on_restore(self, session_id: int):
        session = db.get_session(session_id)
        if not session:
            return

        preview = restorer.get_restore_preview(session_id)
        if not preview:
            self.show_toast("ℹ️", "No saved state to restore yet.")
            return

        # Confirm dialog
        msg = QMessageBox(self)
        msg.setWindowTitle("Restore Session")
        msg.setText(f"Restore  \"{session['name']}\"?")
        msg.setInformativeText("\n".join(preview))
        msg.setStandardButtons(
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel
        )
        msg.setDefaultButton(QMessageBox.StandardButton.Ok)
        msg.button(QMessageBox.StandardButton.Ok).setText("↩  Restore")
        if msg.exec() == QMessageBox.StandardButton.Ok:
            result = restorer.restore_session(session_id)
            self.show_toast("↩", f"Restored {result['total']} item(s)")
            self.refresh()

    def _on_delete(self, session_id: int):
        session = db.get_session(session_id)
        if not session:
            return

        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Session")
        msg.setText(f"Delete  \"{session['name']}\"?")
        msg.setInformativeText("This cannot be undone.")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if msg.exec() == QMessageBox.StandardButton.Yes:
            db.delete_session(session_id)
            self.show_toast("🗑", f"\"{session['name']}\" deleted")
            self.refresh()

    def closeEvent(self, e):
        """Minimize to tray instead of closing."""
        e.ignore()
        self.hide()
        self.show_toast("⊞", "WorkSpace running in tray")
