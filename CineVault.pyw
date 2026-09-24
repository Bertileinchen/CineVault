"""
Startet CineVault OHNE Konsolenfenster.

Windows oeffnet .pyw-Dateien automatisch mit pythonw.exe statt python.exe
(sofern Python mit den Standardeinstellungen installiert wurde) -- dadurch
erscheint beim Doppelklick kein schwarzes Konsolenfenster mehr.

Einfach diese Datei per Doppelklick starten (oder eine Verknuepfung dazu auf
den Desktop legen). main.py bleibt unveraendert -- diese Datei ruft nur
dieselbe main()-Funktion auf.
"""
import sys
from pathlib import Path

# Sicherstellen, dass dieser Ordner (mit main.py und dem mediathek-Paket)
# im Suchpfad ist, auch wenn CineVault.pyw z.B. per Verknuepfung von einem
# anderen "Arbeitsordner" aus gestartet wird.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from main import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
