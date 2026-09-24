"""
CineVault – Einstiegspunkt.

Start unter Windows 11 (mit Konsolenfenster, z.B. zum Debuggen):
    python main.py

Start OHNE Konsolenfenster (fuer den normalen Alltagsgebrauch, z.B. per
Doppelklick oder Desktop-Verknuepfung):
    CineVault.pyw

(oder als gebaute CineVault.exe, siehe README.md)

Wichtig: Alle Imports, die PySide6 oder das mediathek-Paket benoetigen,
passieren bewusst ERST innerhalb von run() (nicht auf Modulebene). So kann
main() selbst einen Fehler beim Programmstart (z.B. ein fehlerhafter Import,
eine fehlende Abhaengigkeit) abfangen und in eine crash.log-Datei schreiben,
statt dass die App (bei --windowed gebauter .exe) lautlos verschwindet oder
nur kurz ein Konsolenfenster aufblitzt.
"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path


def _program_dir() -> Path:
    """Ordner der .exe (PyInstaller --onefile) bzw. im Entwicklungsbetrieb
    der Ordner, der main.py enthaelt."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(sys.argv[0]).resolve().parent


def _icon_path() -> Path:
    """Pfad zum App-Icon."""
    from mediathek.config import app_assets_dir
    return app_assets_dir() / "cinevault.ico"


def _write_crash_log(exc: BaseException) -> Path | None:
    try:
        log_path = _program_dir() / "crash.log"
        log_path.write_text(
            "CineVault konnte nicht gestartet werden bzw. ist abgestuerzt.\n"
            "Bitte diese Datei bei Rueckfragen mitschicken.\n\n"
            + traceback.format_exc(),
            encoding="utf-8",
        )
        return log_path
    except Exception:
        return None


def _apply_native_taskbar_icon(window, icon_path: Path) -> None:
    """Setzt das Fenster-Icon zusaetzlich direkt per Windows-API (WM_SETICON).

    Hintergrund: app.setWindowIcon() (Qt) sollte eigentlich ausreichen, aber
    es gibt einen bekannten, haeufig berichteten Windows-Eigenheit-Bug, bei
    dem die Taskleiste bei mit python.exe/pythonw.exe gestarteten Programmen
    das eigene Icon erst ab dem zweiten Start einer Windows-Sitzung korrekt
    uebernimmt (die HICON-Zuweisung ueber Qt allein kommt fuer den ganz
    ersten Taskleisten-Eintrag manchmal "zu spaet"). Das direkte Senden von
    WM_SETICON per WinAPI unmittelbar nach dem Anzeigen des Fensters behebt
    das zuverlaessig -- unabhaengig von Qt-internem Timing."""
    if not sys.platform.startswith("win") or not icon_path.exists():
        return
    try:
        import ctypes

        hwnd = int(window.winId())
        IMAGE_ICON = 1
        LR_LOADFROMFILE = 0x00000010
        WM_SETICON = 0x0080
        ICON_SMALL = 0
        ICON_BIG = 1

        user32 = ctypes.windll.user32
        hicon_small = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 16, 16, LR_LOADFROMFILE)
        hicon_big = user32.LoadImageW(None, str(icon_path), IMAGE_ICON, 32, 32, LR_LOADFROMFILE)
        if hicon_small:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_SMALL, hicon_small)
        if hicon_big:
            user32.SendMessageW(hwnd, WM_SETICON, ICON_BIG, hicon_big)
    except Exception:
        pass


def run() -> int:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from mediathek.config import Library, load_filme_root, save_filme_root, DIR_NEU, DIR_ARCHIV
    from mediathek.database import Database
    from mediathek.ui.main_window import MainWindow
    from mediathek.ui.styles import build_stylesheet, STYLESHEET

    # Windows gruppiert Taskleisten-Icons standardmaessig anhand des
    # ausfuehrenden Prozesses (python.exe/pythonw.exe) -- dadurch zeigt die
    # Taskleiste beim allerersten Start einer Windows-Sitzung oft noch das
    # generische Python-Symbol, bis Windows sein Icon-Cache aktualisiert
    # (typischerweise erst beim naechsten Start sichtbar). Ein explizites
    # "AppUserModelID" loest CineVault von der Python-Identitaet und behebt
    # das zuverlaessig ab dem ersten Start. Muss VOR dem Erzeugen von
    # Fenstern gesetzt werden.
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("CineVault.App")
        except Exception:
            pass

    def select_filme_folder() -> Path | None:
        QMessageBox.information(
            None, "CineVault – Einrichtung",
            "Bitte waehle deinen 'FILME'-Hauptordner aus.\n\n"
            "Dieser sollte die Unterordner 'NEU' und 'ARCHIV' enthalten."
        )
        chosen = QFileDialog.getExistingDirectory(None, "FILME-Ordner auswaehlen")
        if not chosen:
            return None
        path = Path(chosen)

        if not (path / DIR_NEU).exists() and not (path / DIR_ARCHIV).exists():
            answer = QMessageBox.question(
                None, "Ordner pruefen",
                f"In '{path}' wurden weder 'NEU' noch 'ARCHIV' gefunden.\n"
                "Trotzdem fortfahren? (Die Ordner werden dann automatisch angelegt.)"
            )
            if answer != QMessageBox.Yes:
                return None
        return path

    app = QApplication(sys.argv)
    app.setStyleSheet(STYLESHEET)

    icon_file = _icon_path()
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))

    root = load_filme_root()
    if root is None:
        root = select_filme_folder()
        if root is None:
            return 0
        save_filme_root(root)

    library = Library(root)
    db = Database(library.db_path)
    # Jetzt, wo die Einstellungen geladen sind, das Stylesheet mit der
    # tatsaechlich gewaehlten Akzentfarbe anwenden (vorher lief nur die
    # Standardfarbe, da der FILME-Ordner beim allerersten Start noch nicht
    # bekannt war).
    app.setStyleSheet(build_stylesheet(library.config.accent_color))

    if not library.config.tmdb_api_key:
        QMessageBox.information(
            None, "TMDb-API-Key fehlt",
            "Fuer die automatische Synchronisierung von Titel, Cover und Beschreibung "
            "wird ein kostenloser TMDb-API-Key benoetigt.\n\n"
            "Du kannst ihn gleich unter dem Zahnrad-Symbol (⚙ Einstellungen) eintragen."
        )

    window = MainWindow(library, db)
    if icon_file.exists():
        window.setWindowIcon(QIcon(str(icon_file)))
    window.show()
    _apply_native_taskbar_icon(window, icon_file)

    exit_code = app.exec()
    db.close()
    return exit_code


def main() -> int:
    try:
        return run()
    except Exception as exc:
        log_path = _write_crash_log(exc)
        # Best-effort: falls Qt zumindest so weit laden konnte, eine normale
        # Fehlermeldung statt eines nackten Absturzes anzeigen.
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            app = QApplication.instance() or QApplication(sys.argv)
            details = f"\n\nDetails wurden gespeichert unter:\n{log_path}" if log_path else ""
            QMessageBox.critical(
                None, "CineVault – Fehler beim Start",
                f"Das Programm konnte nicht gestartet werden:\n\n{exc}{details}"
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
