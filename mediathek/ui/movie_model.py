from __future__ import annotations

from PySide6.QtCore import (QAbstractListModel, QModelIndex, QSortFilterProxyModel,
                             Qt, QSize)
from PySide6.QtGui import QPixmap

from ..database import Movie
from .constants import POSTER_H, POSTER_W

TITLE_ROLE = Qt.UserRole + 1
MOVIE_ID_ROLE = Qt.UserRole + 2
POSTER_PATH_ROLE = Qt.UserRole + 3
LOCATION_ROLE = Qt.UserRole + 4
YEAR_ROLE = Qt.UserRole + 5
SYNC_STATUS_ROLE = Qt.UserRole + 6
OVERVIEW_ROLE = Qt.UserRole + 7
GENRE_ROLE = Qt.UserRole + 8          # Genres, kommagetrennt
COMPLETENESS_ROLE = Qt.UserRole + 9   # 'complete' / 'partial' / 'missing'
REWATCH_ROLE = Qt.UserRole + 10       # True = zum "nochmal ansehen" vorgemerkt
FOLDER_CTIME_ROLE = Qt.UserRole + 11  # Windows-Erstelldatum des Ordners
IS_MISSING_ROLE = Qt.UserRole + 12    # True = Ordner auf der Platte nicht mehr gefunden

PLACEHOLDER_SIZE = QSize(POSTER_W, POSTER_H)


def movie_completeness(movie: Movie) -> str:
    """Bewertet, wie vollstaendig die Filminfos sind -- unabhaengig davon, ob
    Cover/Beschreibung automatisch per TMDb oder von Hand eingetragen wurden:
    'missing'  = weder Cover noch Beschreibung vorhanden
    'partial'  = nur eines von beiden vorhanden
    'complete' = beides vorhanden"""
    has_cover = bool(movie.poster_path)
    has_overview = bool(movie.overview and movie.overview.strip())
    if has_cover and has_overview:
        return "complete"
    if has_cover or has_overview:
        return "partial"
    return "missing"


