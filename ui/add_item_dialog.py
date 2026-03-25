"""
ui/add_item_dialog.py — Add file, URL, or app to a session.
Premium redesign: Helvetica Bold · Large fonts · No emoji · Pill tabs ·
Full-size floating card dialog.
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QWidget, QFrame, QScrollArea,
    QApplication, QGraphicsDropShadowEffect
)
from PyQt6.QtCore import Qt, pyqtSignal, QThread, QObject
from PyQt6.QtGui import (
    QPainter, QColor, QPainterPath, QFont, QLinearGradient,
    QPen, QDragEnterEvent, QDropEvent
)

import db
from core.launcher import label_for_file, label_for_url, label_for_app
from ui.styles import (
    BG, SURFACE, SURFACE2, SURFACE3, GLASS, BORDER,
    ACCENT, ACCENT2, ACCENT3, ACCENT_LIGHT, ACCENT_MED,
    GRAD_START, GRAD_END, TEXT, TEXT2, MUTED, MUTED2,
    GREEN, RED, RED_BG, SHADOW_SM, SHADOW_MD,
    FONT_DISPLAY, FONT_BODY
)

# Geometric symbols
ICON_FILE = "▭"
ICON_WEB  = "○"
ICON_APP  = "◈"


# ── App loader worker ─────────────────────────────────────────────────────────

class AppLoaderWorker(QObject):
    apps_loaded = pyqtSignal(list)
    error       = pyqtSignal(str)

    def run(self):
        try:
            from core.app_registry import get_installed_apps
            apps = get_installed_apps()
            self.apps_loaded.emit(apps)
        except Exception as e:
            import traceback
            print(f"[AppLoader] ERROR:\n{traceback.format_exc()}")
            self.error.emit(str(e))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _field(placeholder: str) -> QLineEdit:
    f = QLineEdit()
    f.setPlaceholderText(placeholder)
    f.setFont(QFont(FONT_BODY, 15))
    f.setStyleSheet(f"""
        QLineEdit {{
            background: {SURFACE2};
            border: 1.5px solid rgba(0,0,0,0.07);
            border-radius: 14px;
            color: {TEXT};
            font-size: 15px;
            font-weight: 500;
            padding: 11px 16px;
        }}
        QLineEdit:focus {{
            border-color: rgba(0,0,0,0.22);
            background: {SURFACE};
        }}
    """)
    return f


def _section_lbl(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont(FONT_BODY, 10, QFont.Weight.Bold))
    lbl.setStyleSheet(
        f"color: {MUTED}; letter-spacing: 1.8px;"
    )
    return lbl


# ── Tab button — pill style ───────────────────────────────────────────────────

class TabBtn(QPushButton):
    def __init__(self, icon_sym: str, label: str, parent=None):
        super().__init__(f"{icon_sym}  {label}", parent)
        self._icon_sym = icon_sym
        self._label    = label
        self.setCheckable(True)
        self.setFixedHeight(40)
        self.setMinimumWidth(110)
        self.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
        self._update(False)

    def setChecked(self, v: bool):
        super().setChecked(v)
        self._update(v)

    def _update(self, active: bool):
        if active:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: {ACCENT};
                    border: none;
                    border-radius: 20px;
                    color: white;
                    font-weight: 700;
                    font-size: 14px;
                    padding: 0 18px;
                }}
            """)
        else:
            self.setStyleSheet(f"""
                QPushButton {{
                    background: transparent;
                    border: 1.5px solid rgba(0,0,0,0.08);
                    border-radius: 20px;
                    color: {MUTED};
                    font-weight: 600;
                    font-size: 14px;
                    padding: 0 18px;
                }}
                QPushButton:hover {{
                    border-color: rgba(0,0,0,0.16);
                    color: {TEXT2};
                    background: {SURFACE2};
                }}
            """)


# ── Drop zone ─────────────────────────────────────────────────────────────────

