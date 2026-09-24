"""
Backup-Funktion.

Sichert den KOMPLETTEN Programmordner (Code + Datenordner) -- nicht nur die
Datenbank. Faellt also mal ein Update daneben, eine .py-Datei geht verloren
oder sonst irgendwas im Programmordner ist kaputt, reicht es, den
Backup-Ordner 1:1 zurueckzukopieren und alles laeuft wieder wie zuvor.

Je nach Aenderungsverhalten der Dateien kommen unterschiedliche Strategien
zum Einsatz:

- Programmcode (main.py, mediathek/*.py, assets, ...): sehr kleine Dateien,
  aendern sich nur bei einem Update. Werden inkrementell kopiert (nur
  neue/geaenderte Dateien) -- normalerweise passiert hier also nichts.
- Datenbank (mediathek.db): aendert sich staendig, ist aber klein (wenige MB
  selbst bei ~2000 Filmen). Wird daher bei JEDEM Backup komplett per
  SQLite's eigener Backup-API neu dupliziert -- sicher und schnell, auch
  waehrend die App laeuft (WAL-Modus aktiv). Ein einfacher Datei-Kopiervorgang
  waere hier NICHT sicher (moegliche Inkonsistenz durch WAL/SHM).
- Cover (MEDIA-Ordner): koennen zusammen mehrere hundert MB ausmachen,
  aendern sich aber nach dem ersten Sync so gut wie nie wieder. Werden daher
  ebenfalls INKREMENTELL kopiert.

Ergebnis ist bewusst ein Ordner mit normalen Einzeldateien (kein ZIP): bis
auf die Datenbank sind das alles statische, nach dem Schreiben nie wieder
veraenderte Dateien -- ein Cloud-Sync-Client wie Google Drive/OneDrive kommt
damit problemlos klar. Die Datenbank selbst wird ja ohnehin nur als
fertiger, abgeschlossener Snapshot abgelegt (nicht "live" wie im
Mediathek-Ordner waehrend die App laeuft).
"""
from __future__ import annotations

import shutil
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .config import DIR_PROGRAMMDATEN, Library, program_dir
from .database import Database

BACKUP_FOLDER_NAME = "CineVault-Backup"
_SKIP_DIR_NAMES = {"__pycache__", ".git"}


@dataclass
class BackupResult:
    path: Path             # Zielordner des Backups
    files_copied: int      # tatsaechlich neu kopierte/aktualisierte Dateien
    files_skipped: int     # bereits vorhandene, unveraenderte Dateien


def _file_unchanged(src: Path, dest: Path) -> bool:
    if not dest.exists():
        return False
    s, d = src.stat(), dest.stat()
    # Sekundengenauer Vergleich reicht -- diese Dateien werden nach dem
    # Schreiben praktisch nie mehr angefasst, ein exaktes Byte-fuer-Byte-Diff
    # waere hier nur unnoetig langsam.
    return s.st_size == d.st_size and int(s.st_mtime) == int(d.st_mtime)


def _copy_tree_incremental(src_root: Path, dest_root: Path, exclude: set[Path] = frozenset()) -> tuple[int, int]:
    """Kopiert src_root -> dest_root, ueberspringt aber unveraenderte
    Dateien sowie alles unterhalb der in 'exclude' gelisteten Pfade (werden
    z.B. fuer den Mediathek-Datenordner benutzt, der gesondert behandelt
    wird). Gibt (kopiert, uebersprungen) zurueck."""
    copied = 0
    skipped = 0
    if not src_root.exists():
        return copied, skipped

    for src in src_root.rglob("*"):
        if not src.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in src.relative_to(src_root).parts):
            continue
        if any(src == ex or ex in src.parents for ex in exclude):
            continue

        rel = src.relative_to(src_root)
        dest = dest_root / rel
        if _file_unchanged(src, dest):
            skipped += 1
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied += 1

    return copied, skipped


def create_backup(library: Library, db: Database, dest_dir: Path) -> BackupResult:
    """Erstellt/aktualisiert das Backup im gewaehlten Ordner. Wirft eine
    Exception bei Fehlern (z.B. Zielordner nicht erreichbar) -- der Aufrufer
    entscheidet, wie er das dem Nutzer meldet."""
    dest_dir = Path(dest_dir)
    backup_root = dest_dir / BACKUP_FOLDER_NAME
    backup_root.mkdir(parents=True, exist_ok=True)

    program_root = program_dir()
    data_dir_name = DIR_PROGRAMMDATEN  # "Mediathek" -- Unterordner mit DB/Cover

    total_copied = 0
    total_skipped = 0

    # --- 1) Programmcode & sonstige Dateien im Programmordner ---
    # (main.py, CineVault.pyw, mediathek/*.py, assets/, requirements.txt, ...)
    # Der "Mediathek"-Datenordner wird hier ausgeschlossen und unten
    # gesondert (sicher) behandelt.
    data_dir_path = program_root / data_dir_name
    # Falls das gewaehlte Backup-Ziel selbst innerhalb des Programmordners
    # liegt, darf der Backup-Ordner sich nicht versehentlich selbst kopieren.
    exclude_paths = {data_dir_path, backup_root.resolve()}
    copied, skipped = _copy_tree_incremental(program_root, backup_root, exclude=exclude_paths)
    total_copied += copied
    total_skipped += skipped

    # --- 2) Datenbank: immer komplett, aber klein & schnell ---
    data_backup_root = backup_root / data_dir_name
    data_backup_root.mkdir(parents=True, exist_ok=True)

    db_dest = data_backup_root / "mediathek.db"
    tmp_db = data_backup_root / ".mediathek.db.tmp"
    dst_conn = sqlite3.connect(str(tmp_db))
    try:
        db.conn.backup(dst_conn)
    finally:
        dst_conn.close()
    # Atomar ersetzen, damit bei einem Abbruch mitten im Schreiben keine
    # kaputte/unvollstaendige Datei liegen bleibt.
    shutil.move(str(tmp_db), str(db_dest))
    total_copied += 1

    # --- 3) Einstellungen + Pfad-Zeiger: klein, immer komplett kopieren ---
    if library.config_path.exists():
        shutil.copy2(library.config_path, data_backup_root / "config.json")
    pointer_src = data_dir_path / "pointer.json"
    if pointer_src.exists():
        shutil.copy2(pointer_src, data_backup_root / "pointer.json")

    # --- 4) Cover: inkrementell -- nur neue/geaenderte Dateien uebertragen ---
    if library.dir_media.exists():
        copied, skipped = _copy_tree_incremental(
            library.dir_media, data_backup_root / "MEDIA")
        total_copied += copied
        total_skipped += skipped

    return BackupResult(path=backup_root, files_copied=total_copied, files_skipped=total_skipped)
