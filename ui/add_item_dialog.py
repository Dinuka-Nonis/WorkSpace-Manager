"""
ui/add_item_dialog.py — Dialog to add a file, URL, or app to a session.

Three tabs: File, URL, App.
File   → drag & drop or browse button → stores absolute path.
URL    → paste field with live label preview.
App    → browse to .exe → stores absolute path.
"""

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QWidget, QFrame, QApplication
)
from PyQt6.QtCore import Qt, pyqtSignal, QMimeData
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
        self.setFixedSize(480, 400)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

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
        layout.setSpacing(10)

        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self._app_path = _make_field("Path to .exe")
        self._app_path.setReadOnly(True)
        path_row.addWidget(self._app_path)
        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(90)
        browse_btn.setFixedHeight(38)
        browse_btn.clicked.connect(self._browse_app)
        path_row.addWidget(browse_btn)
        layout.addLayout(path_row)

        layout.addWidget(_section("Label"))
        self._app_label = _make_field("Auto-generated from filename")
        layout.addWidget(self._app_label)

        return w

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

    # ── App tab handlers ──

    def _browse_app(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Application",
            r"C:\Program Files",
            "Executables (*.exe)"
        )
        if path:
            self._app_path.setText(path)
            if not self._app_label.text():
                self._app_label.setText(label_for_app(path))

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
            path = self._app_path.text().strip()
            if not path:
                self._error_lbl.setText("Please select an executable.")
                return
            if not os.path.exists(path):
                self._error_lbl.setText("Executable not found.")
                return
            label = self._app_label.text().strip() or label_for_app(path)
            item_id = db.add_item(self.session_id, "app", path, label)

        self.item_added.emit(item_id)
        self.accept()

    def mousePressEvent(self, e):
        self._drag_pos = e.globalPosition().toPoint()

    def mouseMoveEvent(self, e):
        if e.buttons() == Qt.MouseButton.LeftButton:
            self.move(self.pos() + e.globalPosition().toPoint() - self._drag_pos)
            self._drag_pos = e.globalPosition().toPoint()