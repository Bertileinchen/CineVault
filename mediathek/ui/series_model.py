from __future__ import annotations

from PySide6.QtCore import QAbstractListModel, QModelIndex, QSortFilterProxyModel, Qt, QSize
from PySide6.QtGui import QPixmap

from ..database import Series
from .constants import POSTER_H, POSTER_W

TITLE_ROLE = Qt.UserRole + 1
SERIES_ID_ROLE = Qt.UserRole + 2
POSTER_PATH_ROLE = Qt.UserRole + 3
LOCATION_ROLE = Qt.UserRole + 4
YEAR_ROLE = Qt.UserRole + 5
SYNC_STATUS_ROLE = Qt.UserRole + 6
OVERVIEW_ROLE = Qt.UserRole + 7
GENRE_ROLE = Qt.UserRole + 8
IS_MISSING_ROLE = Qt.UserRole + 9
PROGRESS_ROLE = Qt.UserRole + 10  # (gesehen, gesamt) -- Tupel
FOLDER_CTIME_ROLE = Qt.UserRole + 11  # Windows-Erstelldatum des Ordners

PLACEHOLDER_SIZE = QSize(POSTER_W, POSTER_H)


class SeriesListModel(QAbstractListModel):
    """Haelt die komplette Serienliste im Speicher -- analog zu
    MovieListModel bei Filmen. Der Fortschritt (X/Y Episoden gesehen) wird
    hier bewusst vom Aufrufer mitgeliefert (siehe set_series()), statt bei
    jedem data()-Aufruf neu aus der Datenbank nachgefragt zu werden."""

    def __init__(self, thumbs_dir, parent=None):
        super().__init__(parent)
        self._series: list[Series] = []
        self._progress: dict[int, tuple[int, int]] = {}
        self._thumbs_dir = thumbs_dir
        self._pixmap_cache: dict[str, QPixmap] = {}
        self._placeholder = self._make_placeholder()

    def _make_placeholder(self) -> QPixmap:
        pm = QPixmap(PLACEHOLDER_SIZE)
        pm.fill(Qt.transparent)
        return pm

    def set_series(self, series_list: list[Series], progress: dict[int, tuple[int, int]]) -> None:
        self.beginResetModel()
        self._series = series_list
        self._progress = progress
        self.endResetModel()

    def update_series(self, series: Series, progress: tuple[int, int] | None = None) -> None:
        if progress is not None:
            self._progress[series.id] = progress
        for i, s in enumerate(self._series):
            if s.id == series.id:
                self._series[i] = series
                self._pixmap_cache.pop(s.folder_name, None)
                idx = self.index(i)
                self.dataChanged.emit(idx, idx)
                return
        self.beginInsertRows(QModelIndex(), len(self._series), len(self._series))
        self._series.append(series)
        self.endInsertRows()

    def series_at(self, row: int) -> Series | None:
        if 0 <= row < len(self._series):
            return self._series[row]
        return None

    def rowCount(self, parent=QModelIndex()) -> int:
        return len(self._series)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole):
        if not index.isValid():
            return None
        series = self._series[index.row()]

        if role in (Qt.DisplayRole, TITLE_ROLE):
            # Wie bei Filmen bewusst der ROHE Ordnername, nicht der TMDb-Titel.
            return series.folder_name
        if role == Qt.DecorationRole:
            return self._pixmap_for(series)
        if role == SERIES_ID_ROLE:
            return series.id
        if role == POSTER_PATH_ROLE:
            return series.poster_path
        if role == LOCATION_ROLE:
            return series.location
        if role == YEAR_ROLE:
            return series.first_air_year
        if role == SYNC_STATUS_ROLE:
            return series.sync_status
        if role == OVERVIEW_ROLE:
            return series.overview
        if role == GENRE_ROLE:
            return series.genre_names
        if role == IS_MISSING_ROLE:
            return bool(series.missing)
        if role == PROGRESS_ROLE:
            return self._progress.get(series.id, (0, 0))
        if role == FOLDER_CTIME_ROLE:
            return series.folder_ctime
        if role == Qt.ToolTipRole:
            y = f" ({series.first_air_year})" if series.first_air_year else ""
            if series.title and series.title != series.folder_name:
                return f"{series.folder_name}\nTMDb: {series.display_title}{y}"
            return f"{series.folder_name}{y}"
        return None

    def _pixmap_for(self, series: Series) -> QPixmap:
        if not series.poster_path:
            return self._placeholder
        cached = self._pixmap_cache.get(series.folder_name)
        if cached is not None:
            return cached
        full_path = self._thumbs_dir / series.poster_path
        raw = QPixmap(str(full_path))
        if raw.isNull():
            pm = self._placeholder
        else:
            pm = self._fit_and_crop(raw, POSTER_W, POSTER_H)
        self._pixmap_cache[series.folder_name] = pm
        return pm

    @staticmethod
    def _fit_and_crop(pixmap: QPixmap, width: int, height: int) -> QPixmap:
        scaled = pixmap.scaled(width, height, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        x = max(0, (scaled.width() - width) // 2)
        y = max(0, (scaled.height() - height) // 2)
        return scaled.copy(x, y, width, height)

    def remove_series(self, series_id: int) -> None:
        for i, s in enumerate(self._series):
            if s.id == series_id:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._series[i]
                self.endRemoveRows()
                self._pixmap_cache.pop(s.folder_name, None)
                self._progress.pop(series_id, None)
                return

    def all_series(self) -> list[Series]:
        return list(self._series)


class SeriesFilterProxy(QSortFilterProxyModel):
    """Analog zu MovieFilterProxy bei Filmen -- Status-Filter hier bewusst
    dreiteilig (Neu/Laufend/Archiv statt Ungesehen/Gesehen/Rewatch), Rest
    (Suche, Genre, Sortierung, Diagnosefilter, 'missing' bleibt sichtbar mit
    Badge statt ausgeblendet) 1:1 identisch."""

    FILTER_ALL = "all"
    FILTER_NEU = "neu"
    FILTER_LAUFEND = "laufend"
    FILTER_ARCHIV = "archiv"

    SORT_TITLE = "title"
    SORT_ADDED = "added"
    SORT_YEAR = "year"  # Erstausstrahlungsjahr (TMDb), neueste zuerst

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
        # Siehe MovieFilterProxy.set_sort_mode -- erzwingt ein echtes
        # Neusortieren, auch wenn Spalte/Richtung unveraendert bleiben.
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
            if not is_missing:
                return False
            if self._search_text:
                title = str(model.data(idx, TITLE_ROLE) or "").lower()
                if self._search_text not in title:
                    return False
            return True

        location = model.data(idx, LOCATION_ROLE)

        if self._filter_mode == self.FILTER_NEU and location != "NEU":
            return False
        if self._filter_mode == self.FILTER_LAUFEND and location != "LAUFEND":
            return False
        if self._filter_mode == self.FILTER_ARCHIV and location != "ARCHIV":
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
