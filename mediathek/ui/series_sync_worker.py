"""
Duenne QThread-Wrapper um die Sync-Logik aus mediathek/series_sync.py --
analog zu BackupWorker in sync_worker.py, das ebenfalls nur create_backup()
im Hintergrund-Thread aufruft. Die eigentliche Logik liegt bewusst NICHT
hier, damit sie ohne Qt-Abhaengigkeit fuer sich testbar bleibt.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QThread, Signal

from ..config import Library, SeriesLibrary
from ..database import Database, Series
from ..metadata_client import TmdbClient, TmdbError
from ..series_sync import assign_tv_id, sync_single_series


class SeriesManualAssignWorker(QThread):
    """Fuehrt assign_tv_id() im Hintergrund aus, analog zu
    ManualAssignWorker bei Filmen."""
    finished_ok = Signal(object)   # Series
    failed = Signal(str)

    def __init__(self, library: Library, series_library: SeriesLibrary, db: Database,
                 series: Series, tmdb_id: int, parent=None):
        super().__init__(parent)
        self._library = library
        self._series_library = series_library
        self._db = db
        self._series = series
        self._tmdb_id = tmdb_id

    def run(self) -> None:
        if not self._library.config.tmdb_api_key:
            self.failed.emit(
                "Kein TMDb-API-Key hinterlegt. Bitte unter 'Einstellungen' einen "
                "kostenlosen API-Key eintragen (https://www.themoviedb.org/settings/api)."
            )
            return
        try:
            updated = assign_tv_id(self._library, self._series_library, self._db,
                                    self._series, self._tmdb_id)
            self.finished_ok.emit(updated)
        except TmdbError as e:
            self.failed.emit(str(e))
        except Exception as e:
            self.failed.emit(str(e))


class SeriesSyncWorker(QThread):
    """Analog zu SyncWorker bei Filmen: synchronisiert mehrere Serien
    parallel (Thread-Pool, gleiche Nebenlaeufigkeits-Einstellung wie bei
    Filmen). Die Episoden JEDER Serie werden dabei -- innerhalb der fuer
    diese Serie zustaendigen Worker-Thread -- sequenziell nachgeladen, um
    nicht zusaetzlich zur Serien-Parallelitaet noch eine zweite Ebene
    gleichzeitiger Verbindungen aufzumachen. Bei Serien mit sehr vielen
    Episoden (z.B. 291 bei manchen Animes) kann das fuer diese eine Serie
    entsprechend dauern -- andere Serien werden in der Zwischenzeit aber
    ganz normal parallel weiter abgeglichen."""
    progress = Signal(int, int)          # (erledigt, gesamt) -- zaehlt SERIEN, nicht Episoden
    series_updated = Signal(object)      # Series
    finished_sync = Signal(int, int)     # (erfolgreich, gesamt)
    error = Signal(str)

    def __init__(self, library: Library, series_library: SeriesLibrary, db: Database,
                 series_list: list[Series], parent=None):
        super().__init__(parent)
        self._library = library
        self._series_library = series_library
        self._db = db
        self._series_list = series_list
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        if not self._library.config.tmdb_api_key:
            self.error.emit(
                "Kein TMDb-API-Key hinterlegt. Bitte unter 'Einstellungen' einen "
                "kostenlosen API-Key eintragen (https://www.themoviedb.org/settings/api)."
            )
            self.finished_sync.emit(0, len(self._series_list))
            return

        client = TmdbClient(self._library.config.tmdb_api_key,
                             self._library.config.tmdb_language)
        total = len(self._series_list)
        done = 0
        ok_count = 0

        concurrency = max(1, min(self._library.config.sync_concurrency, 10))
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {
                pool.submit(sync_single_series, self._library, self._series_library,
                            self._db, client, s): s
                for s in self._series_list
            }
            for future in as_completed(futures):
                if self._cancel:
                    break
                try:
                    updated_series = future.result()
                    if updated_series and updated_series.sync_status == "ok":
                        ok_count += 1
                    if updated_series:
                        self.series_updated.emit(updated_series)
                except Exception as e:
                    self.error.emit(str(e))
                done += 1
                self.progress.emit(done, total)

        self.finished_sync.emit(ok_count, total)
