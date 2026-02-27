"""
ui/add_item_dialog.py — Dialog to add a file, URL, or app to a session.

Three tabs: File, URL, App.
File   → drag & drop or browse button → stores absolute path.
URL    → paste field with live label preview.
App    → searchable list of installed Windows apps (from registry + Start Menu).
"""

import os
import threading
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QWidget, QFrame, QScrollArea,
    QApplication, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QPainter, QColor, QPainterPath, QFont, QDragEnterEvent, QDropEvent

import db
from core.launcher import (
    label_for_file, label_for_url, label_for_app, icon_for_item
)
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, BORDER, ACCENT, ACCENT2, ACCENT_DIM,
    TEXT, MUTED, MUTED2, RED, WHITE_005, ACCENT_010, ACCENT_020
)


# ── Tab button ────────────────────────────────────────────────────────────────

class TabButton(QPushButton):
    def __init__(self, label: str, parent=None):
        super().__init__(label, parent)
        self.setCheckable(True)
        self.setFixedHeight(34)
        self._update_style(False)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._update_style(checked)

    def _update_style(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {ACCENT_020};
                    border: 1px solid {ACCENT};
                    border-radius: 8px;
                    color: {ACCENT2};
                    font-weight: 700;
                    font-size: 13px;
                    padding: 0 18px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1px solid {BORDER};
                    border-radius: 8px;
                    color: {MUTED};
                    font-weight: 600;
                    font-size: 13px;
                    padding: 0 18px;
                }}
                QPushButton:hover {{
                    border-color: {MUTED2};
                    color: {TEXT};
                    background: {WHITE_005};
                }}
            """)


# ── Drop zone for files ───────────────────────────────────────────────────────

class DropZone(QWidget):
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(110)
        self._hovering = False
        self._path = ""

    def set_path(self, path: str):
        self._path = path
        self.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._hovering = True
            self.update()

    def dragLeaveEvent(self, e):
        self._hovering = False
        self.update()

    def dropEvent(self, e: QDropEvent):
        self._hovering = False
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            self.set_path(path)
            self.file_dropped.emit(path)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 12, 12)

        if self._hovering:
            p.fillPath(path, QColor(ACCENT_020))
            border_color = QColor(ACCENT)
        else:
            p.fillPath(path, QColor(SURFACE2))
            border_color = QColor(BORDER)

        from PyQt6.QtCore import Qt
        from PyQt6.QtGui import QPen
        pen = QPen(border_color, 1.5, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawPath(path)

        p.setPen(QColor(TEXT if self._path else MUTED))
        if self._path:
            p.setFont(QFont("Segoe UI Variable", 10))
            name = Path(self._path).name
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, f"📄  {name}")
        else:
            p.setFont(QFont("Segoe UI Variable", 12))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "Drop a file here")
            # subtext
            p.setFont(QFont("Segoe UI Variable", 10))
            p.setPen(QColor(MUTED2))
            from PyQt6.QtCore import QRect
            sub = QRect(0, self.height() // 2 + 10, self.width(), 24)
            p.drawText(sub, Qt.AlignmentFlag.AlignCenter, "or use the Browse button below")


# ── Label input with live preview ─────────────────────────────────────────────

def _make_field(placeholder: str, parent=None) -> QLineEdit:
    f = QLineEdit(parent)
    f.setPlaceholderText(placeholder)
    f.setStyleSheet(f"""
        QLineEdit {{
            background: {SURFACE2};
            border: 1px solid {BORDER};
            border-radius: 8px;
            color: {TEXT};
            font-size: 13px;
            padding: 8px 12px;
        }}
        QLineEdit:focus {{
            border-color: {ACCENT};
        }}
    """)
    return f


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setStyleSheet(f"color: {MUTED}; font-size: 11px; font-weight: 700; "
                      f"letter-spacing: 1.5px; text-transform: uppercase;")
    return lbl


# ── Main dialog ───────────────────────────────────────────────────────────────

class AddItemDialog(QDialog):
    item_added = pyqtSignal(int)   # emits the new item id

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._active_tab = "file"

        self.setWindowTitle("Add Item")
        self.setFixedSize(480, 460)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._selected_app = None

        self._build()

    def _build(self):
        # Outer container with rounded background
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._card = QWidget(self)
        self._card.setObjectName("card")
        self._card.setStyleSheet(f"""
            #card {{
                background: {SURFACE};
                border: 1px solid {BORDER};
                border-radius: 16px;
            }}
        """)
        outer.addWidget(self._card)

        layout = QVBoxLayout(self._card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(16)

        # ── Header ──
        header = QHBoxLayout()
        title = QLabel("Add to Session")
        title.setStyleSheet(f"color: {TEXT}; font-size: 16px; font-weight: 700;")
        header.addWidget(title)
        header.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none;
                color: {MUTED}; font-size: 14px; border-radius: 6px;
            }}
            QPushButton:hover {{ background: {WHITE_005}; color: {TEXT}; }}
        """)
        close_btn.clicked.connect(self.reject)
        header.addWidget(close_btn)
        layout.addLayout(header)

        # ── Tabs ──
        tabs = QHBoxLayout()
        tabs.setSpacing(8)
        self._tab_file = TabButton("📄  File")
        self._tab_url  = TabButton("🌐  URL")
        self._tab_app  = TabButton("⚙️  App")
        for btn in (self._tab_file, self._tab_url, self._tab_app):
            tabs.addWidget(btn)
        tabs.addStretch()
        self._tab_file.clicked.connect(lambda: self._switch_tab("file"))
        self._tab_url.clicked.connect(lambda:  self._switch_tab("url"))
        self._tab_app.clicked.connect(lambda:  self._switch_tab("app"))
        layout.addLayout(tabs)

        divider = QFrame()
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setStyleSheet(f"background: {BORDER}; max-height: 1px;")
        layout.addWidget(divider)

        # ── Tab pages (stacked manually) ──
        self._file_page = self._build_file_page()
        self._url_page  = self._build_url_page()
        self._app_page  = self._build_app_page()
        layout.addWidget(self._file_page)
        layout.addWidget(self._url_page)
        layout.addWidget(self._app_page)
        layout.addStretch()

        # ── Add button ──
        self._add_btn = QPushButton("Add to Session")
        self._add_btn.setObjectName("accentBtn")
        self._add_btn.setFixedHeight(40)
        self._add_btn.clicked.connect(self._on_add)
        layout.addWidget(self._add_btn)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet(f"color: {RED}; font-size: 12px;")
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._error_lbl)

        self._switch_tab("file")

    def _build_file_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self._drop_zone = DropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)
        layout.addWidget(self._drop_zone)

        browse_row = QHBoxLayout()
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedHeight(34)
        browse_btn.clicked.connect(self._browse_file)
        browse_row.addStretch()
        browse_row.addWidget(browse_btn)
        layout.addLayout(browse_row)

        layout.addWidget(_section("Label"))
        self._file_label = _make_field("Auto-generated from filename")
        layout.addWidget(self._file_label)

        return w

    def _build_url_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        layout.addWidget(_section("URL"))
        self._url_field = _make_field("https://...")
        self._url_field.textChanged.connect(self._on_url_changed)
        layout.addWidget(self._url_field)

        layout.addWidget(_section("Label"))
        self._url_label = _make_field("Auto-generated from URL")
        layout.addWidget(self._url_label)

        return w

    def _build_app_page(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        # Search bar
        self._app_search = _make_field("Search installed apps…")
        self._app_search.textChanged.connect(self._filter_apps)
        layout.addWidget(self._app_search)

        # Scrollable app list
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(160)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._app_list_widget = QWidget()
        self._app_list_widget.setStyleSheet("background: transparent;")
        self._app_list_layout = QVBoxLayout(self._app_list_widget)
        self._app_list_layout.setContentsMargins(0, 0, 0, 0)
        self._app_list_layout.setSpacing(2)
        self._app_list_layout.addStretch()
        scroll.setWidget(self._app_list_widget)
        layout.addWidget(scroll)

        # Loading label
        self._app_loading = QLabel("Loading installed apps…")
        self._app_loading.setStyleSheet(f"color: {MUTED}; font-size: 12px;")
        self._app_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._app_loading)

        # Selected app display
        self._selected_app: dict | None = None
        self._app_selected_lbl = QLabel("")
        self._app_selected_lbl.setStyleSheet(
            f"color: {ACCENT2}; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(self._app_selected_lbl)

        # Also allow manual browse as fallback
        browse_row = QHBoxLayout()
        browse_row.addStretch()
        fallback_btn = QPushButton("Browse .exe…")
        fallback_btn.setFixedHeight(28)
        fallback_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: 1px solid {BORDER};
                border-radius: 6px; color: {MUTED}; font-size: 11px;
                padding: 0 10px;
            }}
            QPushButton:hover {{ color: {TEXT}; border-color: {MUTED2}; }}
        """)
        fallback_btn.clicked.connect(self._browse_app_fallback)
        browse_row.addWidget(fallback_btn)
        layout.addLayout(browse_row)

        # Kick off background load
        self._all_apps: list[dict] = []
        threading.Thread(target=self._load_apps_bg, daemon=True).start()

        return w

    def _load_apps_bg(self):
        """Load installed apps in background thread, then populate UI."""
        try:
            from core.app_registry import get_installed_apps
            apps = get_installed_apps()
        except Exception:
            apps = []
        # Schedule UI update on main thread
        QTimer.singleShot(0, lambda: self._on_apps_loaded(apps))

    def _on_apps_loaded(self, apps: list[dict]):
        self._all_apps = apps
        self._app_loading.hide()
        self._populate_app_list(apps)

    def _filter_apps(self, query: str):
        if not self._all_apps:
            return
        q = query.lower().strip()
        filtered = [a for a in self._all_apps if q in a["name"].lower()] if q else self._all_apps
        self._populate_app_list(filtered[:50])  # cap at 50 for performance

    def _populate_app_list(self, apps: list[dict]):
        # Clear existing rows
        while self._app_list_layout.count() > 1:
            item = self._app_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for app in apps[:50]:
            row = self._make_app_row(app)
            self._app_list_layout.insertWidget(
                self._app_list_layout.count() - 1, row
            )

    def _make_app_row(self, app: dict) -> QWidget:
        row = QWidget()
        row.setFixedHeight(36)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(8, 4, 8, 4)
        row_layout.setSpacing(8)

        icon_lbl = QLabel(app.get("icon_emoji", "⚙️"))
        icon_lbl.setFixedSize(24, 24)
        icon_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_lbl.setStyleSheet("font-size: 14px;")
        row_layout.addWidget(icon_lbl)

        name_lbl = QLabel(app["name"])
        name_lbl.setStyleSheet(f"color: {TEXT}; font-size: 12px;")
        row_layout.addWidget(name_lbl)
        row_layout.addStretch()

        def _select(a=app, r=row):
            self._selected_app = a
            self._app_selected_lbl.setText(f"✓  {a['name']}")
            # Highlight selected row
            r.setStyleSheet(f"background: {ACCENT_020}; border-radius: 7px;")

        # Style default
        row.setStyleSheet(f"""
            QWidget {{ background: transparent; border-radius: 7px; }}
            QWidget:hover {{ background: {SURFACE3}; }}
        """)
        row.mousePressEvent = lambda e, fn=_select: fn()
        return row

    def _browse_app_fallback(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Application",
            r"C:\Program Files",
            "Executables (*.exe)"
        )
        if path:
            self._selected_app = {
                "name":       label_for_app(path),
                "exe_path":   path,
                "icon_emoji": "⚙️",
            }
            self._app_selected_lbl.setText(f"✓  {self._selected_app['name']}")

    def _switch_tab(self, tab: str):
        self._active_tab = tab
        self._tab_file.setChecked(tab == "file")
        self._tab_url.setChecked(tab == "url")
        self._tab_app.setChecked(tab == "app")
        self._file_page.setVisible(tab == "file")
        self._url_page.setVisible(tab == "url")
        self._app_page.setVisible(tab == "app")
        self._error_lbl.setText("")

    # ── File tab handlers ──

    def _on_file_dropped(self, path: str):
        if not self._file_label.text():
            self._file_label.setText(label_for_file(path))

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self._drop_zone.set_path(path)
            if not self._file_label.text():
                self._file_label.setText(label_for_file(path))

    # ── URL tab handlers ──

    def _on_url_changed(self, text: str):
        if text and not self._url_label.text():
            self._url_label.setText(label_for_url(text))

    # ── URL tab handlers ──

    def _on_url_changed(self, text: str):
        if text and not self._url_label.text():
            self._url_label.setText(label_for_url(text))

    # ── Add button ──

    def _on_add(self):
        self._error_lbl.setText("")

        if self._active_tab == "file":
            path = self._drop_zone._path
            if not path:
                self._error_lbl.setText("Please select a file first.")
                return
            if not os.path.exists(path):
                self._error_lbl.setText("File not found.")
                return
            label = self._file_label.text().strip() or label_for_file(path)
            item_id = db.add_item(self.session_id, "file", path, label)

        elif self._active_tab == "url":
            url = self._url_field.text().strip()
            if not url:
                self._error_lbl.setText("Please enter a URL.")
                return
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            label = self._url_label.text().strip() or label_for_url(url)
            item_id = db.add_item(self.session_id, "url", url, label)

        elif self._active_tab == "app":
            if not self._selected_app:
                self._error_lbl.setText("Please select an app first.")
                return
            exe_path = self._selected_app["exe_path"]
            label    = self._selected_app["name"]
            item_id  = db.add_item(self.session_id, "app", exe_path, label)

        self.item_added.emit(item_id)
        self.accept()

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()