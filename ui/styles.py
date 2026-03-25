"""
ui/styles.py — Premium design system.
Helvetica Bold · Floating glass cards · Large readable fonts · No emoji icons
"""

# ── Color Tokens ──────────────────────────────────────────────────────────────
BG           = "#F0F0ED"
GLASS        = "rgba(255,255,255,0.88)"
GLASS2       = "rgba(255,255,255,0.70)"
GLASS3       = "rgba(255,255,255,0.45)"
SURFACE      = "#FFFFFF"
SURFACE2     = "#F4F4F2"
SURFACE3     = "#EBEBEA"
BORDER       = "rgba(0,0,0,0.07)"
BORDER2      = "rgba(0,0,0,0.04)"

ACCENT       = "#111111"
ACCENT2      = "#2A2A2A"
ACCENT3      = "#3D3D3D"
ACCENT_LIGHT = "rgba(0,0,0,0.04)"
ACCENT_MED   = "rgba(0,0,0,0.08)"

GRAD_START   = "#111111"
GRAD_END     = "#333333"

TEXT         = "#0D0D0D"
TEXT2        = "#3A3A3A"
MUTED        = "#8A8A8A"
MUTED2       = "#C0C0C0"

GREEN        = "#2D7A52"
GREEN_BG     = "rgba(45,122,82,0.09)"
AMBER        = "#7A5A18"
AMBER_BG     = "rgba(122,90,24,0.09)"
RED          = "#8A1A1A"
RED_BG       = "rgba(138,26,26,0.07)"

SHADOW_SM    = "rgba(0,0,0,0.05)"
SHADOW_MD    = "rgba(0,0,0,0.09)"

# Legacy aliases
SURFACE_DARK = "#1a1a24"
BORDER_DARK  = "#2a2a3a"
WHITE_005    = "rgba(255,255,255,0.05)"
WHITE_008    = "rgba(255,255,255,0.08)"
ACCENT_010   = ACCENT_LIGHT
ACCENT_020   = ACCENT_MED
ACCENT_030   = "rgba(0,0,0,0.12)"
ACCENT_DIM   = ACCENT3

FONT_DISPLAY = "Helvetica Neue"
FONT_BODY    = "Helvetica Neue"

APP_STYLE = f"""
QWidget {{
    font-family: "Helvetica Neue", "Helvetica", "Arial", sans-serif;
    font-size: 15px;
    color: {TEXT};
    background-color: transparent;
}}
QMainWindow {{ background-color: {BG}; }}
QDialog      {{ background-color: {BG}; }}

QScrollBar:vertical {{
    background: transparent; width: 5px;
    margin: 6px 1px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: rgba(0,0,0,0.10); border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: rgba(0,0,0,0.20); }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical,  QScrollBar::sub-page:vertical {{ background: transparent; }}

QLineEdit {{
    background: {SURFACE};
    border: 1.5px solid {BORDER};
    border-radius: 14px;
    color: {TEXT};
    font-size: 16px;
    font-weight: 500;
    padding: 11px 16px;
    selection-background-color: rgba(0,0,0,0.10);
}}
QLineEdit:focus {{ border-color: rgba(0,0,0,0.22); background: {SURFACE}; }}

QPushButton {{
    background: {SURFACE};
    border: 1.5px solid {BORDER};
    border-radius: 12px;
    color: {TEXT2};
    padding: 9px 20px;
    font-weight: 600;
    font-size: 15px;
    font-family: "Helvetica Neue", "Helvetica", sans-serif;
}}
QPushButton:hover {{ background: {SURFACE2}; border-color: rgba(0,0,0,0.13); color: {TEXT}; }}
QPushButton:pressed {{ background: {SURFACE3}; }}

QPushButton#accentBtn {{
    background: {ACCENT};
    border: none;
    border-radius: 12px;
    color: white;
    font-weight: 700;
    font-size: 15px;
    padding: 11px 24px;
    font-family: "Helvetica Neue", "Helvetica", sans-serif;
}}
QPushButton#accentBtn:hover {{ background: {ACCENT2}; }}
QPushButton#accentBtn:pressed {{ background: {ACCENT3}; }}
QPushButton#accentBtn:disabled {{ background: {MUTED2}; color: white; }}

QPushButton#ghostBtn {{
    background: transparent;
    border: 1.5px solid {BORDER};
    border-radius: 12px;
    color: {MUTED};
    padding: 9px 20px;
    font-weight: 600;
}}
QPushButton#ghostBtn:hover {{ border-color: rgba(0,0,0,0.16); color: {TEXT2}; background: {SURFACE2}; }}

QPushButton#dangerBtn {{
    background: {RED_BG};
    border: 1.5px solid rgba(138,26,26,0.12);
    border-radius: 12px;
    color: {RED};
    padding: 9px 20px;
    font-weight: 600;
}}
QPushButton#dangerBtn:hover {{ background: rgba(138,26,26,0.11); border-color: rgba(138,26,26,0.22); }}

QLabel {{ color: {TEXT}; background: transparent; }}

QMenu {{
    background: {SURFACE};
    border: 1.5px solid {BORDER};
    border-radius: 14px;
    padding: 6px;
}}
QMenu::item {{ padding: 9px 18px; border-radius: 8px; color: {TEXT2}; font-size: 15px; }}
QMenu::item:selected {{ background: {SURFACE2}; color: {TEXT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 5px 8px; }}

QToolTip {{
    background: {SURFACE};
    border: 1.5px solid {BORDER};
    color: {TEXT2};
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 13px;
}}

QInputDialog, QMessageBox {{ background: {BG}; }}
QInputDialog QLabel, QMessageBox QLabel {{ color: {TEXT}; font-size: 15px; }}
QInputDialog QLineEdit {{
    background: {SURFACE};
    border: 1.5px solid {BORDER};
    border-radius: 14px;
    padding: 11px 16px;
    color: {TEXT};
    font-size: 16px;
}}
"""