class DropZone(QWidget):
    file_dropped = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setFixedHeight(108)
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
        path.addRoundedRect(0, 0, self.width(), self.height(), 16, 16)

        if self._hovering:
            p.fillPath(path, QColor(0, 0, 0, 28))
            pen = QPen(QColor(0, 0, 0, 80), 1.5, Qt.PenStyle.DashLine)
        else:
            p.fillPath(path, QColor(SURFACE2))
            pen = QPen(QColor(0, 0, 0, 35), 1.5, Qt.PenStyle.DashLine)

        p.setPen(pen)
        p.drawPath(path)

        from PyQt6.QtCore import QRect
        if self._path:
            p.setPen(QColor(TEXT))
            p.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                       f"{ICON_FILE}  {Path(self._path).name}")
        else:
            p.setPen(QColor(MUTED))
            p.setFont(QFont(FONT_DISPLAY, 14, QFont.Weight.Bold))
            p.drawText(
                QRect(0, 16, self.width(), 30),
                Qt.AlignmentFlag.AlignCenter, "Drop a file here"
            )
            p.setFont(QFont(FONT_BODY, 13))
            p.drawText(
                QRect(0, 50, self.width(), 28),
                Qt.AlignmentFlag.AlignCenter, "or use the Browse button below"
            )


# ── Main dialog ───────────────────────────────────────────────────────────────

