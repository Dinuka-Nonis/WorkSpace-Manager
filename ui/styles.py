"""
ui/styles.py — Uiverse-inspired design system.
Light theme · Glassmorphism cards · Soft gradients · Rounded everything
"""

# ── Color Tokens ──────────────────────────────────────────────────────────────
BG           = "#f0f2ff"
GLASS        = "rgba(255,255,255,0.72)"
GLASS2       = "rgba(255,255,255,0.55)"
GLASS3       = "rgba(255,255,255,0.35)"
SURFACE      = "#ffffff"
SURFACE2     = "#f7f8ff"
SURFACE3     = "#eef0ff"
BORDER       = "rgba(120,100,255,0.15)"
BORDER2      = "rgba(120,100,255,0.08)"

ACCENT       = "#6c63ff"
ACCENT2      = "#a78bfa"
ACCENT3      = "#7c3aed"
ACCENT_LIGHT = "rgba(108,99,255,0.10)"
ACCENT_MED   = "rgba(108,99,255,0.20)"

GRAD_START   = "#6c63ff"
GRAD_END     = "#a78bfa"

TEXT         = "#1a1a2e"
TEXT2        = "#4a4a6a"
MUTED        = "#8888aa"
MUTED2       = "#bbbbcc"

GREEN        = "#10b981"
GREEN_BG     = "rgba(16,185,129,0.10)"
AMBER        = "#f59e0b"
AMBER_BG     = "rgba(245,158,11,0.10)"
RED          = "#ef4444"
RED_BG       = "rgba(239,68,68,0.10)"

SHADOW_SM    = "rgba(108,99,255,0.10)"
SHADOW_MD    = "rgba(108,99,255,0.18)"

# Legacy dark aliases kept so imports don't break
SURFACE_DARK = "#1a1a24"
BORDER_DARK  = "#2a2a3a"
WHITE_005    = "rgba(255,255,255,0.05)"
WHITE_008    = "rgba(255,255,255,0.08)"
ACCENT_010   = ACCENT_LIGHT
ACCENT_020   = ACCENT_MED
ACCENT_030   = "rgba(108,99,255,0.30)"
ACCENT_DIM   = ACCENT3

APP_STYLE = f"""
QWidget {{
    font-family: "Segoe UI Variable", "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
    color: {TEXT};
    background-color: transparent;
}}
QMainWindow {{ background-color: {BG}; }}
QDialog      {{ background-color: {BG}; }}

QScrollBar:vertical {{
    background: transparent; width: 5px;
    margin: 4px 2px; border-radius: 3px;
}}
QScrollBar::handle:vertical {{
    background: {ACCENT_MED}; border-radius: 3px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT}; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page:vertical,  QScrollBar::sub-page:vertical {{ background: transparent; }}

QLineEdit {{
    background: {GLASS};
    border: 1.5px solid {BORDER};
    border-radius: 10px;
    color: {TEXT};
    font-size: 13px;
    padding: 8px 12px;
    selection-background-color: {ACCENT_MED};
}}
QLineEdit:focus {{ border-color: {ACCENT}; background: {SURFACE}; }}
QLineEdit::placeholder {{ color: {MUTED}; }}

QPushButton {{
    background: {GLASS};
    border: 1.5px solid {BORDER};
    border-radius: 10px;
    color: {TEXT2};
    padding: 7px 18px;
    font-weight: 600;
    font-size: 13px;
}}
QPushButton:hover {{ background: {SURFACE}; border-color: {ACCENT}; color: {ACCENT}; }}
QPushButton:pressed {{ background: {ACCENT_LIGHT}; border-color: {ACCENT3}; color: {ACCENT3}; }}

QPushButton#accentBtn {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {GRAD_START}, stop:1 {GRAD_END});
    border: none; border-radius: 10px;
    color: white; font-weight: 700; font-size: 13px; padding: 9px 22px;
}}
QPushButton#accentBtn:hover {{
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 {ACCENT3}, stop:1 {ACCENT});
}}
QPushButton#accentBtn:pressed  {{ background: {ACCENT3}; }}
QPushButton#accentBtn:disabled {{ background: {MUTED2}; color: white; }}

QPushButton#ghostBtn {{
    background: transparent; border: 1.5px solid {BORDER};
    border-radius: 10px; color: {MUTED}; padding: 7px 18px; font-weight: 600;
}}
QPushButton#ghostBtn:hover {{ border-color: {ACCENT}; color: {ACCENT}; background: {ACCENT_LIGHT}; }}

QPushButton#dangerBtn {{
    background: {RED_BG}; border: 1.5px solid rgba(239,68,68,0.25);
    border-radius: 10px; color: {RED}; padding: 7px 16px; font-weight: 600;
}}
QPushButton#dangerBtn:hover {{ background: rgba(239,68,68,0.18); border-color: {RED}; }}

QLabel {{ color: {TEXT}; background: transparent; }}

QMenu {{
    background: {SURFACE}; border: 1.5px solid {BORDER};
    border-radius: 12px; padding: 6px;
}}
QMenu::item {{ padding: 8px 18px; border-radius: 8px; color: {TEXT2}; font-size: 13px; }}
QMenu::item:selected {{ background: {ACCENT_LIGHT}; color: {ACCENT}; }}
QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}

QToolTip {{
    background: {SURFACE}; border: 1px solid {BORDER};
    color: {TEXT2}; border-radius: 8px; padding: 5px 10px; font-size: 12px;
}}

QInputDialog, QMessageBox {{ background: {BG}; }}
QInputDialog QLabel, QMessageBox QLabel {{ color: {TEXT}; font-size: 13px; }}
QInputDialog QLineEdit {{
    background: {SURFACE}; border: 1.5px solid {BORDER};
    border-radius: 10px; padding: 8px 12px; color: {TEXT};
}}
"""
