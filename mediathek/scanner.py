"""
Inkrementelle Indexierung der Filmordner.

Strategie fuer Geschwindigkeit bei ~2000 Filmen:
- Es wird NUR mit os.scandir() ueber die Top-Level-Filmordner (NEU/ARCHIV)
  iteriert -> das sind ~2000 Eintraege, nicht die Videodateien selbst.
- Bestehende DB-Eintraege werden EINMAL komplett geladen (list_movies())
  und danach nur noch per Dictionary nachgeschlagen -- keine einzelne
  SQL-Abfrage mehr pro Filmordner (frueher: ~2000 Einzelabfragen).
- Pro Filmordner wird die mtime des Ordners mit dem in der DB gespeicherten
  Wert verglichen. Nur bei Abweichung (neu, geaendert, Datei ausgetauscht)
  wird der Ordnerinhalt (Video/Untertitel) tatsaechlich erneut gelesen.
- Ordner, die in der DB stehen aber auf der Platte fehlen, werden als
  'missing' markiert statt geloescht (z.B. falls Platte kurz nicht verfuegbar
  war) und aus den Listen ausgeblendet.
- Das Windows-Erstelldatum (st_ctime -- unter Windows tatsaechlich das
  Erstelldatum, nicht wie unter Linux ein "Metadaten-geaendert"-Zeitstempel)
  wird zusaetzlich erfasst und dient als Basis fuer die Sortierung "Zuletzt
  hinzugefuegt". Fehlt es noch (aeltere CineVault-Version), wird es beim
  naechsten Scan automatisch einmalig nachgetragen.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Library, DIR_NEU, DIR_ARCHIV
from .database import Database

VIDEO_EXTENSIONS = {".mkv", ".mp4", ".avi", ".mov", ".m4v", ".wmv", ".ts"}


@dataclass
class ScanResult:
    new_count: int = 0
    updated_count: int = 0
    unchanged_count: int = 0
    missing_count: int = 0


def _find_video_and_subs(folder: Path) -> tuple[str | None, bool]:
    video_path = None
    biggest_size = -1
    has_subs = False
    try:
        for entry in folder.iterdir():
            if entry.is_dir():
                if entry.name.lower() in ("subs", "untertitel", "subtitles"):
                    has_subs = True
                continue
            if entry.suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                if size > biggest_size:
                    biggest_size = size
                    video_path = str(entry)
    except OSError:
        pass
    return video_path, has_subs


def scan_library(library: Library, db: Database, force_full: bool = False) -> ScanResult:
    result = ScanResult()
    seen_folder_names: set[str] = set()

    # EINE Abfrage statt einer pro Filmordner (frueher: db.get_by_folder_name()
    # innerhalb der Schleife -- bei ~2000 Filmen 2000 einzelne SQL-Anfragen).
    # Macht bei grossen Sammlungen einen spuerbaren Unterschied beim Start.
    existing_by_name = {m.folder_name: m for m in db.list_movies()}

    for location, folder in ((DIR_NEU, library.dir_neu), (DIR_ARCHIV, library.dir_archiv)):
        if not folder.exists():
            continue
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue

        for entry in entries:
            if not entry.is_dir():
                continue
            name = entry.name
            seen_folder_names.add(name)
            try:
                stat = entry.stat()
                mtime = stat.st_mtime
                ctime = stat.st_ctime
            except OSError:
                continue

            existing = existing_by_name.get(name)
            if existing is None:
                video_path, has_subs = _find_video_and_subs(entry)
                db.insert_new(name, location, mtime, video_path, has_subs, ctime)
                result.new_count += 1
                continue

            needs_refresh = (
                force_full
                or existing.missing == 1
                or existing.location != location
                or abs(existing.folder_mtime - mtime) > 0.5
                or not existing.folder_ctime  # aeltere DB ohne Erstelldatum -> einmalig nachtragen
            )
            if needs_refresh:
                video_path, has_subs = _find_video_and_subs(entry)
                db.update_scan_fields(name, location, mtime, video_path, has_subs, ctime)
                result.updated_count += 1
            else:
                result.unchanged_count += 1

    known_names = set(existing_by_name.keys())
    missing_names = known_names - seen_folder_names
    if missing_names:
        db.mark_missing(missing_names)
        result.missing_count = len(missing_names)

    return result