class MovieListModel(QAbstractListModel):
    """Haelt die komplette Filmliste im Speicher (bei ~2000 Eintraegen unkritisch)
    und liefert Daten fuer die virtualisierte QListView (nur sichtbare Zellen
    fragen wirklich Pixmaps an).

    Cover werden hier EINMALIG passgenau auf POSTER_W x POSTER_H zugeschnitten
    (wie CSS 'object-fit: cover') und gecacht, statt bei jedem einzelnen
    Paint-Aufruf des Delegates neu skaliert zu werden -- das ist der groesste
    Hebel gegen ruckelndes Scrollen bei grossen Listen. Das Ergebnis hat
    IMMER exakt die Zielgroesse in normalen (nicht HiDPI-skalierten) Pixeln,
    ohne Sonderbehandlung fuer devicePixelRatio -- das haelt die Zeichenlogik
    im Delegate simpel und fehlerfrei."""

    def __init__(self, thumbs_dir, parent=None):
        super().__init__(parent)
        self._movies: list[Movie] = []
        self._thumbs_dir = thumbs_dir
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._placeholder = self._make_placeholder()

    def _make_placeholder(self) -> QPixmap:
        pm = QPixmap(PLACEHOLDER_SIZE)
        pm.fill(Qt.transparent)
        return pm

    def set_movies(self, movies: list[Movie]) -> None:
        self.beginResetModel()
        self._movies = movies
        self.endResetModel()

    def update_movie(self, movie: Movie) -> None:
        for i, m in enumerate(self._movies):
            if m.id == movie.id:
                self._movies[i] = movie
                self._pixmap_cache.pop(m.folder_name, None)
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                return
        # Nicht gefunden -> neu anhaengen (z.B. frisch synchronisierter Film)
        self.beginInsertRows(QModelIndex(), len(self._movies), len(self._movies))
        self._movies.append(movie)
        self.endInsertRows()

    def movie_at(self, row: int) -> Movie | None:
        if 0 <= row < len(self._movies):
            return self._movies[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._movies)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        movie = self._movies[index.row()]

        if role in (Qt.DisplayRole, TITLE_ROLE):
            # In der Kachelansicht bewusst der ROHE Ordnername (nicht der
            # TMDb-Titel) -- das entspricht 1:1 der eigenen Dateibenennung
            # (z.B. bei Reihen mit "Teil 1/2/3") und macht falsch zugeordnete
            # TMDb-Daten auf den ersten Blick erkennbar. Im Detail-Fenster
            # wird weiterhin der TMDb-Titel angezeigt.
            return movie.folder_name
        if role == Qt.DecorationRole:
            return self._pixmap_for(movie)
        if role == MOVIE_ID_ROLE:
            return movie.id
        if role == POSTER_PATH_ROLE:
            return movie.poster_path
        if role == LOCATION_ROLE:
            return movie.location
        if role == YEAR_ROLE:
            return movie.year
        if role == SYNC_STATUS_ROLE:
            return movie.sync_status
        if role == OVERVIEW_ROLE:
            return movie.overview
        if role == GENRE_ROLE:
            return movie.genre_names
        if role == COMPLETENESS_ROLE:
            return movie_completeness(movie)
        if role == REWATCH_ROLE:
            return bool(movie.rewatch)
        if role == FOLDER_CTIME_ROLE:
            return movie.folder_ctime
        if role == IS_MISSING_ROLE:
            return bool(movie.missing)
        if role == Qt.ToolTipRole:
            y = f" ({movie.year})" if movie.year else ""
            if movie.title and movie.title != movie.folder_name:
                return f"{movie.folder_name}\nTMDb: {movie.display_title}{y}"
            return f"{movie.folder_name}{y}"
        return None

    def _pixmap_for(self, movie: Movie) -> QPixmap:
        if not movie.poster_path:
            return self._placeholder
        cached = self._pixmap_cache.get(movie.folder_name)
        if cached is not None:
            return cached
        full_path = self._thumbs_dir / movie.poster_path
        raw = QPixmap(str(full_path))
        if raw.isNull():
            pm = self._placeholder
        else:
            pm = self._fit_and_crop(raw, POSTER_W, POSTER_H)
        self._pixmap_cache[movie.folder_name] = pm
        return pm

    @staticmethod
    def _fit_and_crop(pixmap: QPixmap, width: int, height: int) -> QPixmap:
        """Skaliert ein Bild verzerrungsfrei so, dass es das Zielrechteck
        vollstaendig ausfuellt (wie CSS 'object-fit: cover'), und schneidet
        ueberstehende Raender mittig ab. Das Ergebnis hat garantiert exakt
        'width' x 'height' Pixel."""
        scaled = pixmap.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - width) // 2)
        y = max(0, (scaled.height() - height) // 2)
        return scaled.copy(x, y, width, height)

    def invalidate_pixmap(self, folder_name: str) -> None:
        self._pixmap_cache.pop(folder_name, None)

    def remove_movie(self, movie_id: int) -> None:
        for i, m in enumerate(self._movies):
            if m.id == movie_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._movies[i]
                self.endRemoveRows()
                self._pixmap_cache.pop(m.folder_name, None)
                return


class MovieFilterProxy(QSortFilterProxyModel):
    FILTER_ALL = "all"
    FILTER_UNSEEN = "unseen"
    FILTER_SEEN = "seen"
    FILTER_REWATCH = "rewatch"

    SORT_TITLE = "title"
    SORT_ADDED = "added"      # Windows-Erstelldatum des Ordners, neueste zuerst
    SORT_YEAR = "year"        # Erscheinungsjahr (TMDb), neueste zuerst

    # Diagnosefilter (siehe Einstellungen-Dialog)
    DIAG_NONE = None
    DIAG_UNSYNCED = "unsynced"
    DIAG_NO_OVERVIEW = "no_overview"
    DIAG_NO_COVER = "no_cover"
    DIAG_AMBIGUOUS = "ambiguous_only"
    DIAG_MISSING = "missing_only"

    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_mode = self.FILTER_ALL
        self._search_text = ""
        self._diagnostic_filter = self.DIAG_NONE
        self._genre_filter: str | None = None
        self._sort_mode = self.SORT_TITLE
        self.setSortCaseSensitivity(Qt.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def set_filter_mode(self, mode: str) -> None:
        self._filter_mode = mode
        self.invalidateFilter()

    def filter_mode(self) -> str:
        return self._filter_mode

    def set_search_text(self, text: str) -> None:
        self._search_text = text.strip().lower()
        self.invalidateFilter()

    def set_diagnostic_filter(self, mode: str | None) -> None:
        """Versteckter Diagnosefilter aus den Einstellungen: 'unsynced'
        (nicht erfolgreich synchronisiert), 'no_overview' (keine Beschreibung)
        oder 'no_cover' (kein Cover). None = kein Diagnosefilter aktiv."""
        self._diagnostic_filter = mode
        self.invalidateFilter()

    def diagnostic_filter(self) -> str | None:
        return self._diagnostic_filter

    def set_genre_filter(self, genre: str | None) -> None:
        self._genre_filter = genre
        self.invalidateFilter()

    def genre_filter(self) -> str | None:
        return self._genre_filter

    def set_sort_mode(self, mode: str) -> None:
        self._sort_mode = mode
        # Qt erkennt "sort(0, Ascending)" als unveraendert, wenn Spalte/
        # Richtung schon vorher genau so gesetzt waren, und sortiert dann
        # NICHT neu -- obwohl sich unser lessThan() ja je nach _sort_mode
        # unterschiedlich verhaelt. Sortierung daher erst per sort(-1)
        # explizit "ausschalten", dann wieder aktivieren -> erzwingt in
        # jedem Fall ein echtes Neusortieren.
        self.sort(-1)
        self.sort(0, Qt.AscendingOrder)

    def sort_mode(self) -> str:
        return self._sort_mode

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        model = self.sourceModel()
        if self._sort_mode == self.SORT_ADDED:
            lv = model.data(left, FOLDER_CTIME_ROLE) or 0
            rv = model.data(right, FOLDER_CTIME_ROLE) or 0
            return lv < rv
        if self._sort_mode == self.SORT_YEAR:
            # Filme ohne bekanntes Jahr (noch nicht synchronisiert) rutschen
            # ans Ende, unabhaengig von der Richtung -- daher hier bewusst
            # 0 als Ersatzwert (kleiner als jedes echte Jahr).
            lv = model.data(left, YEAR_ROLE) or 0
            rv = model.data(right, YEAR_ROLE) or 0
            if lv != rv:
                return lv > rv  # neuestes Jahr zuerst
            lt = str(model.data(left, TITLE_ROLE) or "").lower()
            rt = str(model.data(right, TITLE_ROLE) or "").lower()
            return lt < rt  # bei gleichem Jahr alphabetisch als Tie-Breaker
        lt = str(model.data(left, TITLE_ROLE) or "").lower()
        rt = str(model.data(right, TITLE_ROLE) or "").lower()
        return lt < rt

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:
        model = self.sourceModel()
        idx = model.index(source_row, 0, source_parent)
        is_missing = bool(model.data(idx, IS_MISSING_ROLE))

        if self._diagnostic_filter == self.DIAG_MISSING:
            # Eigener, einfacher Zweig: zeigt WIRKLICH alle fehlenden Filme,
            # unabhaengig vom Ort-Filter (Alle/Ungesehen/Gesehen/Rewatch) --
            # der bezieht sich ja auf den zuletzt bekannten Ort, der bei
            # einem geloeschten Ordner nicht mehr sonderlich aussagekraeftig
            # ist. Die Suche bleibt trotzdem nutzbar. Praktisch als
            # Schnellfilter, um NUR die fehlenden auf einen Blick zu sehen --
            # in der normalen Uebersicht bleiben sie naemlich ganz regulaer
            # sichtbar (siehe unten), nur mit rotem "MISSING"-Badge markiert.
            if not is_missing:
                return False
            if self._search_text:
                title = str(model.data(idx, TITLE_ROLE) or "").lower()
                if self._search_text not in title:
                    return False
            return True

        location = model.data(idx, LOCATION_ROLE)

        if self._filter_mode == self.FILTER_UNSEEN and location != "NEU":
            return False
        if self._filter_mode == self.FILTER_SEEN and location != "ARCHIV":
            return False
        if self._filter_mode == self.FILTER_REWATCH and not model.data(idx, REWATCH_ROLE):
            return False

        if self._diagnostic_filter == self.DIAG_UNSYNCED:
            sync_status = model.data(idx, SYNC_STATUS_ROLE)
            if sync_status not in ("pending", "not_found", "error", "ambiguous"):
                return False
        elif self._diagnostic_filter == self.DIAG_NO_OVERVIEW:
            if str(model.data(idx, OVERVIEW_ROLE) or "").strip():
                return False
        elif self._diagnostic_filter == self.DIAG_NO_COVER:
            if model.data(idx, POSTER_PATH_ROLE):
                return False
        elif self._diagnostic_filter == self.DIAG_AMBIGUOUS:
            if model.data(idx, SYNC_STATUS_ROLE) != "ambiguous":
                return False

        if self._genre_filter:
            genres = str(model.data(idx, GENRE_ROLE) or "")
            genre_list = [g.strip().lower() for g in genres.split(",") if g.strip()]
            if self._genre_filter.lower() not in genre_list:
                return False

        if self._search_text:
            title = str(model.data(idx, TITLE_ROLE) or "").lower()
            if self._search_text not in title:
                return False
        return True
