"""
ui/styles.py — Global PyQt6 QSS stylesheet and color tokens.
Dark theme matching the WorkSpace mockup palette.
"""

# ── Color Tokens ──────────────────────────────────────────────────────────────
BG          = "#0a0a0f"
SURFACE     = "#111118"
SURFACE2    = "#1a1a24"
SURFACE3    = "#22222f"
BORDER      = "#2a2a3a"
BORDER2     = "#1e1e2e"
ACCENT      = "#7c6af7"
ACCENT2     = "#a78bfa"
ACCENT_DIM  = "#4a3d99"
TEXT        = "#e8e8f0"
MUTED       = "#6b6b80"
MUTED2      = "#4a4a5a"
GREEN       = "#4ade80"
AMBER       = "#fbbf24"
RED         = "#f87171"
WHITE_005   = "rgba(255,255,255,0.05)"
WHITE_008   = "rgba(255,255,255,0.08)"
WHITE_012   = "rgba(255,255,255,0.12)"
ACCENT_010  = "rgba(124,106,247,0.10)"
ACCENT_020  = "rgba(124,106,247,0.20)"
ACCENT_030  = "rgba(124,106,247,0.30)"


APP_STYLE = f"""
/* ── Global ── */
QWidget {{
    font-family: "Segoe UI Variable", "Segoe UI", "SF Pro Display", sans-serif;
    font-size: 13px;
    color: {TEXT};
    background-color: transparent;
}}

QMainWindow, QDialog {{
    background-color: {BG};
}}

/* ── Scrollbar ── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 4px 2px;
    border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 3px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {MUTED2};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{ background: transparent; }}

/* ── QLineEdit ── */
QLineEdit {{
    background: transparent;
    border: none;
    color: {TEXT};
    font-size: 17px;
    font-weight: 500;
    padding: 0;
    selection-background-color: {ACCENT_030};
}}
QLineEdit::placeholder {{
    color: {MUTED};
}}

/* ── QPushButton (default) ── */
QPushButton {{
    background: {SURFACE2};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT};
    padding: 7px 16px;
    font-weight: 600;
}}
QPushButton:hover {{
    background: {SURFACE3};
    border-color: {MUTED2};
}}
QPushButton:pressed {{
    background: {ACCENT_010};
    border-color: {ACCENT};
    color: {ACCENT2};
}}

/* ── Accent Button ── */
QPushButton#accentBtn {{
    background: {ACCENT};
    border: none;
    color: white;
    font-weight: 700;
    border-radius: 10px;
    padding: 9px 22px;
}}
QPushButton#accentBtn:hover {{
    background: {ACCENT2};
}}
QPushButton#accentBtn:pressed {{
    background: {ACCENT_DIM};
}}

/* ── Danger Button ── */
QPushButton#dangerBtn {{
    background: rgba(248,113,113,0.12);
    border: 1px solid rgba(248,113,113,0.25);
    color: {RED};
    border-radius: 8px;
    padding: 5px 12px;
    font-weight: 600;
}}
QPushButton#dangerBtn:hover {{
    background: rgba(248,113,113,0.22);
    border-color: {RED};
}}

/* ── Ghost Button ── */
QPushButton#ghostBtn {{
    background: transparent;
    border: 1px solid {BORDER};
    color: {MUTED};
    border-radius: 8px;
    padding: 7px 16px;
}}
QPushButton#ghostBtn:hover {{
    border-color: {MUTED2};
    color: {TEXT};
    background: {WHITE_005};
}}

/* ── QLabel ── */
QLabel {{
    color: {TEXT};
    background: transparent;
}}
QLabel#mutedLabel {{
    color: {MUTED};
    font-size: 12px;
}}
QLabel#titleLabel {{
    font-size: 15px;
    font-weight: 700;
    color: {TEXT};
    letter-spacing: -0.3px;
}}
QLabel#sectionLabel {{
    font-size: 10px;
    font-weight: 700;
    color: {MUTED};
    letter-spacing: 2px;
    text-transform: uppercase;
}}
QLabel#accentLabel {{
    color: {ACCENT2};
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
}}

/* ── QFrame divider ── */
QFrame#divider {{
    background: {BORDER};
    max-height: 1px;
}}

/* ── QMenu ── */
QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 18px;
    border-radius: 6px;
    color: {TEXT};
    font-size: 13px;
}}
QMenu::item:selected {{
    background: {ACCENT_010};
    color: {ACCENT2};
}}
QMenu::separator {{
    height: 1px;
    background: {BORDER};
    margin: 4px 8px;
}}

/* ── QSystemTrayIcon (no style needed directly) ── */

/* ── QToolTip ── */
QToolTip {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    color: {TEXT};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 12px;
}}
"""
