"""
Native Windows-Fensteroptik: dunkle Titelleiste in App-Farbe statt der
Windows-Akzentfarbe, sowie das kleine Programm-Icon aus der Titelleiste
selbst entfernen (Minimieren/Maximieren/Schliessen bleiben unangetastet) --
wirkt aufgeraeumter/eleganter.

Beides rein kosmetisch: schlaegt einer der Aufrufe fehl (z.B. auf einer
aelteren Windows-Version ohne die noetigen DWM-Attribute, oder unter
macOS/Linux), wird das einfach stillschweigend uebersprungen und die
normale Titelleiste bleibt bestehen -- nie ein Grund fuer einen Absturz.

WICHTIG: Konnte mangels eigenem Windows-System nicht selbst getestet
werden. Beide Techniken sind aber seit Jahren bekannte, gut dokumentierte
Windows-API-Verfahren:
- DWMWA_CAPTION_COLOR / DWMWA_USE_IMMERSIVE_DARK_MODE (Windows 10 20H1+
  bzw. Windows 11 fuer die Farbe) ueber dwmapi.dll.
- WS_EX_DLGMODALFRAME + SWP_FRAMECHANGED, ein klassischer Trick, der
  Windows dazu bringt, die Titelleiste ohne das kleine Icon zu zeichnen.
"""
from __future__ import annotations

import sys


def apply_native_window_chrome(window, caption_hex: str = "#14161c") -> None:
    """Faerbt die Titelleiste dunkel und entfernt das kleine Titelleisten-
    Icon + den sichtbaren Fenstertitel. Wird am besten ganz am Ende von
    __init__() jedes Fensters aufgerufen (winId() erzeugt bei Bedarf
    automatisch das native Handle, ein vorheriges show() ist nicht noetig)."""
    if not sys.platform.startswith("win"):
        return
    try:
        hwnd = int(window.winId())
    except Exception:
        return

    _apply_dark_caption_color(hwnd, caption_hex)
    _remove_titlebar_icon(hwnd)
    _clear_native_caption_text(hwnd)


def _clear_native_caption_text(hwnd: int) -> None:
    """Loescht NUR den in der Titelleiste sichtbar gezeichneten Text auf
    nativer Windows-Ebene -- bewusst NICHT ueber Qts eigenes
    setWindowTitle(), damit Taskleisten-Tooltip/Alt-Tab weiterhin den
    echten Programm- bzw. Serien-/Filmtitel anzeigen."""
    try:
        import ctypes
        ctypes.windll.user32.SetWindowTextW(hwnd, "")
    except Exception:
        pass


def _apply_dark_caption_color(hwnd: int, caption_hex: str) -> None:
    try:
        import ctypes

        dwmapi = ctypes.windll.dwmapi
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        DWMWA_CAPTION_COLOR = 35

        dark_mode = ctypes.c_int(1)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(dark_mode), ctypes.sizeof(dark_mode))

        hex_clean = caption_hex.lstrip("#")
        r, g, b = (int(hex_clean[i:i + 2], 16) for i in (0, 2, 4))
        colorref = r | (g << 8) | (b << 16)  # COLORREF-Format ist 0x00BBGGRR
        color = ctypes.c_int(colorref)
        dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_CAPTION_COLOR, ctypes.byref(color), ctypes.sizeof(color))
    except Exception:
        pass  # aeltere Windows-Version (vor 10 20H1) oder anderer Fehler


def _remove_titlebar_icon(hwnd: int) -> None:
    try:
        import ctypes

        GWL_EXSTYLE = -20
        WS_EX_DLGMODALFRAME = 0x00000001
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOZORDER = 0x0004
        SWP_FRAMECHANGED = 0x0020

        user32 = ctypes.windll.user32
        ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex_style | WS_EX_DLGMODALFRAME)
        user32.SetWindowPos(
            hwnd, 0, 0, 0, 0, 0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_FRAMECHANGED)
    except Exception:
        pass
