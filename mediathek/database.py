"""
Sehr duenne SQLite-Datenschicht. Kein ORM, bewusst simpel und schnell.

Ein einzelnes Connection-Objekt wird von mehreren Threads genutzt (der
Sync-Vorgang laeuft mit mehreren parallelen Worker-Threads). Ein einfacher
Lock serialisiert alle Zugriffe und verhindert "database is locked"-Fehler.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Iterable, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS movies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_name TEXT UNIQUE NOT NULL,
    location TEXT NOT NULL,            -- 'NEU' oder 'ARCHIV'
    folder_mtime REAL NOT NULL,
    video_path TEXT,
    has_subs INTEGER NOT NULL DEFAULT 0,

    tmdb_id INTEGER,
    title TEXT,
    original_title TEXT,
    year INTEGER,
    overview TEXT,

    poster_path TEXT,                  -- relativer Pfad unter MEDIA/covers
    poster_source TEXT,                -- 'tmdb' oder 'manual'

    cast_names TEXT,                   -- Hauptbesetzung, kommagetrennt
    genre_names TEXT,                  -- Genres, kommagetrennt
    trailer_url TEXT,                  -- YouTube-Link, falls vorhanden
    trailer_language TEXT,             -- 'de' oder 'en'

    sync_status TEXT NOT NULL DEFAULT 'pending',  -- pending/ok/not_found/error/manual
    sync_error TEXT,

    rewatch INTEGER NOT NULL DEFAULT 0,   -- 1 = zum "nochmal ansehen" vorgemerkt
    folder_ctime REAL NOT NULL DEFAULT 0, -- Windows-Erstelldatum des Ordners
    ambiguous_candidates TEXT,             -- JSON-Liste bei mehrdeutigem Sync-Treffer

    added_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0  -- 1 = Ordner wurde nicht mehr gefunden
);
CREATE INDEX IF NOT EXISTS idx_movies_location ON movies(location);
CREATE INDEX IF NOT EXISTS idx_movies_sync_status ON movies(sync_status);

-- ================== Serien (komplett getrennter Bereich) ==================
-- Eigene Tabellen, eigener Programmbereich -- absichtlich nicht mit den
-- Filmen vermischt. Vom Aufbau her sehr aehnlich zu 'movies', aber mit
-- einem dritten Ordner-Zustand ('LAUFEND') und einer eigenen Episoden-
-- Tabelle darunter.
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_name TEXT UNIQUE NOT NULL,
    location TEXT NOT NULL,            -- 'NEU', 'LAUFEND' oder 'ARCHIV'
    folder_mtime REAL NOT NULL,
    folder_ctime REAL NOT NULL DEFAULT 0,

    tmdb_id INTEGER,
    title TEXT,
    original_title TEXT,
    first_air_year INTEGER,
    overview TEXT,

    poster_path TEXT,
    poster_source TEXT,

    cast_names TEXT,
    genre_names TEXT,
    trailer_url TEXT,
    trailer_language TEXT,

    sync_status TEXT NOT NULL DEFAULT 'pending',  -- pending/ok/not_found/error/manual/ambiguous
    sync_error TEXT,
    ambiguous_candidates TEXT,

    added_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0,

    -- Reine UI-Bequemlichkeit (kein Datenbank fuer Kern-Metadaten): merkt
    -- sich pro Serie, welche Staffeln im Detail-Fenster eingeklappt waren
    -- und wo der Scrollbalken der Episodenliste zuletzt stand.
    collapsed_seasons TEXT,
    episode_scroll_position INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_series_location ON series(location);
CREATE INDEX IF NOT EXISTS idx_series_sync_status ON series(sync_status);

-- Der aktuelle Ordnerpfad einer Episode wird bewusst NICHT direkt
-- gespeichert, sondern aus series.location + series.folder_name +
-- relative_path zusammengesetzt (siehe episode_video_path() weiter unten).
-- Dadurch muss beim Verschieben einer kompletten Serie (NEU/LAUFEND/ARCHIV)
-- nicht jede einzelne Episodenzeile aktualisiert werden -- bei Serien mit
-- vielen Episoden waere das unnoetig teuer.
CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    series_id INTEGER NOT NULL REFERENCES series(id) ON DELETE CASCADE,
    season_number INTEGER NOT NULL,
    episode_number INTEGER NOT NULL,
    relative_path TEXT NOT NULL,       -- Pfad relativ zum Serienordner, z.B. "Staffel 01/S01E02.mkv"

    title TEXT,                        -- Episodentitel von TMDb
    overview TEXT,                     -- Beschreibung von TMDb
    sync_status TEXT NOT NULL DEFAULT 'pending',  -- pending/ok/not_found/error
    sync_error TEXT,

    seen INTEGER NOT NULL DEFAULT 0,   -- 1 = abgehakt -- reines Metadaten-Flag, keine Dateibewegung

    added_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    missing INTEGER NOT NULL DEFAULT 0,

    UNIQUE(series_id, season_number, episode_number)
);
CREATE INDEX IF NOT EXISTS idx_episodes_series ON episodes(series_id);
CREATE INDEX IF NOT EXISTS idx_episodes_sync_status ON episodes(sync_status);
"""

