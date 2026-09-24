"""
Inkrementelle Indexierung der Serienordner.

Deckt drei gaengige Strukturmuster ab (koennen auch gemischt vorkommen):
1. Staffel-Unterordner mit Episodendateien direkt drin ("Staffel 01/S01E02.mkv").
2. Episodendateien direkt im Serienordner, ohne Staffel-Unterordner.
3. EIN ORDNER PRO EPISODE (typisch bei Szene-/Release-Downloads, z.B.
   "Dragon.Ball.Super.E001.Titel...STARS/" mit der Videodatei darin) --
   solche Ordner werden erkannt, indem geprueft wird, ob direkt eine
   Videodatei drinsteckt, auch wenn der Ordnername selbst nicht wie eine
   Staffel aussieht.

Nur Ordner, die eindeutig KEINE Episode sind (Extras/Bonus/Making-of/...,
siehe series_utils.is_non_episode_folder_name), werden weiterhin komplett
uebersprungen -- auch wenn dort zufaellig eine Videodatei liegt.

Folgt ansonsten demselben Grundprinzip wie scanner.py bei Filmen:
Ordner-mtime der SERIE (nicht jeder einzelnen Episodendatei) mit dem in der
DB gespeicherten Wert vergleichen, nur bei Aenderung wird der komplette
Serienordner tatsaechlich neu eingelesen. Das reicht aus, weil das
Hinzufuegen/Entfernen einer Datei in einem Unterordner die mtime des
Serien-Wurzelordners i.d.R. NICHT veraendert -- deshalb wird zusaetzlich die
mtime jedes Unterordners mit einbezogen (siehe _folder_signature).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .config import DIR_ARCHIV, DIR_LAUFEND, DIR_NEU, SeriesLibrary
from .database import Database, Series
from .scanner import VIDEO_EXTENSIONS
from .series_utils import (
    is_non_episode_folder_name,
    parse_season_episode_from_filename,
    parse_season_number_from_folder,
    resolve_episode_numbers,
)


@dataclass
class SeriesScanResult:
    new_series: int = 0
    updated_series: int = 0
    unchanged_series: int = 0
    missing_series: int = 0
    new_episodes: int = 0
    missing_episodes: int = 0


def episode_video_path(series_library: SeriesLibrary, series: Series, relative_path: str) -> Path:
    """Setzt den aktuellen absoluten Pfad einer Episode aus series.location +
    series.folder_name + relative_path zusammen (siehe database.py
    Kopfkommentar bei der episodes-Tabelle -- der Pfad wird bewusst NICHT
    direkt in der Datenbank gespeichert, da er sich bei jedem Verschieben
    der kompletten Serie sonst fuer jede einzelne Episode aendern wuerde)."""
    base = series_library.dir_for_location(series.location)
    return base / series.folder_name / relative_path


def _folder_signature(series_folder: Path) -> float:
    """Kombinierte 'Aenderungs-Kennzahl' aus der mtime des Serienordners
    selbst UND seiner direkten Unterordner UND deren direkten Unterordnern
    (2 Ebenen tief, NICHT bis zu den Videodateien selbst) -- eine neue/
    geloeschte Datei in einem Staffel- oder Episode-Ordner veraendert
    dessen eigene mtime, das reicht als Signal, ohne dass wir bis zu den
    Blattdateien selbst hinabsteigen muessen (bei Serien mit hunderten
    Episode-Ordnern -- z.B. ein Ordner PRO Episode, siehe Modul-
    Kopfkommentar -- spart das spuerbar Zeit beim Programmstart).

    Nutzt bewusst os.scandir() statt Path.iterdir(): os.scandir() liefert
    unter Windows Dateiattribute/Zeitstempel schon beim Auflisten mit
    (DirEntry-Cache), sodass is_dir() und meist auch stat() OHNE
    zusaetzlichen Systemaufruf pro Eintrag auskommen -- Path.iterdir()
    wuerde fuer jeden einzelnen Eintrag erneut einen echten stat()-Aufruf
    ausloesen."""
    try:
        newest = series_folder.stat().st_mtime
    except OSError:
        return 0.0

    try:
        with os.scandir(series_folder) as it:
            level1 = [e for e in it if e.is_dir()]
    except OSError:
        return newest

    for entry in level1:
        try:
            newest = max(newest, entry.stat().st_mtime)
        except OSError:
            continue
        try:
            with os.scandir(entry.path) as it2:
                for sub_entry in it2:
                    if sub_entry.is_dir():
                        try:
                            newest = max(newest, sub_entry.stat().st_mtime)
                        except OSError:
                            pass
        except OSError:
            pass

    return newest


def _largest_video_in(folder: Path) -> Path | None:
    """Fuer Episode-Ordner mit ggf. mehreren Dateien drin (z.B. eine
    Sample-Datei zusaetzlich zur eigentlichen Episode) -- analog zur
    Video-Erkennung bei Filmen wird die groesste Datei genommen."""
    best = None
    best_size = -1
    try:
        for f in folder.iterdir():
            if f.is_file() and f.suffix.lower() in VIDEO_EXTENSIONS:
                try:
                    size = f.stat().st_size
                except OSError:
                    size = 0
                if size > best_size:
                    best_size = size
                    best = f
    except OSError:
        pass
    return best


def _collect_episode_sources(folder: Path) -> list[tuple[str, Path]]:
    """Liefert (Name-zum-Erkennen, Videodatei) fuer alle Episoden direkt IN
    'folder' -- sowohl lose Videodateien als auch (siehe Modul-Kopfkommentar,
    Muster 3) Unterordner, die selbst eine Videodatei enthalten. Fuer
    Unterordner wird bewusst der ORDNERNAME zur Nummer-Erkennung verwendet
    (bei Szene-Releases meist aussagekraeftiger als der Dateiname darin,
    der z.B. schlicht 'video.mkv' heissen kann)."""
    sources: list[tuple[str, Path]] = []
    try:
        entries = list(folder.iterdir())
    except OSError:
        return sources

    for entry in entries:
        if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
            sources.append((entry.name, entry))
        elif entry.is_dir() and not is_non_episode_folder_name(entry.name):
            video = _largest_video_in(entry)
            if video is not None:
                sources.append((entry.name, video))

    return sources


def _scan_season_dir(season_dir: Path) -> dict[int, Path]:
    """Liefert {episode_number: video_datei} fuer eine Staffel."""
    sources = _collect_episode_sources(season_dir)
    resolved = resolve_episode_numbers(sources)
    return {ep_num: f for f, ep_num in resolved.items()}


def _scan_flat_sources(sources: list[tuple[str, Path]]) -> dict[tuple[int, int], Path]:
    """Episoden, die OHNE Staffel-Unterordner direkt im Serienordner liegen
    (als Datei oder als eigener Episode-Ordner)."""
    result: dict[tuple[int, int], Path] = {}
    remaining: list[tuple[str, Path]] = []
    for name, path in sources:
        season_number, ep_num = parse_season_episode_from_filename(name)
        if season_number is not None and ep_num is not None:
            result[(season_number, ep_num)] = path
        else:
            remaining.append((name, path))

    if remaining:
        for path, ep_num in resolve_episode_numbers(remaining).items():
            assigned = ep_num
            while (1, assigned) in result:
                assigned += 1
            result[(1, assigned)] = path

    return result


def _scan_series_folder(series_folder: Path) -> dict[tuple[int, int], Path]:
    """Liefert {(staffel, episode): video_datei} fuer eine komplette Serie."""
    result: dict[tuple[int, int], Path] = {}
    try:
        entries = list(series_folder.iterdir())
    except OSError:
        return result

    flat_sources: list[tuple[str, Path]] = []
    for entry in entries:
        if entry.is_file() and entry.suffix.lower() in VIDEO_EXTENSIONS:
            flat_sources.append((entry.name, entry))
            continue
        if not entry.is_dir():
            continue
        if is_non_episode_folder_name(entry.name):
            continue  # z.B. "Extras"/"Bonusmaterial" -- bewusst uebersprungen

        season_number = parse_season_number_from_folder(entry.name)
        if season_number is not None:
            # Klassischer Staffelordner mit Episoden(-dateien oder -ordnern) drin.
            for ep_num, f in _scan_season_dir(entry).items():
                result[(season_number, ep_num)] = f
            continue

        # Kein Staffelordner -- aber vielleicht ein Episode-Ordner (Muster 3)?
        video = _largest_video_in(entry)
        if video is not None:
            flat_sources.append((entry.name, video))
        # Enthaelt weder Video noch erkennbare Staffelstruktur -> uebersprungen.

    if flat_sources:
        result.update(_scan_flat_sources(flat_sources))

    return result


def scan_series_library(series_library: SeriesLibrary, db: Database,
                         force_full: bool = False) -> SeriesScanResult:
    result = SeriesScanResult()
    seen_folder_names: set[str] = set()

    # EINE Abfrage statt einer pro Serie (siehe scanner.py bei Filmen fuer
    # denselben Trick) -- bei vielen Serien spuerbar schneller als vorher.
    existing_by_name = {s.folder_name: s for s in db.list_series()}

    for location, root in (
        (DIR_NEU, series_library.dir_neu),
        (DIR_LAUFEND, series_library.dir_laufend),
        (DIR_ARCHIV, series_library.dir_archiv),
    ):
        if not root.exists():
            continue
        try:
            entries = list(root.iterdir())
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
            signature = _folder_signature(entry)

            if existing is None:
                series_id = db.insert_new_series(name, location, signature, ctime)
                episodes = _scan_series_folder(entry)
                for (season_num, ep_num), video_file in episodes.items():
                    rel = str(video_file.relative_to(entry))
                    db.upsert_episode(series_id, season_num, ep_num, rel)
                result.new_series += 1
                result.new_episodes += len(episodes)
                continue

            needs_refresh = (
                force_full
                or existing.missing == 1
                or existing.location != location
                or abs(existing.folder_mtime - signature) > 0.5
                or not existing.folder_ctime
            )
            if needs_refresh:
                db.update_series_scan_fields(name, location, signature, ctime)
                before_ids = {e.id for e in db.list_episodes_for_series(existing.id)}
                episodes = _scan_series_folder(entry)
                kept_ids = []
                for (season_num, ep_num), video_file in episodes.items():
                    rel = str(video_file.relative_to(entry))
                    eid = db.upsert_episode(existing.id, season_num, ep_num, rel)
                    kept_ids.append(eid)
                db.mark_episodes_missing_except(existing.id, kept_ids)
                newly_missing = before_ids - set(kept_ids)
                newly_added = set(kept_ids) - before_ids
                result.missing_episodes += len(newly_missing)
                result.new_episodes += len(newly_added)
                result.updated_series += 1
            else:
                result.unchanged_series += 1

    known_names = set(existing_by_name.keys())
    missing_names = known_names - seen_folder_names
    if missing_names:
        db.mark_series_missing(missing_names)
        result.missing_series = len(missing_names)

    return result
