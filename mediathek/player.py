from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from .config import Library, DIR_NEU, DIR_ARCHIV
from .database import Database, Movie
from .scanner import _find_video_and_subs


def play_movie(movie: Movie) -> None:
    """Startet die Videodatei mit dem unter Windows registrierten Standardplayer
    (identisch zum Doppelklick im Explorer)."""
    if not movie.video_path:
        raise FileNotFoundError("Keine Videodatei fuer diesen Film gefunden.")
    path = Path(movie.video_path)
    if not path.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {path}")

    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{path}"')
    else:
        os.system(f'xdg-open "{path}"')


def _move_folder(library: Library, movie: Movie, target_location: str) -> Path:
    if movie.location == target_location:
        raise ValueError("Film befindet sich bereits am Zielort.")

    src_dir = (library.dir_neu if movie.location == DIR_NEU else library.dir_archiv) / movie.folder_name
    dst_root = library.dir_neu if target_location == DIR_NEU else library.dir_archiv
    dst_dir = dst_root / movie.folder_name

    if not src_dir.exists():
        raise FileNotFoundError(f"Quellordner fehlt: {src_dir}")
    if dst_dir.exists():
        raise FileExistsError(f"Zielordner existiert bereits: {dst_dir}")

    shutil.move(str(src_dir), str(dst_dir))
    return dst_dir


def mark_as_seen(library: Library, db: Database, movie: Movie) -> Movie:
    """Verschiebt den Film von NEU nach ARCHIV -> gilt danach als gesehen."""
    dst_dir = _move_folder(library, movie, DIR_ARCHIV)
    video_path, has_subs = _find_video_and_subs(dst_dir)
    db.set_location(movie.id, DIR_ARCHIV, video_path)
    return db.get(movie.id)


def mark_as_unseen(library: Library, db: Database, movie: Movie) -> Movie:
    """Verschiebt den Film von ARCHIV nach NEU -> gilt danach wieder als ungesehen."""
    dst_dir = _move_folder(library, movie, DIR_NEU)
    video_path, has_subs = _find_video_and_subs(dst_dir)
    db.set_location(movie.id, DIR_NEU, video_path)
    # Ein "nochmal ansehen"-Merker ist ueberfluessig, sobald der Film ohnehin
    # wieder als ungesehen gilt.
    db.set_rewatch(movie.id, False)
    return db.get(movie.id)


def open_movie_folder(library: Library, movie: Movie) -> None:
    """Oeffnet den Filmordner im Windows-Explorer, z.B. um den Dateinamen
    direkt vor Ort zu korrigieren."""
    folder = (library.dir_neu if movie.location == DIR_NEU else library.dir_archiv) / movie.folder_name
    if not folder.exists():
        raise FileNotFoundError(f"Ordner nicht gefunden: {folder}")

    if sys.platform.startswith("win"):
        os.startfile(str(folder))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        os.system(f'open "{folder}"')
    else:
        os.system(f'xdg-open "{folder}"')


def delete_movie_to_trash(library: Library, db: Database, movie: Movie) -> None:
    """Verschiebt den kompletten Filmordner in den normalen Windows-Papierkorb
    (nicht endgueltig loeschen!) und entfernt danach den Datenbankeintrag.
    Der Ordner laesst sich also jederzeit ganz normal aus dem Papierkorb
    wiederherstellen."""
    from send2trash import send2trash

    folder = (library.dir_neu if movie.location == DIR_NEU else library.dir_archiv) / movie.folder_name
    if folder.exists():
        send2trash(str(folder))
    db.delete_movie(movie.id)