# Spalten, die nachtraeglich zu bereits bestehenden Datenbanken (aeltere
# Programmversion) hinzugefuegt werden muessen.
MIGRATIONS = [
    "ALTER TABLE movies ADD COLUMN cast_names TEXT",
    "ALTER TABLE movies ADD COLUMN trailer_url TEXT",
    "ALTER TABLE movies ADD COLUMN trailer_language TEXT",
    "ALTER TABLE movies ADD COLUMN genre_names TEXT",
    "ALTER TABLE movies ADD COLUMN rewatch INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE movies ADD COLUMN folder_ctime REAL NOT NULL DEFAULT 0",
    "ALTER TABLE movies ADD COLUMN ambiguous_candidates TEXT",
    "ALTER TABLE series ADD COLUMN collapsed_seasons TEXT",
    "ALTER TABLE series ADD COLUMN episode_scroll_position INTEGER NOT NULL DEFAULT 0",
]


@dataclass
class Movie:
    id: int
    folder_name: str
    location: str
    folder_mtime: float
    video_path: Optional[str]
    has_subs: int
    tmdb_id: Optional[int]
    title: Optional[str]
    original_title: Optional[str]
    year: Optional[int]
    overview: Optional[str]
    poster_path: Optional[str]
    poster_source: Optional[str]
    cast_names: Optional[str]
    genre_names: Optional[str]
    trailer_url: Optional[str]
    trailer_language: Optional[str]
    sync_status: str
    sync_error: Optional[str]
    rewatch: int
    folder_ctime: float
    ambiguous_candidates: Optional[str]
    added_at: float
    updated_at: float
    missing: int

    @property
    def display_title(self) -> str:
        return self.title or self.folder_name

    @property
    def is_unseen(self) -> bool:
        return self.location == "NEU"

    @property
    def is_processed(self) -> bool:
        return self.sync_status in ("ok", "manual")

    @classmethod
    def field_names(cls):
        return [f.name for f in fields(cls)]


@dataclass
class Series:
    id: int
    folder_name: str
    location: str               # 'NEU', 'LAUFEND' oder 'ARCHIV'
    folder_mtime: float
    folder_ctime: float
    tmdb_id: Optional[int]
    title: Optional[str]
    original_title: Optional[str]
    first_air_year: Optional[int]
    overview: Optional[str]
    poster_path: Optional[str]
    poster_source: Optional[str]
    cast_names: Optional[str]
    genre_names: Optional[str]
    trailer_url: Optional[str]
    trailer_language: Optional[str]
    sync_status: str
    sync_error: Optional[str]
    ambiguous_candidates: Optional[str]
    added_at: float
    updated_at: float
    missing: int
    collapsed_seasons: Optional[str]
    episode_scroll_position: int

    @property
    def display_title(self) -> str:
        return self.title or self.folder_name

    @property
    def is_processed(self) -> bool:
        return self.sync_status in ("ok", "manual")

    @classmethod
    def field_names(cls):
        return [f.name for f in fields(cls)]