class AddItemDialog(QDialog):
    item_added = pyqtSignal(int)

    def __init__(self, session_id: int, parent=None):
        super().__init__(parent)
        self.session_id = session_id
        self._active_tab = "file"
        self._selected_app: dict | None = None
        self._all_apps: list[dict] = []

        self.setWindowTitle("Add Item")
        self.setFixedSize(520, 520)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(12, 12, 12, 12)

        card = QWidget()
        card.setObjectName("dialogCard")
        card.setStyleSheet(f"""
            #dialogCard {{
                background: {SURFACE};
                border: 1.5px solid rgba(0,0,0,0.07);
                border-radius: 24px;
            }}
        """)
        fx = QGraphicsDropShadowEffect(card)
        fx.setBlurRadius(50)
        fx.setColor(QColor(0, 0, 0, 60))
        fx.setOffset(0, 12)
        card.setGraphicsEffect(fx)
        outer.addWidget(card)

        layout = QVBoxLayout(card)
        layout.setContentsMargins(30, 28, 30, 28)
        layout.setSpacing(20)

        # Header
        header_row = QHBoxLayout()
        title = QLabel("Add to Session")
        title.setFont(QFont(FONT_DISPLAY, 20, QFont.Weight.Black))
        title.setStyleSheet(f"color: {TEXT}; letter-spacing: -0.3px;")
        header_row.addWidget(title)
        header_row.addStretch()
        close_btn = QPushButton("×")
        close_btn.setFixedSize(36, 36)
        close_btn.setFont(QFont(FONT_BODY, 20, QFont.Weight.Light))
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE2};
                border: none;
                color: {MUTED};
                border-radius: 12px;
            }}
            QPushButton:hover {{ background: {RED_BG}; color: {RED}; }}
        """)
        close_btn.clicked.connect(self.reject)
        header_row.addWidget(close_btn)
        layout.addLayout(header_row)

        # Pill tabs
        tabs_row = QHBoxLayout()
        tabs_row.setSpacing(8)
        self._tab_file = TabBtn(ICON_FILE, "File")
        self._tab_url  = TabBtn(ICON_WEB,  "Website")
        self._tab_app  = TabBtn(ICON_APP,  "App")
        for btn in (self._tab_file, self._tab_url, self._tab_app):
            tabs_row.addWidget(btn)
        tabs_row.addStretch()
        self._tab_file.clicked.connect(lambda: self._switch("file"))
        self._tab_url.clicked.connect(lambda:  self._switch("url"))
        self._tab_app.clicked.connect(lambda:  self._switch("app"))
        layout.addLayout(tabs_row)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.HLine)
        div.setStyleSheet(f"background: rgba(0,0,0,0.06); max-height: 1px;")
        layout.addWidget(div)

        # Pages
        self._file_page = self._build_file_page()
        self._url_page  = self._build_url_page()
        self._app_page  = self._build_app_page()
        for pg in (self._file_page, self._url_page, self._app_page):
            layout.addWidget(pg)
        layout.addStretch()

        # Add button
        self._add_btn = QPushButton("Add to Session")
        self._add_btn.setObjectName("accentBtn")
        self._add_btn.setFixedHeight(48)
        self._add_btn.setFont(QFont(FONT_DISPLAY, 15, QFont.Weight.Bold))
        self._add_btn.clicked.connect(self._on_add)
        layout.addWidget(self._add_btn)

        self._error_lbl = QLabel("")
        self._error_lbl.setFont(QFont(FONT_BODY, 13, QFont.Weight.Bold))
        self._error_lbl.setStyleSheet(f"color: {RED};")
        self._error_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._error_lbl)

        self._switch("file")

    # ── Pages ──

    def _build_file_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)

        self._drop_zone = DropZone()
        self._drop_zone.file_dropped.connect(self._on_file_dropped)
        v.addWidget(self._drop_zone)

        row = QHBoxLayout()
        browse = QPushButton("Browse…")
        browse.setFixedHeight(36)
        browse.setMinimumWidth(100)
        browse.setFont(QFont(FONT_BODY, 13, QFont.Weight.Bold))
        browse.setStyleSheet(f"""
            QPushButton {{
                background: {SURFACE2};
                border: 1.5px solid rgba(0,0,0,0.07);
                border-radius: 18px;
                color: {TEXT2};
                padding: 0 16px;
            }}
            QPushButton:hover {{ background: {SURFACE3}; }}
        """)
        browse.clicked.connect(self._browse_file)
        row.addStretch()
        row.addWidget(browse)
        v.addLayout(row)

        v.addWidget(_section_lbl("LABEL"))
        self._file_label = _field("Auto-generated from filename")
        v.addWidget(self._file_label)
        return w

    def _build_url_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        v.addWidget(_section_lbl("URL"))
        self._url_field = _field("https://...")
        self._url_field.textChanged.connect(self._on_url_changed)
        v.addWidget(self._url_field)
        v.addWidget(_section_lbl("LABEL"))
        self._url_label = _field("Auto-generated from URL")
        v.addWidget(self._url_label)
        return w

    def _build_app_page(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)

        self._app_search = _field("Search installed apps…")
        self._app_search.textChanged.connect(self._filter_apps)
        v.addWidget(self._app_search)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(170)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("background: transparent;")

        self._app_list_widget = QWidget()
        self._app_list_widget.setStyleSheet("background: transparent;")
        self._app_list_layout = QVBoxLayout(self._app_list_widget)
        self._app_list_layout.setContentsMargins(0, 0, 0, 0)
        self._app_list_layout.setSpacing(2)
        self._app_list_layout.addStretch()
        scroll.setWidget(self._app_list_widget)
        v.addWidget(scroll)

        self._app_loading = QLabel("Loading installed apps…")
        self._app_loading.setFont(QFont(FONT_BODY, 13))
        self._app_loading.setStyleSheet(f"color: {MUTED}; font-style: italic;")
        self._app_loading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(self._app_loading)

        self._app_selected_lbl = QLabel("")
        self._app_selected_lbl.setFont(QFont(FONT_DISPLAY, 13, QFont.Weight.Bold))
        self._app_selected_lbl.setStyleSheet(f"color: {ACCENT};")
        v.addWidget(self._app_selected_lbl)

        fallback_row = QHBoxLayout()
        fallback_row.addStretch()
        fb = QPushButton("Browse .exe…")
        fb.setFixedHeight(32)
        fb.setMinimumWidth(110)
        fb.setFont(QFont(FONT_BODY, 12, QFont.Weight.Bold))
        fb.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                border: 1.5px solid rgba(0,0,0,0.08);
                border-radius: 16px;
                color: {MUTED};
                padding: 0 14px;
            }}
            QPushButton:hover {{ color: {TEXT}; border-color: rgba(0,0,0,0.18); }}
        """)
        fb.clicked.connect(self._browse_app_fallback)
        fallback_row.addWidget(fb)
        v.addLayout(fallback_row)

        self._app_thread = QThread()
        self._app_worker = AppLoaderWorker()
        self._app_worker.moveToThread(self._app_thread)
        self._app_thread.started.connect(self._app_worker.run)
        self._app_worker.apps_loaded.connect(self._on_apps_loaded)
        self._app_worker.apps_loaded.connect(self._app_thread.quit)
        self._app_worker.error.connect(self._on_apps_error)
        self._app_worker.error.connect(self._app_thread.quit)
        self._app_thread.start()

        return w

    # ── App loading ──

    def _on_apps_loaded(self, apps: list[dict]):
        self._all_apps = apps
        self._app_loading.hide()
        self._populate_app_list(apps)

    def _on_apps_error(self, msg: str):
        self._app_loading.setText("Could not load apps — use Browse .exe…")
        self._app_loading.setStyleSheet(f"color: {MUTED}; font-size: 13px;")

    def _filter_apps(self, query: str):
        if not self._all_apps:
            return
        q = query.lower().strip()
        filtered = [a for a in self._all_apps if q in a["name"].lower()] if q else self._all_apps
        self._populate_app_list(filtered[:60])

    def _populate_app_list(self, apps: list[dict]):
        while self._app_list_layout.count() > 1:
            item = self._app_list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, app in enumerate(apps[:60]):
            row = self._make_app_row(app)
            self._app_list_layout.insertWidget(i, row)

    def _make_app_row(self, app: dict) -> QWidget:
        row = QWidget()
        row.setFixedHeight(42)
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.setStyleSheet(f"""
            QWidget {{ background: transparent; border-radius: 12px; }}
            QWidget:hover {{ background: {SURFACE2}; }}
        """)
        rl = QHBoxLayout(row)
        rl.setContentsMargins(10, 4, 10, 4)
        rl.setSpacing(12)

        icon_box = QWidget()
        icon_box.setFixedSize(30, 30)
        icon_box.setStyleSheet(f"""
            background: {SURFACE3};
            border-radius: 8px;
        """)
        il = QHBoxLayout(icon_box)
        il.setContentsMargins(0, 0, 0, 0)
        sym = QLabel(ICON_APP)
        sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sym.setFont(QFont(FONT_BODY, 11))
        sym.setStyleSheet(f"color: {TEXT2}; background: transparent;")
        il.addWidget(sym)
        rl.addWidget(icon_box)

        name_lbl = QLabel(app["name"])
        name_lbl.setFont(QFont(FONT_BODY, 14, QFont.Weight.Medium))
        name_lbl.setStyleSheet(f"color: {TEXT};")
        rl.addWidget(name_lbl)
        rl.addStretch()

        def _select(a=app, r=row):
            self._selected_app = a
            self._app_selected_lbl.setText(f"Selected: {a['name']}")
            r.setStyleSheet(f"""
                QWidget {{
                    background: rgba(0,0,0,0.05);
                    border: 1.5px solid rgba(0,0,0,0.10);
                    border-radius: 12px;
                }}
            """)

        row.mousePressEvent = lambda e, fn=_select: fn()
        return row

    def _browse_app_fallback(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Application", r"C:\Program Files", "Executables (*.exe)"
        )
        if path:
            self._selected_app = {
                "name": label_for_app(path), "exe_path": path
            }
            self._app_selected_lbl.setText(f"Selected: {self._selected_app['name']}")

    # ── File / URL handlers ──

    def _on_file_dropped(self, path: str):
        if not self._file_label.text():
            self._file_label.setText(label_for_file(path))

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            self._drop_zone.set_path(path)
            if not self._file_label.text():
                self._file_label.setText(label_for_file(path))

    def _on_url_changed(self, text: str):
        if text and not self._url_label.text():
            self._url_label.setText(label_for_url(text))

    # ── Tab switching ──

    def _switch(self, tab: str):
        self._active_tab = tab
        self._tab_file.setChecked(tab == "file")
        self._tab_url.setChecked(tab == "url")
        self._tab_app.setChecked(tab == "app")
        self._file_page.setVisible(tab == "file")
        self._url_page.setVisible(tab == "url")
        self._app_page.setVisible(tab == "app")
        self._error_lbl.setText("")

    # ── Add ──

    def _on_add(self):
        self._error_lbl.setText("")

        if self._active_tab == "file":
            path = self._drop_zone._path
            if not path:
                self._error_lbl.setText("Please select or drop a file first.")
                return
            if not os.path.exists(path):
                self._error_lbl.setText("File not found on disk.")
                return
            label   = self._file_label.text().strip() or label_for_file(path)
            item_id = db.add_item(self.session_id, "file", path, label)

        elif self._active_tab == "url":
            url = self._url_field.text().strip()
            if not url:
                self._error_lbl.setText("Please enter a URL.")
                return
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            label   = self._url_label.text().strip() or label_for_url(url)
            item_id = db.add_item(self.session_id, "url", url, label)

        elif self._active_tab == "app":
            if not self._selected_app:
                self._error_lbl.setText("Please select an app first.")
                return
            item_id = db.add_item(
                self.session_id, "app",
                self._selected_app["exe_path"],
                self._selected_app["name"]
            )

        self.item_added.emit(item_id)
        self.accept()

    # ── Window drag ──

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()

    def closeEvent(self, e):
        if hasattr(self, "_app_thread") and self._app_thread.isRunning():
            self._app_thread.quit()
            self._app_thread.wait(1000)
        super().closeEvent(e)
