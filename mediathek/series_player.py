"""
Backend-Funktionen fuer Serien -- analog zu player.py bei Filmen, aber mit
dem entscheidenden Unterschied: Episoden werden per Checkbox als "gesehen"
markiert (reines Metadaten-Flag, KEINE Dateibewegung), waehrend nur die
komplette Serie als Ganzes zwischen NEU/LAUFEND/ARCHIV wandert.

Naming-Konvention (siehe Bert's Entscheidung):
- NEU -> LAUFEND: automatisch beim Abhaken der ERSTEN Episode einer noch
  nicht begonnenen Serie, ODER durch die manuelle Aktion 'Serie beginnen'.
- LAUFEND/NEU -> ARCHIV: ausschliesslich manuell ueber 'Serie abschliessen'
  -- es gibt bewusst KEINE Automatik anhand von TMDbs Serienstatus
  ('Ended'/'Canceled'), da das unzuverlaessig/verspaetet gepflegt sein kann.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import DIR_ARCHIV, DIR_LAUFEND, DIR_NEU, SeriesLibrary
from .database import Database, Episode, Series
from .series_scanner import episode_video_path


def play_episode(series_library: SeriesLibrary, series: Series, episode: Episode) -> None:
    """Startet die Episoden-Videodatei mit dem unter Windows registrierten
    Standardplayer (identisch zum Doppelklick im Explorer)."""
    path = episode_video_path(series_library, series, episode.relative_path)
    if not path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")

    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


def next_unseen_episode(db: Database, series: Series) -> Episode | None:
    """Liefert die 'naechste' noch nicht abgehakte Episode (niedrigste
    Staffel-/Episodennummer) -- fuer den dominanten 'Abspielen'-Button im
    Detail-Fenster (Aequivalent zum einfachen Play-Button bei Filmen, nur
    dass eine Serie ja aus vielen Dateien statt einer besteht)."""
    episodes = [e for e in db.list_episodes_for_series(series.id) if e.missing == 0]
    unseen = [e for e in episodes if not e.seen]
    if not unseen:
        return None
    return min(unseen, key=lambda e: (e.season_number, e.episode_number))


def _move_series_folder(series_library: SeriesLibrary, series: Series, target_location: str) -> Path:
    import shutil

    if series.location == target_location:
        raise ValueError("Serie befindet sich bereits am Zielort.")

    src_dir = series_library.dir_for_location(series.location) / series.folder_name
    dst_dir = series_library.dir_for_location(target_location) / series.folder_name

    if not src_dir.exists():
        raise FileNotFoundError(f"Quellordner fehlt: {src_dir}")
    if dst_dir.exists():
        raise FileExistsError(f"Zielordner existiert bereits: {dst_dir}")

    shutil.move(str(src_dir), str(dst_dir))
    return dst_dir


def set_series_status(series_library: SeriesLibrary, db: Database, series: Series,
                       target_location: str) -> Series:
    """Verschiebt die KOMPLETTE Serie zwischen NEU/LAUFEND/ARCHIV (bewusst
    manuell auswaehlbar, nicht nur automatisch -- siehe Bert's Entscheidung:
    'automatisch beim ersten Abhaken, zusaetzlich aber auch eine manuelle
    Aktion vorsehen'). Die Episoden-Zeilen selbst werden dabei NICHT
    angefasst (ihr Pfad wird ja erst bei Bedarf aus series.location +
    relative_path zusammengesetzt, siehe series_scanner.episode_video_path)."""
    if target_location not in (DIR_NEU, DIR_LAUFEND, DIR_ARCHIV):
        raise ValueError(f"Ungueltiger Zielort: {target_location}")
    _move_series_folder(series_library, series, target_location)
    db.set_series_location(series.id, target_location)
    return db.get_series(series.id)


def toggle_episode_seen(series_library: SeriesLibrary, db: Database, series: Series,
                         episode: Episode, flag: bool) -> tuple[Episode, Series]:
    """Hakt eine Episode ab/entab -- reines Metadaten-Flag, KEINE
    Dateibewegung. Ist dies das ERSTE Abhaken einer noch nicht begonnenen
    (NEU) Serie, wandert die komplette Serie automatisch nach LAUFEND.
    Gibt (aktualisierte Episode, aktualisierte Serie) zurueck -- Serie
    aendert sich nur, wenn der automatische NEU->LAUFEND-Uebergang griff."""
    db.set_episode_seen(episode.id, flag)
    updated_episode = db.get_episode(episode.id)

    updated_series = series
    if flag and series.location == DIR_NEU:
        try:
            updated_series = set_series_status(series_library, db, series, DIR_LAUFEND)
        except (FileNotFoundError, FileExistsError, ValueError):
            # Automatik ist ein Komfort-Extra -- schlaegt das Verschieben aus
            # irgendeinem Grund fehl, bleibt die Episode trotzdem korrekt
            # abgehakt, nur der Serien-Status aendert sich dann eben nicht.
            updated_series = db.get_series(series.id)

    return updated_episode, updated_series


def mark_all_episodes_seen(series_library: SeriesLibrary, db: Database, series: Series) -> Series:
    """Markiert ALLE Episoden einer Serie auf einmal als gesehen -- praktisch
    v.a. beim erstmaligen Einpflegen bereits komplett geschauter Serien
    (Rechtsklick-Menue auf der Kachel). Loest denselben automatischen
    NEU->LAUFEND-Uebergang aus wie ein einzelnes Abhaken -- bewusst NICHT
    automatisch nach ARCHIV, das bleibt wie ueberall sonst eine bewusste,
    manuelle Aktion (siehe set_series_status)."""
    db.set_all_episodes_seen_for_series(series.id, True)

    updated_series = series
    if series.location == DIR_NEU:
        try:
            updated_series = set_series_status(series_library, db, series, DIR_LAUFEND)
        except (FileNotFoundError, FileExistsError, ValueError):
            updated_series = db.get_series(series.id)

    return updated_series


def open_series_folder(series_library: SeriesLibrary, series: Series) -> None:
    """Oeffnet den Serienordner im Windows-Explorer."""
    folder = series_library.dir_for_location(series.location) / series.folder_name
    if not folder.exists():
        raise FileNotFoundError(f"Ordner nicht gefunden: {folder}")

    if sys.platform.startswith("win"):
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{folder}"')
    else:
        os.system(f'xdg-open "{folder}"')


def delete_series_to_trash(series_library: SeriesLibrary, db: Database, series: Series) -> None:
    """Verschiebt den kompletten Serienordner in den Windows-Papierkorb
    (nicht endgueltig loeschen) und entfernt danach den Datenbankeintrag
    (Episoden werden per CASCADE automatisch mitgeloescht, siehe
    database.py)."""
    from send2trash import send2trash

    folder = series_library.dir_for_location(series.location) / series.folder_name
    if folder.exists():
        send2trash(str(folder))
    db.delete_series(series.id)