@dataclass
class Episode:
    id: int
    series_id: int
    season_number: int
    episode_number: int
    relative_path: str
    title: Optional[str]
    overview: Optional[str]
    sync_status: str
    sync_error: Optional[str]
    seen: int
    added_at: float
    updated_at: float
    missing: int

    @property
    def display_title(self) -> str:
        return self.title or f"Folge {self.episode_number}"

    @classmethod
    def field_names(cls):
        return [f.name for f in fields(cls)]


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        with self._lock:
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA foreign_keys=ON;")
            self.conn.executescript(SCHEMA)
            for stmt in MIGRATIONS:
                try:
                    self.conn.execute(stmt)
                except sqlite3.OperationalError:
                    pass  # Spalte existiert bereits
            self.conn.commit()

    def close(self):
        with self._lock:
            self.conn.close()

    # ---------- Lesen ----------

    def get_by_folder_name(self, folder_name: str) -> Optional[Movie]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM movies WHERE folder_name = ?", (folder_name,)
            ).fetchone()
            return Movie(**dict(row)) if row else None

    def all_folder_names(self) -> set[str]:
        with self._lock:
            rows = self.conn.execute("SELECT folder_name FROM movies").fetchall()
            return {r["folder_name"] for r in rows}

    def list_movies(self) -> list[Movie]:
        """Liefert ALLE Filme, auch als 'missing' markierte (deren Ordner auf
        der Platte nicht mehr gefunden wurde) -- die werden vom Modell mit
        geladen, damit der Diagnosefilter 'Fehlende Filme anzeigen' sie
        anzeigen kann. Standardmaessig werden sie in der Oberflaeche aber
        ausgeblendet (siehe MovieFilterProxy)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM movies ORDER BY title COLLATE NOCASE, folder_name COLLATE NOCASE"
            ).fetchall()
            return [Movie(**dict(r)) for r in rows]

    def list_pending_sync(self) -> list[Movie]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM movies WHERE missing = 0 AND sync_status IN ('pending','error','not_found') "
                "ORDER BY added_at ASC"
            ).fetchall()
            return [Movie(**dict(r)) for r in rows]

    def get(self, movie_id: int) -> Optional[Movie]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM movies WHERE id = ?", (movie_id,)).fetchone()
            return Movie(**dict(row)) if row else None

    # ---------- Schreiben ----------

    def insert_new(self, folder_name: str, location: str, folder_mtime: float,
                    video_path: Optional[str], has_subs: bool, folder_ctime: float = 0.0) -> int:
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO movies (folder_name, location, folder_mtime, video_path, has_subs,
                                        sync_status, added_at, updated_at, missing, folder_ctime)
                   VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, 0, ?)""",
                (folder_name, location, folder_mtime, video_path, int(has_subs), now, now, folder_ctime),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_scan_fields(self, folder_name: str, location: str, folder_mtime: float,
                            video_path: Optional[str], has_subs: bool, folder_ctime: float = 0.0) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE movies SET location=?, folder_mtime=?, video_path=?, has_subs=?,
                                      updated_at=?, missing=0, folder_ctime=?
                   WHERE folder_name=?""",
                (location, folder_mtime, video_path, int(has_subs), time.time(), folder_ctime, folder_name),
            )
            self.conn.commit()

    def mark_missing(self, folder_names: Iterable[str]) -> None:
        names = list(folder_names)
        if not names:
            return
        with self._lock:
            self.conn.executemany(
                "UPDATE movies SET missing=1, updated_at=? WHERE folder_name=?",
                [(time.time(), n) for n in names],
            )
            self.conn.commit()

    def set_rewatch(self, movie_id: int, flag: bool) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET rewatch=?, updated_at=? WHERE id=?",
                (int(flag), time.time(), movie_id),
            )
            self.conn.commit()

    def delete_movie(self, movie_id: int) -> None:
        """Entfernt den Datenbankeintrag endgueltig (der Ordner selbst wird
        davon NICHT beruehrt -- siehe player.delete_movie_to_trash, das den
        Ordner zuerst in den Papierkorb verschiebt und danach diese Methode
        aufruft)."""
        with self._lock:
            self.conn.execute("DELETE FROM movies WHERE id=?", (movie_id,))
            self.conn.commit()

    def set_location(self, movie_id: int, location: str, video_path: Optional[str]) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET location=?, video_path=?, updated_at=? WHERE id=?",
                (location, video_path, time.time(), movie_id),
            )
            self.conn.commit()

    def set_metadata_ok(self, movie_id: int, tmdb_id: Optional[int], title: str,
                         original_title: Optional[str], year: Optional[int],
                         overview: str, poster_path: Optional[str],
                         cast_names: Optional[str] = None,
                         trailer_url: Optional[str] = None,
                         trailer_language: Optional[str] = None,
                         genre_names: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE movies SET tmdb_id=?, title=?, original_title=?, year=?, overview=?,
                                      poster_path=?, poster_source='tmdb', cast_names=?,
                                      genre_names=?, trailer_url=?, trailer_language=?,
                                      sync_status='ok', sync_error=NULL, ambiguous_candidates=NULL,
                                      updated_at=?
                   WHERE id=?""",
                (tmdb_id, title, original_title, year, overview, poster_path,
                 cast_names, genre_names, trailer_url, trailer_language, time.time(), movie_id),
            )
            self.conn.commit()

    def set_manual_edit(self, movie_id: int, title: Optional[str] = None,
                         overview: Optional[str] = None, cast_names: Optional[str] = None,
                         genre_names: Optional[str] = None, trailer_url: Optional[str] = None) -> None:
        """Speichert von Hand bearbeitete Filminfos. Nur uebergebene Felder
        (nicht None) werden geaendert. Ein Film, der bisher nicht erfolgreich
        synchronisiert war (pending/not_found/error/ambiguous), gilt danach
        als 'manual' -- damit taucht er nicht mehr im Diagnosefilter
        'nicht synchronisiert' auf, sobald von Hand Infos ergaenzt wurden."""
        sets = []
        params: list = []
        if title is not None:
            sets.append("title=?")
            params.append(title)
        if overview is not None:
            sets.append("overview=?")
            params.append(overview)
        if cast_names is not None:
            sets.append("cast_names=?")
            params.append(cast_names)
        if genre_names is not None:
            sets.append("genre_names=?")
            params.append(genre_names)
        if trailer_url is not None:
            sets.append("trailer_url=?")
            params.append(trailer_url)
            sets.append("trailer_language=NULL")
        if not sets:
            return
        sets.append("sync_status = CASE WHEN sync_status != 'ok' THEN 'manual' ELSE sync_status END")
        sets.append("sync_error=NULL")
        sets.append("ambiguous_candidates=NULL")
        sets.append("updated_at=?")
        params.append(time.time())
        params.append(movie_id)
        sql = f"UPDATE movies SET {', '.join(sets)} WHERE id=?"
        with self._lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def set_metadata_not_found(self, movie_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET sync_status='not_found', title=COALESCE(title, folder_name), "
                "updated_at=? WHERE id=?",
                (time.time(), movie_id),
            )
            self.conn.commit()

    def set_metadata_ambiguous(self, movie_id: int, note: str, candidates_json: str | None = None) -> None:
        """Mehrere gleichnamige TMDb-Treffer (typischerweise ein Remake) ohne
        Jahr im Dateinamen zur Unterscheidung -- wird NICHT automatisch
        geraten, sondern zur manuellen Klaerung markiert. candidates_json
        enthaelt die zur Auswahl stehenden Filme (siehe
        TmdbClient.search_movie) als JSON-Liste, damit das Detail-Fenster
        direkt ein Auswahl-Dropdown anbieten kann."""
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET sync_status='ambiguous', sync_error=?, "
                "ambiguous_candidates=?, title=COALESCE(title, folder_name), "
                "updated_at=? WHERE id=?",
                (note, candidates_json, time.time(), movie_id),
            )
            self.conn.commit()

    def list_ok_missing_extra_info(self) -> list[Movie]:
        """Bereits erfolgreich synchronisierte Filme (sync_status='ok') mit
        bekannter TMDb-ID, denen aber noch Besetzung, Genre oder Trailer
        fehlt (typischerweise, weil sie mit einer aelteren CineVault-Version
        synchronisiert wurden, bevor diese Felder unterstuetzt wurden)."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM movies WHERE missing=0 AND sync_status='ok' "
                "AND tmdb_id IS NOT NULL AND ("
                "  genre_names IS NULL OR genre_names='' OR "
                "  cast_names IS NULL OR cast_names='' OR "
                "  trailer_url IS NULL OR trailer_url=''"
                ")"
            ).fetchall()
            return [Movie(**dict(r)) for r in rows]

    def set_extra_details(self, movie_id: int, cast_names: Optional[str] = None,
                           genre_names: Optional[str] = None, trailer_url: Optional[str] = None,
                           trailer_language: Optional[str] = None) -> None:
        """Ergaenzt NUR Besetzung/Genre/Trailer eines bereits zugeordneten
        Films (per bekannter TMDb-ID nachgeladen). Nur uebergebene (nicht
        None) Felder werden geschrieben; Titel, Beschreibung, Cover und
        sync_status bleiben in jedem Fall unveraendert, damit z.B. eine per
        Mehrdeutigkeits-Dropdown getroffene Auswahl oder eine von Hand
        bearbeitete Beschreibung dabei nicht verloren geht."""
        sets = []
        params: list = []
        if genre_names is not None:
            sets.append("genre_names=?")
            params.append(genre_names)
        if cast_names is not None:
            sets.append("cast_names=?")
            params.append(cast_names)
        if trailer_url is not None:
            sets.append("trailer_url=?")
            params.append(trailer_url)
            sets.append("trailer_language=?")
            params.append(trailer_language)
        if not sets:
            return
        sets.append("updated_at=?")
        params.append(time.time())
        params.append(movie_id)
        sql = f"UPDATE movies SET {', '.join(sets)} WHERE id=?"
        with self._lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def set_metadata_error(self, movie_id: int, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET sync_status='error', sync_error=?, updated_at=? WHERE id=?",
                (error, time.time(), movie_id),
            )
            self.conn.commit()

    def set_manual_cover(self, movie_id: int, poster_path: str) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE movies SET poster_path=?, poster_source='manual',
                                      sync_status=CASE WHEN sync_status='pending' THEN 'manual' ELSE sync_status END,
                                      updated_at=? WHERE id=?""",
                (poster_path, time.time(), movie_id),
            )
            self.conn.commit()

    def set_title_override(self, movie_id: int, title: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET title=?, updated_at=? WHERE id=?",
                (title, time.time(), movie_id),
            )
            self.conn.commit()

    def reset_sync(self, movie_id: int) -> None:
        """Erzwingt eine erneute Synchronisierung dieses einen Films."""
        with self._lock:
            self.conn.execute(
                "UPDATE movies SET sync_status='pending', sync_error=NULL, updated_at=? WHERE id=?",
                (time.time(), movie_id),
            )
            self.conn.commit()

    def delete_missing_older_than(self, seconds: float) -> None:
        """Optionaler Aufraeumschritt: seit langem fehlende Eintraege endgueltig loeschen."""
        cutoff = time.time() - seconds
        with self._lock:
            self.conn.execute("DELETE FROM movies WHERE missing=1 AND updated_at < ?", (cutoff,))
            self.conn.commit()

    # ================================================================
    # Serien (komplett eigener Bereich, siehe database.py Kopfkommentar
    # bei SCHEMA) -- Methoden bewusst parallel zu den Film-Methoden oben
    # aufgebaut statt generalisiert, damit der Code fuer beide Bereiche fuer
    # sich lesbar bleibt.
    # ================================================================

    # ---------- Serien: Lesen ----------

    def get_series_by_folder_name(self, folder_name: str) -> Optional[Series]:
        with self._lock:
            row = self.conn.execute(
                "SELECT * FROM series WHERE folder_name = ?", (folder_name,)
            ).fetchone()
            return Series(**dict(row)) if row else None

    def all_series_folder_names(self) -> set[str]:
        with self._lock:
            rows = self.conn.execute("SELECT folder_name FROM series").fetchall()
            return {r["folder_name"] for r in rows}

    def list_series(self) -> list[Series]:
        """Liefert ALLE Serien, auch als 'missing' markierte -- analog zu
        list_movies() werden die in der Oberflaeche standardmaessig
        ausgeblendet, nicht bereits hier."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM series ORDER BY title COLLATE NOCASE, folder_name COLLATE NOCASE"
            ).fetchall()
            return [Series(**dict(r)) for r in rows]

    def list_series_pending_sync(self) -> list[Series]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM series WHERE missing = 0 AND sync_status IN ('pending','error','not_found') "
                "ORDER BY added_at ASC"
            ).fetchall()
            return [Series(**dict(r)) for r in rows]

    def get_series(self, series_id: int) -> Optional[Series]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()
            return Series(**dict(row)) if row else None

    # ---------- Serien: Schreiben ----------

    def insert_new_series(self, folder_name: str, location: str, folder_mtime: float,
                           folder_ctime: float = 0.0) -> int:
        now = time.time()
        with self._lock:
            cur = self.conn.execute(
                """INSERT INTO series (folder_name, location, folder_mtime, folder_ctime,
                                        sync_status, added_at, updated_at, missing)
                   VALUES (?, ?, ?, ?, 'pending', ?, ?, 0)""",
                (folder_name, location, folder_mtime, folder_ctime, now, now),
            )
            self.conn.commit()
            return cur.lastrowid

    def update_series_scan_fields(self, folder_name: str, location: str, folder_mtime: float,
                                   folder_ctime: float = 0.0) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE series SET location=?, folder_mtime=?, updated_at=?, missing=0, folder_ctime=?
                   WHERE folder_name=?""",
                (location, folder_mtime, time.time(), folder_ctime, folder_name),
            )
            self.conn.commit()

    def mark_series_missing(self, folder_names: Iterable[str]) -> None:
        names = list(folder_names)
        if not names:
            return
        with self._lock:
            for n in names:
                row = self.conn.execute(
                    "SELECT id FROM series WHERE folder_name=?", (n,)).fetchone()
                self.conn.execute(
                    "UPDATE series SET missing=1, updated_at=? WHERE folder_name=?",
                    (time.time(), n),
                )
                if row:
                    self.conn.execute(
                        "UPDATE episodes SET missing=1, updated_at=? WHERE series_id=?",
                        (time.time(), row["id"]),
                    )
            self.conn.commit()

    def set_series_location(self, series_id: int, location: str) -> None:
        """Verschiebt eine komplette Serie zwischen NEU/LAUFEND/ARCHIV.
        Bewusst OHNE dabei die einzelnen Episoden-Zeilen anzufassen -- deren
        Pfad wird ja ohnehin erst bei Bedarf aus series.location +
        episode.relative_path zusammengesetzt (siehe series_scanner.py),
        nicht direkt gespeichert."""
        with self._lock:
            self.conn.execute(
                "UPDATE series SET location=?, updated_at=? WHERE id=?",
                (location, time.time(), series_id),
            )
            self.conn.commit()

    def set_series_metadata_ok(self, series_id: int, tmdb_id: Optional[int], title: str,
                                original_title: Optional[str], first_air_year: Optional[int],
                                overview: str, poster_path: Optional[str],
                                cast_names: Optional[str] = None,
                                trailer_url: Optional[str] = None,
                                trailer_language: Optional[str] = None,
                                genre_names: Optional[str] = None) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE series SET tmdb_id=?, title=?, original_title=?, first_air_year=?, overview=?,
                                      poster_path=?, poster_source='tmdb', cast_names=?,
                                      genre_names=?, trailer_url=?, trailer_language=?,
                                      sync_status='ok', sync_error=NULL, ambiguous_candidates=NULL,
                                      updated_at=?
                   WHERE id=?""",
                (tmdb_id, title, original_title, first_air_year, overview, poster_path,
                 cast_names, genre_names, trailer_url, trailer_language, time.time(), series_id),
            )
            self.conn.commit()

    def set_series_manual_edit(self, series_id: int, title: Optional[str] = None,
                                overview: Optional[str] = None, cast_names: Optional[str] = None,
                                genre_names: Optional[str] = None, trailer_url: Optional[str] = None) -> None:
        sets = []
        params: list = []
        if title is not None:
            sets.append("title=?")
            params.append(title)
        if overview is not None:
            sets.append("overview=?")
            params.append(overview)
        if cast_names is not None:
            sets.append("cast_names=?")
            params.append(cast_names)
        if genre_names is not None:
            sets.append("genre_names=?")
            params.append(genre_names)
        if trailer_url is not None:
            sets.append("trailer_url=?")
            params.append(trailer_url)
            sets.append("trailer_language=NULL")
        if not sets:
            return
        sets.append("sync_status = CASE WHEN sync_status != 'ok' THEN 'manual' ELSE sync_status END")
        sets.append("sync_error=NULL")
        sets.append("ambiguous_candidates=NULL")
        sets.append("updated_at=?")
        params.append(time.time())
        params.append(series_id)
        sql = f"UPDATE series SET {', '.join(sets)} WHERE id=?"
        with self._lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def set_series_metadata_not_found(self, series_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE series SET sync_status='not_found', title=COALESCE(title, folder_name), "
                "updated_at=? WHERE id=?",
                (time.time(), series_id),
            )
            self.conn.commit()

    def set_series_metadata_ambiguous(self, series_id: int, note: str,
                                       candidates_json: str | None = None) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE series SET sync_status='ambiguous', sync_error=?, "
                "ambiguous_candidates=?, title=COALESCE(title, folder_name), "
                "updated_at=? WHERE id=?",
                (note, candidates_json, time.time(), series_id),
            )
            self.conn.commit()

    def set_series_metadata_error(self, series_id: int, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE series SET sync_status='error', sync_error=?, updated_at=? WHERE id=?",
                (error, time.time(), series_id),
            )
            self.conn.commit()

    def set_series_manual_cover(self, series_id: int, poster_path: str) -> None:
        with self._lock:
            self.conn.execute(
                """UPDATE series SET poster_path=?, poster_source='manual',
                                      sync_status=CASE WHEN sync_status='pending' THEN 'manual' ELSE sync_status END,
                                      updated_at=? WHERE id=?""",
                (poster_path, time.time(), series_id),
            )
            self.conn.commit()

    def reset_series_sync(self, series_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE series SET sync_status='pending', sync_error=NULL, updated_at=? WHERE id=?",
                (time.time(), series_id),
            )
            self.conn.commit()

    def set_series_ui_state(self, series_id: int, collapsed_seasons: Optional[str] = None,
                             episode_scroll_position: Optional[int] = None) -> None:
        """Rein kosmetischer Merkzustand (welche Staffeln eingeklappt waren,
        Scrollposition der Episodenliste) -- absichtlich OHNE updated_at
        anzufassen, damit das nicht wie eine inhaltliche Aenderung wirkt."""
        sets = []
        params: list = []
        if collapsed_seasons is not None:
            sets.append("collapsed_seasons=?")
            params.append(collapsed_seasons)
        if episode_scroll_position is not None:
            sets.append("episode_scroll_position=?")
            params.append(episode_scroll_position)
        if not sets:
            return
        params.append(series_id)
        sql = f"UPDATE series SET {', '.join(sets)} WHERE id=?"
        with self._lock:
            self.conn.execute(sql, params)
            self.conn.commit()

    def delete_series(self, series_id: int) -> None:
        """Entfernt Serie + all ihre Episoden endgueltig aus der Datenbank
        (der Ordner selbst wird davon NICHT beruehrt). PRAGMA foreign_keys
        ist aktiviert (siehe __init__), daher loescht SQLite die
        zugehoerigen episodes-Zeilen automatisch mit (ON DELETE CASCADE)."""
        with self._lock:
            self.conn.execute("DELETE FROM series WHERE id=?", (series_id,))
            self.conn.commit()

    # ---------- Episoden: Lesen ----------

    def list_episodes_for_series(self, series_id: int) -> list[Episode]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM episodes WHERE series_id=? "
                "ORDER BY season_number ASC, episode_number ASC",
                (series_id,),
            ).fetchall()
            return [Episode(**dict(r)) for r in rows]

    def get_episode(self, episode_id: int) -> Optional[Episode]:
        with self._lock:
            row = self.conn.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            return Episode(**dict(row)) if row else None

    def list_episodes_pending_sync(self) -> list[Episode]:
        """Ueber ALLE Serien hinweg -- fuer den globalen 'Serien
        synchronisieren'-Durchlauf, analog zu list_pending_sync() bei Filmen."""
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM episodes WHERE missing=0 AND sync_status IN ('pending','error','not_found') "
                "ORDER BY added_at ASC"
            ).fetchall()
            return [Episode(**dict(r)) for r in rows]

    def count_episodes_for_series(self, series_id: int) -> tuple[int, int]:
        """Gibt (gesamt, abgehakt) zurueck -- praktisch fuer eine
        Fortschrittsanzeige ('12 von 24 gesehen') in der Oberflaeche."""
        with self._lock:
            row = self.conn.execute(
                "SELECT COUNT(*) AS total, COALESCE(SUM(seen), 0) AS seen_count "
                "FROM episodes WHERE series_id=? AND missing=0",
                (series_id,),
            ).fetchone()
            return int(row["total"]), int(row["seen_count"])

    # ---------- Episoden: Schreiben ----------

    def upsert_episode(self, series_id: int, season_number: int, episode_number: int,
                        relative_path: str) -> int:
        """Legt eine Episode an oder aktualisiert (bei Wiedererkennen anhand
        Staffel+Episodennummer) nur ihren Pfad -- 'seen'-Status und bereits
        geladene TMDb-Metadaten bleiben dabei unangetastet, genau wie bei
        update_scan_fields() fuer Filme."""
        now = time.time()
        with self._lock:
            existing = self.conn.execute(
                "SELECT id FROM episodes WHERE series_id=? AND season_number=? AND episode_number=?",
                (series_id, season_number, episode_number),
            ).fetchone()
            if existing:
                self.conn.execute(
                    "UPDATE episodes SET relative_path=?, missing=0, updated_at=? WHERE id=?",
                    (relative_path, now, existing["id"]),
                )
                self.conn.commit()
                return existing["id"]
            cur = self.conn.execute(
                """INSERT INTO episodes (series_id, season_number, episode_number, relative_path,
                                          sync_status, seen, added_at, updated_at, missing)
                   VALUES (?, ?, ?, ?, 'pending', 0, ?, ?, 0)""",
                (series_id, season_number, episode_number, relative_path, now, now),
            )
            self.conn.commit()
            return cur.lastrowid

    def mark_episodes_missing_except(self, series_id: int, keep_ids: Iterable[int]) -> None:
        """Markiert alle Episoden einer Serie als 'missing', die beim
        letzten Scan NICHT mehr gefunden wurden (Datei geloescht/umbenannt) --
        keep_ids sind die IDs der gerade tatsaechlich vorgefundenen Episoden."""
        keep = set(keep_ids)
        with self._lock:
            rows = self.conn.execute(
                "SELECT id FROM episodes WHERE series_id=?", (series_id,)
            ).fetchall()
            stale_ids = [r["id"] for r in rows if r["id"] not in keep]
            if stale_ids:
                self.conn.executemany(
                    "UPDATE episodes SET missing=1, updated_at=? WHERE id=?",
                    [(time.time(), eid) for eid in stale_ids],
                )
                self.conn.commit()

    def set_episode_seen(self, episode_id: int, flag: bool) -> None:
        """Reines Metadaten-Flag ('abgehakt') -- bewegt KEINE Datei, anders
        als bei Filmen (dort ist NEU/ARCHIV = tatsaechliche Ordnerbewegung).
        Erst wenn die ganze Serie fertig ist, wandert der Serienordner
        insgesamt (siehe set_series_location)."""
        with self._lock:
            self.conn.execute(
                "UPDATE episodes SET seen=?, updated_at=? WHERE id=?",
                (int(flag), time.time(), episode_id),
            )
            self.conn.commit()

    def set_all_episodes_seen_for_series(self, series_id: int, flag: bool) -> int:
        """Setzt das 'gesehen'-Flag fuer ALLE (nicht als fehlend markierten)
        Episoden einer Serie auf einmal -- EIN SQL-Befehl statt eine
        Einzelabfrage pro Episode (praktisch v.a. beim erstmaligen Einpflegen
        bereits komplett geschauter Serien, auch bei welchen mit hunderten
        Episoden). Gibt die Anzahl der tatsaechlich betroffenen Episoden
        zurueck."""
        with self._lock:
            cur = self.conn.execute(
                "UPDATE episodes SET seen=?, updated_at=? WHERE series_id=? AND missing=0",
                (int(flag), time.time(), series_id),
            )
            self.conn.commit()
            return cur.rowcount

    def set_episode_metadata_ok(self, episode_id: int, title: Optional[str],
                                 overview: Optional[str]) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE episodes SET title=?, overview=?, sync_status='ok', updated_at=? WHERE id=?",
                (title, overview, time.time(), episode_id),
            )
            self.conn.commit()

    def set_episode_metadata_not_found(self, episode_id: int) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE episodes SET sync_status='not_found', updated_at=? WHERE id=?",
                (time.time(), episode_id),
            )
            self.conn.commit()

    def set_episode_metadata_error(self, episode_id: int, error: str) -> None:
        with self._lock:
            self.conn.execute(
                "UPDATE episodes SET sync_status='error', sync_error=?, updated_at=? WHERE id=?",
                (error, time.time(), episode_id),
            )
            self.conn.commit()
