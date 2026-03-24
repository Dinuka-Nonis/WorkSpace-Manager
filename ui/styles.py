"""
ui/styles.py — Minimal design system.
Near-neutral palette · Clean type · Animated sidebar indicator
"""

# ── Color Tokens ──────────────────────────────────────────────────────────────
BG           = "#F7F7F5"
GLASS        = "rgba(255,255,255,0.85)"
GLASS2       = "rgba(255,255,255,0.65)"
GLASS3       = "rgba(255,255,255,0.40)"
SURFACE      = "#FFFFFF"
SURFACE2     = "#F2F2F0"
SURFACE3     = "#EAEAE8"
BORDER       = "rgba(0,0,0,0.08)"
BORDER2      = "rgba(0,0,0,0.05)"

ACCENT       = "#1A1A1A"
ACCENT2      = "#3D3D3D"
ACCENT3      = "#5A5A5A"
ACCENT_LIGHT = "rgba(0,0,0,0.05)"
ACCENT_MED   = "rgba(0,0,0,0.09)"

GRAD_START   = "#1A1A1A"
GRAD_END     = "#3D3D3D"

TEXT         = "#111111"
TEXT2        = "#444444"
MUTED        = "#999999"
MUTED2       = "#C8C8C8"

GREEN        = "#3A7A5A"
GREEN_BG     = "rgba(58,122,90,0.08)"
AMBER        = "#8A6A20"
AMBER_BG     = "rgba(138,106,32,0.08)"
RED          = "#8A2020"
RED_BG       = "rgba(138,32,32,0.07)"

SHADOW_SM    = "rgba(0,0,0,0.06)"
SHADOW_MD    = "rgba(0,0,0,0.10)"

# Legacy aliases
SURFACE_DARK = "#1a1a24"
BORDER_DARK  = "#2a2a3a"
WHITE_005    = "rgba(255,255,255,0.05)"
WHITE_008    = "rgba(255,255,255,0.08)"
ACCENT_010   = ACCENT_LIGHT
ACCENT_020   = ACCENT_MED
ACCENT_030   = "rgba(0,0,0,0.12)"
ACCENT_DIM   = ACCENT3

APP_STYLE = f"""
QWidget {{
    font-family: "Segoe UI Variable", "Segoe UI", "SF Pro Display", sans-serif;
    font-size: 13px;
    color: {TEXT};
    background-color: transparent;
}}
QMainWindow {{ background-color: {BG}; }}
QDialog      {{ background-color: {BG}; }}

QScrollBar:vertical {{
    background: transparent; width: 4px;
    margin: 4px 1px; border-radius: 2px;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,0,0,0.12); border-radius: 2px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(0,0,0,0.22); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical,  QScrollBar::sub-page:vertical {{ background: transparent; }}

QLineEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT};
    font-size: 13px;
    padding: 8px 12px;
    selection-background-color: rgba(0,0,0,0.12);
}}
QLineEdit:focus {{ border-color: rgba(0,0,0,0.25); background: {SURFACE}; }}
QLineEdit::placeholder {{ color: {MUTED}; }}

QPushButton {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {TEXT2};
    padding: 7px 16px;
    font-weight: 500;
    font-size: 13px;
}}
QPushButton:hover {{ background: {SURFACE2}; border-color: rgba(0,0,0,0.14); color: {TEXT}; }}
QPushButton:pressed {{ background: {SURFACE3}; }}

QPushButton#accentBtn {{
    background: {ACCENT};
    border: none;
    border-radius: 8px;
    color: white;
    font-weight: 600;
    font-size: 13px;
    padding: 9px 20px;
}}
QPushButton#accentBtn:hover {{ background: {ACCENT2}; }}
QPushButton#accentBtn:pressed {{ background: {ACCENT3}; }}
QPushButton#accentBtn:disabled {{ background: {MUTED2}; color: white; }}

QPushButton#ghostBtn {{
    background: transparent;
    border: 1px solid {BORDER};
    border-radius: 8px;
    color: {MUTED};
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton#ghostBtn:hover {{ border-color: rgba(0,0,0,0.18); color: {TEXT2}; background: {SURFACE2}; }}

QPushButton#dangerBtn {{
    background: {RED_BG};
    border: 1px solid rgba(138,32,32,0.15);
    border-radius: 8px;
    color: {RED};
    padding: 7px 16px;
    font-weight: 500;
}}
QPushButton#dangerBtn:hover {{ background: rgba(138,32,32,0.12); border-color: rgba(138,32,32,0.25); }}

QLabel {{ color: {TEXT}; background: transparent; }}

QMenu {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 5px;
}}
QMenu::item {{ padding: 7px 16px; border-radius: 6px; color: {TEXT2}; font-size: 13px; }}
QMenu::item:selected {{ background: {SURFACE2}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 6px; }}

QToolTip {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    color: {TEXT2};
    border-radius: 6px;
    padding: 4px 9px;
    font-size: 12px;
}}

QInputDialog, QMessageBox {{ background: {BG}; }}
QInputDialog QLabel, QMessageBox QLabel {{ color: {TEXT}; font-size: 13px; }}
QInputDialog QLineEdit {{
    background: {SURFACE};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    color: {TEXT};
}}
"""
