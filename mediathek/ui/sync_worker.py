"""
Fuehrt den TMDb-Abgleich in einem Hintergrund-Thread durch, damit die
Oberflaeche waehrend der Synchronisierung von ggf. hunderten Filmen
nicht einfriert. Nutzt einen kleinen Thread-Pool (mehrere gleichzeitige
Anfragen), meldet aber jeden fertigen Film einzeln per Qt-Signal an den
Hauptthread zurueck, damit die Liste live aktualisiert werden kann.
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QPixmap

from ..config import Library
from ..database import Database, Movie
from ..metadata_client import TmdbClient, TmdbError
from ..utils import parse_title_year, slugify

try:
    from PIL import Image
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


def _save_poster(library: Library, movie: Movie, poster_bytes: bytes) -> str:
    """Speichert das Cover in voller Groesse (MEDIA/covers) und erzeugt zusaetzlich
    ein kleines Thumbnail (MEDIA/thumbs) fuer eine fluessige Kachelansicht.
    Gibt den *relativen* Dateinamen zurueck (identisch in covers/ und thumbs/)."""
    filename = f"{slugify(movie.folder_name)}_{movie.id}.jpg"
    cover_path = library.dir_covers / filename
    thumb_path = library.dir_thumbs / filename

    cover_path.write_bytes(poster_bytes)

    if _HAVE_PIL:
        try:
            with Image.open(cover_path) as img:
                img = img.convert("RGB")
                img.thumbnail((240, 360))
                img.save(thumb_path, "JPEG", quality=85)
        except Exception:
            thumb_path.write_bytes(poster_bytes)
    else:
        thumb_path.write_bytes(poster_bytes)

    return filename


def sync_single_movie(library: Library, db: Database, client: TmdbClient, movie: Movie) -> Movie:
    """Verarbeitet genau einen Film synchron (wird vom ThreadPool parallel aufgerufen)."""
    query, year = parse_title_year(movie.folder_name)
    try:
        result, ambiguous, candidates = client.search_movie(query, year)
        if ambiguous:
            note = (
                "Mehrere gleichnamige Filme gefunden, kein Jahr im Dateinamen "
                "erkennbar -- bitte unten den richtigen auswählen."
            )
            db.set_metadata_ambiguous(movie.id, note, json.dumps(candidates, ensure_ascii=False))
            return db.get(movie.id)
        if not result:
            db.set_metadata_not_found(movie.id)
            return db.get(movie.id)

        title = result.get("title") or query
        original_title = result.get("original_title")
        release_date = result.get("release_date") or ""
        found_year = int(release_date[:4]) if release_date[:4].isdigit() else year
        overview = result.get("overview") or ""
        poster_path_remote = result.get("poster_path")
        tmdb_id = result.get("id")

        local_poster_name = None
        if poster_path_remote:
            poster_bytes = client.fetch_poster_bytes(poster_path_remote)
            local_poster_name = _save_poster(library, movie, poster_bytes)

        cast_names, genre_names, trailer_url, trailer_language = (
            client.get_extra_details(tmdb_id) if tmdb_id else (None, None, None, None)
        )

        db.set_metadata_ok(movie.id, tmdb_id, title, original_title, found_year,
                           overview, local_poster_name, cast_names, trailer_url,
                           trailer_language, genre_names)
    except TmdbError as e:
        db.set_metadata_error(movie.id, str(e))
    except Exception as e:  # Netzwerkfehler, Timeouts etc.
        db.set_metadata_error(movie.id, str(e))

    return db.get(movie.id)


def assign_tmdb_id(library: Library, db: Database, movie: Movie, tmdb_id: int) -> Movie:
    """Weist einem Film DIREKT einen bestimmten TMDb-Film zu (per ID), ganz
    ohne Titelsuche/Aehnlichkeitspruefung -- fuer den Fall, dass der Nutzer
    den korrekten TMDb-Link selbst kennt (z.B. weil die automatische Suche
    wegen abweichender Schreibweise im Ordnernamen ins Leere lief)."""
    client = TmdbClient(library.config.tmdb_api_key, library.config.tmdb_language)

    data = client.get_movie_by_id(tmdb_id)
    title = data.get("title") or movie.folder_name
    original_title = data.get("original_title")
    release_date = data.get("release_date") or ""
    year = int(release_date[:4]) if release_date[:4].isdigit() else None
    overview = data.get("overview") or ""
    poster_path_remote = data.get("poster_path")

    local_poster_name = None
    if poster_path_remote:
        poster_bytes = client.fetch_poster_bytes(poster_path_remote)
        local_poster_name = _save_poster(library, movie, poster_bytes)

    cast_names, genre_names, trailer_url, trailer_language = client.get_extra_details(tmdb_id)

    db.set_metadata_ok(movie.id, tmdb_id, title, original_title, year, overview,
                        local_poster_name, cast_names, trailer_url, trailer_language, genre_names)
    return db.get(movie.id)


class ManualAssignWorker(QThread):
    """Fuehrt assign_tmdb_id() im Hintergrund aus, damit die Oberflaeche
    waehrend der (wenigen) Netzwerkanfragen nicht blockiert."""
    finished_ok = Signal(object)   # Movie
    failed = Signal(str)

    def __init__(self, library: Library, db: Database, movie: Movie, tmdb_id: int, parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self._movie = movie
        self._tmdb_id = tmdb_id

    def run(self) -> None:
        if not self._library.config.tmdb_api_key:
            self.failed.emit(
                "Kein TMDb-API-Key hinterlegt. Bitte unter 'Einstellungen' einen "
                "kostenlosen API-Key eintragen (https://www.themoviedb.org/settings/api)."
            )
            return
        try:
            updated = assign_tmdb_id(self._library, self._db, self._movie, self._tmdb_id)
            self.finished_ok.emit(updated)
        except TmdbError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(str(e))


class ExtraInfoBackfillWorker(QThread):
    """Ergaenzt bei bereits zugeordneten Filmen (bekannte TMDb-ID) fehlende
    Besetzung/Genre/Trailer -- per direkter ID-Abfrage, OHNE Titelsuche und
    OHNE sync_status zurueckzusetzen. Das ist bewusst der sichere
    Gegenentwurf zu einem vollstaendigen Re-Sync: Titel, Beschreibung, Cover
    und eine z.B. per Mehrdeutigkeits-Dropdown getroffene Auswahl bleiben
    dabei garantiert unangetastet. Bereits vorhandene Werte werden nie
    ueberschrieben, nur echte Luecken werden aufgefuellt. Dient als Vorlage
    fuer aehnliche kuenftige Nachlade-Faelle."""
    progress = Signal(int, int)      # (erledigt, gesamt)
    movie_updated = Signal(object)   # Movie
    finished_all = Signal(int, int)  # (erfolgreich, gesamt)

    def __init__(self, library: Library, db: Database, movies: list[Movie], parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self._movies = movies

    def run(self) -> None:
        total = len(self._movies)
        done = 0
        ok_count = 0
        client = TmdbClient(self._library.config.tmdb_api_key or "-", self._library.config.tmdb_language)

        with ThreadPoolExecutor(max_workers=max(1, min(self._library.config.sync_concurrency, 10))) as pool:
            futures = {pool.submit(self._backfill_movie, client, self._db, m): m for m in self._movies}
            for future in as_completed(futures):
                movie = futures[future]
                try:
                    if future.result():
                        ok_count += 1
                    updated = self._db.get(movie.id)
                    if updated:
                        self.movie_updated.emit(updated)
                except Exception:
                    pass
                done += 1
                self.progress.emit(done, total)

        self.finished_all.emit(ok_count, total)

    @staticmethod
    def _backfill_movie(client: TmdbClient, db: Database, movie: Movie) -> bool:
        if not movie.tmdb_id:
            return False
        cast_names, genre_names, trailer_url, trailer_lang = client.get_extra_details(movie.tmdb_id)

        updates: dict = {}
        if not movie.genre_names and genre_names:
            updates["genre_names"] = genre_names
        if not movie.cast_names and cast_names:
            updates["cast_names"] = cast_names
        if not movie.trailer_url and trailer_url:
            updates["trailer_url"] = trailer_url
            updates["trailer_language"] = trailer_lang

        if not updates:
            return False
        db.set_extra_details(movie.id, **updates)
        return True


class SyncWorker(QThread):
    progress = Signal(int, int)          # (erledigt, gesamt)
    movie_updated = Signal(object)       # Movie
    finished_sync = Signal(int, int)     # (erfolgreich, gesamt)
    error = Signal(str)

    def __init__(self, library: Library, db: Database, movies: list[Movie], parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self._movies = movies
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        if not self._library.config.tmdb_api_key:
            self.error.emit(
                "Kein TMDb-API-Key hinterlegt. Bitte unter 'Einstellungen' einen "
                "kostenlosen API-Key eintragen (https://www.themoviedb.org/settings/api)."
            )
            self.finished_sync.emit(0, len(self._movies))
            return

        client = TmdbClient(self._library.config.tmdb_api_key,
                             self._library.config.tmdb_language)
        total = len(self._movies)
        done = 0
        ok_count = 0

        concurrency = max(1, min(self._library.config.sync_concurrency, 10))
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(sync_single_movie, self._library, self._db, client, m): m
                for m in self._movies
            }
            for future in as_completed(futures):
                if self._cancel:
                    break
                try:
                    updated_movie = future.result()
                    if updated_movie and updated_movie.sync_status == "ok":
                        ok_count += 1
                    if updated_movie:
                        self.movie_updated.emit(updated_movie)
                except Exception as e:
                    self.error.emit(str(e))
                done += 1
                self.progress.emit(done, total)

        self.finished_sync.emit(ok_count, total)


class CandidatePosterWorker(QThread):
    """Laedt im Hintergrund kleine Vorschau-Cover fuer die bei einem
    mehrdeutigen Sync-Treffer zur Auswahl stehenden Kandidaten (z.B. die
    2016er und die 1959er Version von "Ben-Hur"), damit das Detail-Fenster
    beim Durchklicken des Auswahl-Dropdowns direkt Cover + Beschreibung
    zeigen kann. Rein fuers Anzeigen gedacht -- es wird nichts auf der
    Festplatte gespeichert."""
    poster_ready = Signal(int, object)  # tmdb_id, QPixmap

    def __init__(self, library: Library, candidates: list[dict], parent=None):
        super().__init__(parent)
        self._library = library
        self._candidates = candidates

    def run(self) -> None:
        client = TmdbClient(self._library.config.tmdb_api_key or "-", self._library.config.tmdb_language)
        for c in self._candidates:
            poster_path = c.get("poster_path")
            tmdb_id = c.get("id")
            if not poster_path or tmdb_id is None:
                continue
            try:
                data = client.fetch_poster_bytes(poster_path, size="w154")
            except Exception:
                continue
            pm = QPixmap()
            if pm.loadFromData(data) and not pm.isNull():
                self.poster_ready.emit(tmdb_id, pm)


class BackupWorker(QThread):
    """Fuehrt create_backup() im Hintergrund aus, damit die Oberflaeche
    waehrend eines (v.a. beim allerersten Mal potenziell laengeren) Backups
    nicht einfriert."""
    finished_ok = Signal(object)   # BackupResult
    failed = Signal(str)

    def __init__(self, library: Library, db: Database, dest_dir, parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self._dest_dir = dest_dir

    def run(self) -> None:
        from ..backup import create_backup
        try:
            result = create_backup(self._library, self._db, self._dest_dir)
            self.finished_ok.emit(result)
        except Exception as e:
            self.failed.emit(str(e))
