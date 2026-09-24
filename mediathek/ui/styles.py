"""
Stylesheet-Erzeugung mit einstellbarer Akzentfarbe.

build_stylesheet(accent) erzeugt das komplette QSS mit der gewuenschten
Akzentfarbe (Standard: #4f7cff, blau) an allen relevanten Stellen --
Buttons, Fokus-Rahmen, Scrollbar, Dropdown-Auswahl, Fortschrittsbalken usw.
Hellere/dunklere Varianten (Hover/Pressed) werden automatisch daraus
abgeleitet, damit man nicht jede einzeln pflegen muss.
"""
from __future__ import annotations

DEFAULT_ACCENT = "#4f7cff"


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(rgb: tuple[float, float, float]) -> str:
    r, g, b = (max(0, min(255, round(c))) for c in rgb)
    return f"#{r:02x}{g:02x}{b:02x}"


def _lighten(hex_color: str, amount: float) -> str:
    r, g, b = _hex_to_rgb(hex_color)
    return _rgb_to_hex((r + (255 - r) * amount, g + (255 - g) * amount, b + (255 - b) * amount))


def _mix(hex_color: str, with_hex: str, amount: float) -> str:
    """Mischt hex_color zu 'amount' Anteilen mit with_hex (Rest = with_hex)."""
    r1, g1, b1 = _hex_to_rgb(hex_color)
    r2, g2, b2 = _hex_to_rgb(with_hex)
    return _rgb_to_hex((
        r1 * amount + r2 * (1 - amount),
        g1 * amount + g2 * (1 - amount),
        b1 * amount + b2 * (1 - amount),
    ))


def build_stylesheet(accent: str = DEFAULT_ACCENT) -> str:
    a = accent
    a_hover = _lighten(a, 0.15)
    a_pressed = _lighten(a, 0.30)
    # Scrollbar im Ruhezustand: gedaempfte (aber erkennbar farbige statt grau
    # wirkende) Variante der Akzentfarbe, damit sie nicht schon in Ruhe so
    # grell wie im Hover-Zustand ist.
    scrollbar_idle = _mix(a, "#2f3340", 0.55)

    return f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
}}
QMainWindow, QDialog {{
    background-color: #14161c;
    color: #e8e8ec;
}}
QWidget#topBar {{
    background-color: #1b1e27;
    border-bottom: 1px solid #2a2e3a;
}}
QLabel#appTitle {{
    font-size: 18px;
    font-weight: 600;
    color: #ffffff;
    padding: 4px 8px;
}}
QLabel#statusLabel {{
    color: #9aa0ac;
    font-size: 12px;
}}
QLineEdit {{
    background-color: #21242e;
    border: 1px solid #2f3340;
    border-radius: 8px;
    padding: 7px 12px;
    color: #e8e8ec;
    selection-background-color: {a};
}}
QLineEdit:focus {{
    border: 1px solid {a};
}}
QComboBox {{
    background-color: #21242e;
    border: 1px solid #2f3340;
    border-radius: 8px;
    padding: 7px 12px;
    color: #e8e8ec;
}}
QComboBox:hover {{
    border: 1px solid {a};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background-color: #1b1e27;
    border: 1px solid #2f3340;
    color: #e8e8ec;
    selection-background-color: {a};
    selection-color: #ffffff;
    outline: none;
    padding: 4px;
}}
QComboBox QAbstractItemView::item {{
    color: #e8e8ec;
    padding: 4px 6px;
}}
QComboBox QAbstractItemView::item:selected {{
    background-color: {a};
    color: #ffffff;
}}
QPushButton {{
    background-color: #262a35;
    border: 1px solid #333846;
    border-radius: 8px;
    padding: 8px 16px;
    color: #e8e8ec;
    font-weight: 500;
}}
QPushButton:hover {{
    background-color: #303543;
    border: 1px solid {a};
}}
QPushButton:pressed {{
    background-color: #1b1e27;
}}
QPushButton:disabled {{
    color: #5a5f6c;
    background-color: #1c1f27;
    border: 1px solid #262a35;
}}
QPushButton#primaryButton {{
    background-color: {a};
    border: 1px solid {a};
    color: #ffffff;
}}
QPushButton#primaryButton:hover {{
    background-color: {a_hover};
}}
QPushButton[checkable="true"]:checked {{
    background-color: {a};
    border: 1px solid {a};
    color: white;
}}
QListView {{
    background-color: #14161c;
    border: none;
    outline: none;
}}
QListView::item {{
    border-radius: 10px;
}}
QListView::item:selected {{
    background-color: #262a35;
}}
QListView::item:hover {{
    background-color: #1e222c;
}}
QScrollBar:vertical {{
    background: #1b1e27;
    width: 16px;
    margin: 0px;
    border-left: 1px solid #262a35;
}}
QScrollBar::handle:vertical {{
    background: {scrollbar_idle};
    border-radius: 8px;
    min-height: 34px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {a};
}}
QScrollBar::handle:vertical:pressed {{
    background: {a_pressed};
}}
QScrollBar::add-line, QScrollBar::sub-line {{
    height: 0px;
}}
QProgressBar {{
    background-color: #21242e;
    border: 1px solid #2f3340;
    border-radius: 8px;
    text-align: center;
    color: #e8e8ec;
    height: 18px;
}}
QProgressBar::chunk {{
    background-color: {a};
    border-radius: 8px;
}}
QLabel#detailTitle {{
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
}}
QLabel#detailMeta {{
    color: #9aa0ac;
    font-size: 13px;
}}
QTextEdit, QPlainTextEdit {{
    background-color: #1b1e27;
    border: 1px solid #2f3340;
    border-radius: 8px;
    color: #d7d9e0;
    padding: 8px;
}}
QTabWidget::pane {{
    border: 1px solid #2f3340;
    border-radius: 8px;
    top: -1px;
}}
QTabBar::tab {{
    background: #1b1e27;
    color: #9aa0ac;
    border: 1px solid #2f3340;
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 8px 14px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: #21242e;
    color: #ffffff;
    border-bottom: 2px solid {a};
}}
QTabBar::tab:hover:!selected {{
    color: #e8e8ec;
}}
QMenu {{
    background-color: #1b1e27;
    border: 1px solid #2f3340;
    color: #e8e8ec;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 20px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {a};
}}
QToolTip {{
    background-color: #21242e;
    color: #e8e8ec;
    border: 1px solid #2f3340;
    padding: 4px;
}}
"""


# Rueckwaertskompatibel: Modulname STYLESHEET mit Standardfarbe, falls
# irgendwo noch direkt darauf zugegriffen wird.
STYLESHEET = build_stylesheet()
