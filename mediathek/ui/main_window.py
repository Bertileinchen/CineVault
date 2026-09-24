from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QComboBox, QHBoxLayout, QLabel,
                                QLineEdit, QListView, QMainWindow, QMenu, QMessageBox,
                                QProgressBar, QProgressDialog, QPushButton, QStackedWidget,
                                QTabWidget, QVBoxLayout, QWidget)

from ..backup import create_backup
from ..config import Library, SeriesLibrary, load_serien_root
from ..database import Database
from ..player import delete_movie_to_trash, mark_as_seen, mark_as_unseen, play_movie
from ..scanner import scan_library
from ..series_player import (delete_series_to_trash, mark_all_episodes_seen, next_unseen_episode,
                              play_episode, set_series_status)
from ..series_scanner import scan_series_library
from ..streaming import CineVaultStreamingServer
from .constants import CARD_H, CARD_W
from .cover_dialog import CoverPickerDialog
from .detail_dialog import MovieDetailDialog
from .movie_delegate import MovieCardDelegate
from .native_window import apply_native_window_chrome
from .movie_list_view import MovieListView
from .movie_model import GENRE_ROLE, LOCATION_ROLE, MOVIE_ID_ROLE, MovieFilterProxy, MovieListModel
from .series_cover_dialog import SeriesCoverPickerDialog
from .series_delegate import SeriesCardDelegate
from .series_detail_dialog import SeriesDetailDialog
from .series_model import GENRE_ROLE as SERIES_GENRE_ROLE
from .series_model import SERIES_ID_ROLE, SeriesFilterProxy, SeriesListModel
from .series_sync_worker import SeriesSyncWorker
from .settings_dialog import SettingsDialog
from .styles import build_stylesheet
from .sync_worker import ExtraInfoBackfillWorker, SyncWorker


class MainWindow(QMainWindow):
    def __init__(self, library: Library, db: Database):
        super().__init__()
        self._library = library
        self._db = db
        self._sync_worker: SyncWorker | None = None
        self._extra_info_worker: ExtraInfoBackfillWorker | None = None
        self._streaming_server: CineVaultStreamingServer | None = None

        # ---- Serien: komplett optional, eigener Programmbereich ----
        self._series_library: SeriesLibrary | None = None
        self._series_sync_worker: SeriesSyncWorker | None = None
        self.series_proxy = SeriesFilterProxy()

        self.setWindowTitle("CineVault")
        self.resize(1280, 800)

        self.model = MovieListModel(library.dir_thumbs)
        self.proxy = MovieFilterProxy()
        self.proxy.setSourceModel(self.model)

        self._ui_state: dict = dict(library.config.extra.get("ui_state") or {})

        self._build_ui()
        self.proxy.set_sort_mode(MovieFilterProxy.SORT_TITLE)
        self._reload_from_db()
        self._run_scan(initial=True)
        self._restore_movies_ui_state()

        if library.config.streaming_enabled:
            self._start_streaming_server(show_errors=False)

        self._try_load_series_library()

        last_tab = self._ui_state.get("last_tab")
        if last_tab == "series":
            self.tabs.setCurrentIndex(1)

        apply_native_window_chrome(self)

    # ---------------- Ansicht merken (Tab, Filter, Scrollposition) ----------------

    def _restore_movies_ui_state(self):
        """Wendet den beim letzten Beenden gespeicherten Zustand der
        Film-Ansicht an -- muss NACH _reload_from_db() laufen, da z.B. die
        Genre-Auswahl erst dann befuellt ist."""
        state = self._ui_state.get("movies") or {}
        if state.get("filter"):
            self._set_filter(state["filter"])
        sort_idx = self.sort_combo.findData(state.get("sort", MovieFilterProxy.SORT_TITLE))
        if sort_idx >= 0:
            self.sort_combo.setCurrentIndex(sort_idx)
        genre_idx = self.genre_combo.findData(state.get("genre") or None)
        if genre_idx >= 0:
            self.genre_combo.setCurrentIndex(genre_idx)
        if state.get("search"):
            self.search_edit.setText(state["search"])
        scroll_pos = state.get("scroll", 0)
        if scroll_pos:
            QTimer.singleShot(0, lambda: self.list_view.verticalScrollBar().setValue(scroll_pos))

    def _restore_series_ui_state(self):
        """Analog zu _restore_movies_ui_state(), fuer den Serien-Bereich --
        wird von _activate_series_library() aufgerufen, sobald die Serien-
        Daten geladen sind (kann je nach Konfiguration erst spaeter oder nie
        passieren)."""
        state = self._ui_state.get("series") or {}
        if state.get("filter"):
            self._set_series_filter(state["filter"])
        sort_idx = self.series_sort_combo.findData(state.get("sort", SeriesFilterProxy.SORT_TITLE))
        if sort_idx >= 0:
            self.series_sort_combo.setCurrentIndex(sort_idx)
        genre_idx = self.series_genre_combo.findData(state.get("genre") or None)
        if genre_idx >= 0:
            self.series_genre_combo.setCurrentIndex(genre_idx)
        if state.get("search"):
            self.series_search_edit.setText(state["search"])
        scroll_pos = state.get("scroll", 0)
        if scroll_pos:
            QTimer.singleShot(0, lambda: self.series_list_view.verticalScrollBar().setValue(scroll_pos))

    def _save_ui_state(self):
        """Sammelt den aktuellen Ansicht-Zustand ein und schreibt ihn in
        config.json (ueber das ohnehin vorhandene 'extra'-Feld -- rein
        kosmetisch, daher keine eigene Schema-Erweiterung noetig)."""
        movies_state = {
            "filter": self.proxy.filter_mode(),
            "sort": self.proxy.sort_mode(),
            "genre": self.proxy.genre_filter() or "",
            "search": self.search_edit.text(),
            "scroll": self.list_view.verticalScrollBar().value(),
        }
        series_state = {}
        if self._series_library is not None:
            series_state = {
                "filter": self.series_proxy.filter_mode(),
                "sort": self.series_proxy.sort_mode(),
                "genre": self.series_proxy.genre_filter() or "",
                "search": self.series_search_edit.text(),
                "scroll": self.series_list_view.verticalScrollBar().value(),
            }
        else:
            series_state = self._ui_state.get("series") or {}  # unveraendert uebernehmen

        self._library.config.extra["ui_state"] = {
            "last_tab": "series" if self.tabs.currentIndex() == 1 else "movies",
            "movies": movies_state,
            "series": series_state,
        }
        try:
            self._library.config.save(self._library.config_path)
        except Exception:
            pass  # rein kosmetischer Zustand -- ein Fehlschlag hier ist kein Drama

    # ---------------- Netzwerkfreigabe (Streaming) ----------------

    def _start_streaming_server(self, show_errors: bool = True) -> None:
        self._stop_streaming_server()
        try:
            self._streaming_server = CineVaultStreamingServer(
                self._library, self._db, series_library=self._series_library,
                port=self._library.config.streaming_port)
            self._streaming_server.start()
        except OSError as e:
            self._streaming_server = None
            if show_errors:
                QMessageBox.warning(
                    self, "Netzwerkfreigabe",
                    f"Server konnte nicht gestartet werden (Port belegt?):\n{e}"
                )

    def _stop_streaming_server(self) -> None:
        if self._streaming_server is not None:
            try:
                self._streaming_server.stop()
            except Exception:
                pass
            self._streaming_server = None

    # ---------------- UI-Aufbau ----------------

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_movies_tab(), "🎬  Filme")
        self.tabs.addTab(self._build_series_tab(), "📺  Serien")
        outer.addWidget(self.tabs)

    def _build_movies_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_bar_layout = QVBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 10, 16, 10)
        top_bar_layout.setSpacing(8)

        # ---- Zeile 1: Titel, Suche (dynamisch), Sortierung, Genre, Filter ----
        # Aufbau bewusst analog zu Zeile 2: das Suchfeld uebernimmt hier die
        # Rolle des Statustexts dort (stretch=1, ohne Maximalbreite) und
        # fuellt den Zwischenraum -- alle Buttons rechts bleiben so bei jeder
        # Fensterbreite konsequent rechtsbuendig zusammen, statt teilweise
        # schon rechts zu kleben und teilweise mitzuwandern.
        row1 = QHBoxLayout()

        title = QLabel("🎬  CineVault Movies")
        title.setObjectName("appTitle")
        row1.addWidget(title)

        row1.addSpacing(24)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("Filme durchsuchen …")
        self.search_edit.setMinimumWidth(160)
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._on_search_text_changed)
        row1.addWidget(self.search_edit, stretch=1)

        row1.addSpacing(16)

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Titel (A–Z)", MovieFilterProxy.SORT_TITLE)
        self.sort_combo.addItem("Älteste zuerst", MovieFilterProxy.SORT_ADDED)
        self.sort_combo.addItem("Jahr (neueste zuerst)", MovieFilterProxy.SORT_YEAR)
        self.sort_combo.setToolTip("Sortierung")
        self.sort_combo.currentIndexChanged.connect(self._on_sort_changed)
        row1.addWidget(self.sort_combo)

        row1.addSpacing(8)

        self.genre_combo = QComboBox()
        self.genre_combo.addItem("Alle Genres", None)
        self.genre_combo.setToolTip("Nach Genre filtern")
        self.genre_combo.currentIndexChanged.connect(self._on_genre_changed)
        row1.addWidget(self.genre_combo)

        row1.addSpacing(16)

        self.filter_all_btn = QPushButton("Alle")
        self.filter_unseen_btn = QPushButton("Ungesehen")
        self.filter_seen_btn = QPushButton("Gesehen")
        self.filter_rewatch_btn = QPushButton("Rewatch")
        for btn in (self.filter_all_btn, self.filter_unseen_btn,
                    self.filter_seen_btn, self.filter_rewatch_btn):
            btn.setCheckable(True)
            row1.addWidget(btn)
        self.filter_all_btn.setChecked(True)
        self.filter_all_btn.clicked.connect(lambda: self._set_filter("all"))
        self.filter_unseen_btn.clicked.connect(lambda: self._set_filter("unseen"))
        self.filter_seen_btn.clicked.connect(lambda: self._set_filter("seen"))
        self.filter_rewatch_btn.clicked.connect(lambda: self._set_filter("rewatch"))

        top_bar_layout.addLayout(row1)

        # ---- Zeile 2: Status (dynamische Laenge) + Aktionen ----
        # Bewusst eine eigene Zeile: der Statustext aendert seine Laenge
        # (z.B. bei aktivem Diagnosefilter) recht stark -- in einer
        # gemeinsamen Zeile mit den Buttons hat das zuvor die Fensterbreite
        # unerwartet mitverschoben.
        row2 = QHBoxLayout()

        self.status_label = QLabel("")
        self.status_label.setObjectName("statusLabel")
        row2.addWidget(self.status_label, stretch=1)

        rescan_btn = QPushButton("🔄  Ordner neu einlesen")
        rescan_btn.clicked.connect(lambda: self._run_scan(initial=False))
        row2.addWidget(rescan_btn)

        self.sync_btn = QPushButton("⬇  Jetzt synchronisieren")
        self.sync_btn.setObjectName("primaryButton")
        self.sync_btn.clicked.connect(self._start_sync)
        row2.addWidget(self.sync_btn)

        settings_btn = QPushButton("⚙")
        settings_btn.setFixedWidth(40)
        settings_btn.clicked.connect(self._open_settings)
        row2.addWidget(settings_btn)

        top_bar_layout.addLayout(row2)

        outer.addWidget(top_bar)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        outer.addWidget(self.progress_bar)

        self.list_view = MovieListView()
        self.list_view.setModel(self.proxy)
        self.list_view.setViewMode(QListView.IconMode)
        self.list_view.setResizeMode(QListView.Adjust)
        self.list_view.setMovement(QListView.Static)
        self.list_view.setUniformItemSizes(True)
        self.list_view.setSpacing(6)
        self.list_view.setIconSize(QSize(CARD_W, CARD_H))
        self.list_view.setGridSize(QSize(CARD_W + 12, CARD_H + 12))
        self.card_delegate = MovieCardDelegate(self._library.config.accent_color)
        self.list_view.setItemDelegate(self.card_delegate)
        self.list_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list_view.customContextMenuRequested.connect(self._show_context_menu)
        self.list_view.clicked.connect(self._on_item_clicked)
        outer.addWidget(self.list_view, stretch=1)

        return tab

    def _build_series_tab(self) -> QWidget:
        tab = QWidget()
        outer = QVBoxLayout(tab)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("topBar")
        top_bar_layout = QVBoxLayout(top_bar)
        top_bar_layout.setContentsMargins(16, 10, 16, 10)
        top_bar_layout.setSpacing(8)

        # ---- Zeile 1: Titel, Suche, Sortierung, Genre, Filter -- 1:1 analog
        # zum Filme-Tab aufgebaut. ----
        row1 = QHBoxLayout()

        title = QLabel("📺  CineVault Series")
        title.setObjectName("appTitle")
        row1.addWidget(title)

        row1.addSpacing(24)

        self.series_search_edit = QLineEdit()
        self.series_search_edit.setPlaceholderText("Serien durchsuchen …")
        self.series_search_edit.setMinimumWidth(160)
        self.series_search_edit.setClearButtonEnabled(True)
        self.series_search_edit.textChanged.connect(self._on_series_search_text_changed)
        row1.addWidget(self.series_search_edit, stretch=1)

        row1.addSpacing(16)

        self.series_sort_combo = QComboBox()
        self.series_sort_combo.addItem("Titel (A–Z)", SeriesFilterProxy.SORT_TITLE)
        self.series_sort_combo.addItem("Älteste zuerst", SeriesFilterProxy.SORT_ADDED)
        self.series_sort_combo.addItem("Jahr (neueste zuerst)", SeriesFilterProxy.SORT_YEAR)
        self.series_sort_combo.setToolTip("Sortierung")
        self.series_sort_combo.currentIndexChanged.connect(self._on_series_sort_changed)
        row1.addWidget(self.series_sort_combo)

        row1.addSpacing(8)

        self.series_genre_combo = QComboBox()
        self.series_genre_combo.addItem("Alle Genres", None)
        self.series_genre_combo.setToolTip("Nach Genre filtern")
        self.series_genre_combo.currentIndexChanged.connect(self._on_series_genre_changed)
        row1.addWidget(self.series_genre_combo)

        row1.addSpacing(16)

        self.series_filter_all_btn = QPushButton("Alle")
        self.series_filter_neu_btn = QPushButton("Neu")
        self.series_filter_laufend_btn = QPushButton("Laufend")
        self.series_filter_archiv_btn = QPushButton("Archiv")
        for btn in (self.series_filter_all_btn, self.series_filter_neu_btn,
                    self.series_filter_laufend_btn, self.series_filter_archiv_btn):
            btn.setCheckable(True)
            row1.addWidget(btn)
        self.series_filter_all_btn.setChecked(True)
        self.series_filter_all_btn.clicked.connect(lambda: self._set_series_filter("all"))
        self.series_filter_neu_btn.clicked.connect(lambda: self._set_series_filter("neu"))
        self.series_filter_laufend_btn.clicked.connect(lambda: self._set_series_filter("laufend"))
        self.series_filter_archiv_btn.clicked.connect(lambda: self._set_series_filter("archiv"))

        top_bar_layout.addLayout(row1)

        # ---- Zeile 2: Status + Aktionen ----
        row2 = QHBoxLayout()
        self.series_status_label = QLabel("")
        self.series_status_label.setObjectName("statusLabel")
        row2.addWidget(self.series_status_label, stretch=1)

        series_rescan_btn = QPushButton("🔄  Ordner neu einlesen")
        series_rescan_btn.clicked.connect(lambda: self._run_series_scan(initial=False))
        row2.addWidget(series_rescan_btn)

        self.series_sync_btn = QPushButton("⬇  Jetzt synchronisieren")
        self.series_sync_btn.setObjectName("primaryButton")
        self.series_sync_btn.clicked.connect(self._start_series_sync)
        row2.addWidget(self.series_sync_btn)

        series_settings_btn = QPushButton("⚙")
        series_settings_btn.setFixedWidth(40)
        series_settings_btn.clicked.connect(self._open_settings)
        row2.addWidget(series_settings_btn)

        top_bar_layout.addLayout(row2)
        outer.addWidget(top_bar)

        self.series_progress_bar = QProgressBar()
        self.series_progress_bar.setVisible(False)
        self.series_progress_bar.setTextVisible(True)
        outer.addWidget(self.series_progress_bar)

        # Zwei Seiten: "noch nicht eingerichtet"-Hinweis, oder die eigentliche
        # Kachel-Ansicht -- je nachdem, ob ein SERIEN-Ordner konfiguriert ist
        # (komplett optional, siehe config.py/SeriesLibrary).
        self.series_stack = QStackedWidget()

        placeholder = QWidget()
        placeholder_layout = QVBoxLayout(placeholder)
        placeholder_layout.addStretch(1)
        placeholder_label = QLabel(
            "Noch kein SERIEN-Ordner eingerichtet.\n\n"
            "Unter ⚙ Einstellungen → Tab \"Dateipfade\" → Bereich \"Serien\" einrichten."
        )
        placeholder_label.setAlignment(Qt.AlignCenter)
        placeholder_label.setStyleSheet("color: #7d8595; font-size: 14px;")
        placeholder_layout.addWidget(placeholder_label)
        open_settings_btn = QPushButton("⚙  Einstellungen öffnen")
        open_settings_btn.setFixedWidth(220)
        open_settings_btn.clicked.connect(self._open_settings)
        placeholder_row = QHBoxLayout()
        placeholder_row.addStretch(1)
        placeholder_row.addWidget(open_settings_btn)
        placeholder_row.addStretch(1)
        placeholder_layout.addLayout(placeholder_row)
        placeholder_layout.addStretch(1)
        self.series_stack.addWidget(placeholder)  # Index 0

        self.series_list_view = MovieListView()
        self.series_list_view.setModel(self.series_proxy)
        self.series_list_view.setViewMode(QListView.IconMode)
        self.series_list_view.setResizeMode(QListView.Adjust)
        self.series_list_view.setMovement(QListView.Static)
        self.series_list_view.setUniformItemSizes(True)
        self.series_list_view.setSpacing(6)
        self.series_list_view.setIconSize(QSize(CARD_W, CARD_H))
        self.series_list_view.setGridSize(QSize(CARD_W + 12, CARD_H + 12))
        self.series_card_delegate = SeriesCardDelegate(self._library.config.accent_color)
        self.series_list_view.setItemDelegate(self.series_card_delegate)
        self.series_list_view.setSelectionMode(QAbstractItemView.SingleSelection)
        self.series_list_view.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.series_list_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.series_list_view.customContextMenuRequested.connect(self._show_series_context_menu)
        self.series_list_view.clicked.connect(self._on_series_item_clicked)
        self.series_stack.addWidget(self.series_list_view)  # Index 1

        outer.addWidget(self.series_stack, stretch=1)
        return tab

    # ================================================================
    # Filme
    # ================================================================

    # ---------------- Daten laden ----------------

    def _reload_from_db(self):
        movies = self._db.list_movies()
        self.model.set_movies(movies)
        self._refresh_genre_options()
        self._update_status()

    def _refresh_genre_options(self):
        """Baut die Genre-Auswahl aus den tatsaechlich vorhandenen Filmen neu
        auf (z.B. nach einer Synchronisierung koennen neue Genres dazukommen)."""
        genres: set[str] = set()
        for i in range(self.model.rowCount()):
            idx = self.model.index(i)
            raw = self.model.data(idx, GENRE_ROLE)
            if raw:
                for g in str(raw).split(","):
                    g = g.strip()
                    if g:
                        genres.add(g)

        current = self.genre_combo.currentData()
        self.genre_combo.blockSignals(True)
        self.genre_combo.clear()
        self.genre_combo.addItem("Alle Genres", None)
        for g in sorted(genres, key=str.lower):
            self.genre_combo.addItem(g, g)
        idx = self.genre_combo.findData(current)
        self.genre_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.genre_combo.blockSignals(False)

    def _on_genre_changed(self, index: int):
        genre = self.genre_combo.itemData(index)
        self.proxy.set_genre_filter(genre)
        self._update_status()

    def _on_search_text_changed(self, text: str):
        self.proxy.set_search_text(text)
        self._update_status()

    def _update_status(self):
        total_all = self.model.rowCount()
        unseen = sum(1 for i in range(total_all)
                     if self.model.data(self.model.index(i), LOCATION_ROLE) == "NEU")
        visible = self.proxy.rowCount()

        if visible == total_all:
            text = f"{visible} Filme · {unseen} ungesehen"
        else:
            text = f"{visible} von {total_all} Filmen angezeigt · {unseen} ungesehen"

        diag_labels = {
            "unsynced": "nicht synchronisiert",
            "ambiguous_only": "mehrdeutig",
            "no_overview": "ohne Beschreibung",
            "no_cover": "ohne Cover",
            "missing_only": "fehlend (Ordner nicht gefunden)",
        }
        active_diag = diag_labels.get(self.proxy.diagnostic_filter())
        if active_diag:
            text += f"  ·  Filter: {active_diag} (in Einstellungen zurücksetzen oder 'Alle' klicken)"
        self.status_label.setText(text)

    def _set_filter(self, mode: str):
        self.filter_all_btn.setChecked(mode == "all")
        self.filter_unseen_btn.setChecked(mode == "unseen")
        self.filter_seen_btn.setChecked(mode == "seen")
        self.filter_rewatch_btn.setChecked(mode == "rewatch")
        self.proxy.set_filter_mode(mode)
        if mode == "all" and self.proxy.diagnostic_filter():
            self.proxy.set_diagnostic_filter(None)
        self._update_status()

    def _on_sort_changed(self, index: int):
        mode = self.sort_combo.itemData(index)
        if mode:
            self.proxy.set_sort_mode(mode)

    # ---------------- Scan ----------------

    def _run_scan(self, initial: bool):
        result = scan_library(self._library, self._db, force_full=False)
        self._reload_from_db()
        if not initial:
            self.status_label.setText(
                f"Scan fertig: {result.new_count} neu, {result.updated_count} aktualisiert, "
                f"{result.missing_count} fehlend")

    # ---------------- Synchronisierung ----------------

    def _start_sync(self):
        if self._sync_worker is not None and self._sync_worker.isRunning():
            return
        # Vor dem Sync sicherheitshalber neu einlesen, falls Ordner extern geaendert wurden
        scan_library(self._library, self._db, force_full=False)
        self._reload_from_db()

        pending = self._db.list_pending_sync()
        if not pending:
            QMessageBox.information(self, "Synchronisierung",
                                     "Alle Filme sind bereits aufbereitet. Nichts zu tun.")
            return

        self.sync_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(pending))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"Synchronisiere 0 / {len(pending)}")

        self._sync_worker = SyncWorker(self._library, self._db, pending)
        self._sync_worker.progress.connect(self._on_sync_progress)
        self._sync_worker.movie_updated.connect(self._on_movie_updated)
        self._sync_worker.finished_sync.connect(self._on_sync_finished)
        self._sync_worker.error.connect(self._on_sync_error)
        self._sync_worker.start()

    def _on_sync_progress(self, done: int, total: int):
        self.progress_bar.setValue(done)
        self.progress_bar.setFormat(f"Synchronisiere {done} / {total}")

    def _on_movie_updated(self, movie):
        self.model.update_movie(movie)
        self._update_status()

    def _on_sync_finished(self, ok_count: int, total: int):
        self.sync_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._reload_from_db()
        self.status_label.setText(f"Synchronisierung abgeschlossen: {ok_count} / {total} erfolgreich")

    def _on_sync_error(self, message: str):
        self.sync_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        QMessageBox.warning(self, "Synchronisierung", message)

    # ---------------- Interaktion ----------------

    def _current_movie(self, index):
        if not index.isValid():
            return None
        movie_id = self.proxy.data(index, MOVIE_ID_ROLE)
        return self._db.get(movie_id)

    def _on_item_clicked(self, index):
        movie = self._current_movie(index)
        if not movie:
            return
        self._open_detail(movie)

    def _play_movie(self, movie):
        try:
            play_movie(movie)
        except Exception as e:
            QMessageBox.warning(self, "Wiedergabe nicht moeglich", str(e))

    def _show_context_menu(self, pos):
        index = self.list_view.indexAt(pos)
        movie = self._current_movie(index)
        if not movie:
            return

        menu = QMenu(self)
        play_action = menu.addAction("▶  Abspielen")
        detail_action = menu.addAction("ℹ  Details anzeigen")
        cover_action = menu.addAction("🖼  Cover aendern …")
        menu.addSeparator()
        toggle_action = menu.addAction(
            "✔  Als gesehen markieren" if movie.is_unseen else "↺  Als ungesehen markieren")
        rewatch_action = None
        if not movie.is_unseen:
            rewatch_action = menu.addAction(
                "✖  Nicht mehr für Rewatch vormerken" if movie.rewatch else "🔁  Für Rewatch vormerken")
        menu.addSeparator()
        resync_action = menu.addAction("🔁  Erneut synchronisieren")
        menu.addSeparator()
        delete_action = menu.addAction("🗑  Löschen …")

        action = menu.exec(self.list_view.viewport().mapToGlobal(pos))
        if action == play_action:
            self._play_movie(movie)
        elif action == detail_action:
            self._open_detail(movie)
        elif action == cover_action:
            self._open_cover_picker(movie)
        elif action == toggle_action:
            self._toggle_seen(movie)
        elif rewatch_action is not None and action == rewatch_action:
            self._toggle_rewatch(movie)
        elif action == resync_action:
            self._db.reset_sync(movie.id)
            self._reload_from_db()
        elif action == delete_action:
            self._delete_movie(movie)

    def _open_detail(self, movie):
        dlg = MovieDetailDialog(self._library, self._db, movie, self)
        dlg.movie_changed.connect(self.model.update_movie)
        dlg.movie_changed.connect(lambda _m: self._refresh_genre_options())
        dlg.movie_changed.connect(lambda _m: self._update_status())
        dlg.movie_deleted.connect(self._on_movie_deleted)
        dlg.exec()

    def _on_movie_deleted(self, movie_id: int):
        self.model.remove_movie(movie_id)
        self._refresh_genre_options()
        self._update_status()

    def _open_cover_picker(self, movie):
        dlg = CoverPickerDialog(self._library, self._db, movie, self)
        if dlg.exec():
            self.model.update_movie(self._db.get(movie.id))

    def _toggle_seen(self, movie):
        try:
            if movie.is_unseen:
                updated = mark_as_seen(self._library, self._db, movie)
            else:
                updated = mark_as_unseen(self._library, self._db, movie)
            self.model.update_movie(updated)
            self._update_status()
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))

    def _toggle_rewatch(self, movie):
        self._db.set_rewatch(movie.id, not movie.rewatch)
        self.model.update_movie(self._db.get(movie.id))

    def _delete_movie(self, movie):
        answer = QMessageBox.question(
            self, "Film löschen",
            f"'{movie.display_title}' wirklich löschen?\n\n"
            "Der Ordner wird in den Windows-Papierkorb verschoben (nicht "
            "endgültig gelöscht) und kann von dort wiederhergestellt werden.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_movie_to_trash(self._library, self._db, movie)
        except Exception as e:
            QMessageBox.warning(self, "Löschen fehlgeschlagen", str(e))
            return
        self._on_movie_deleted(movie.id)

    # ================================================================
    # Serien
    # ================================================================

    def _try_load_series_library(self):
        root = load_serien_root()
        if root is not None:
            self._activate_series_library(root)

    def _activate_series_library(self, root: Path):
        self._series_library = SeriesLibrary(root, self._library)
        self.series_model = SeriesListModel(self._series_library.dir_thumbs)
        self.series_proxy.setSourceModel(self.series_model)
        self.series_proxy.set_sort_mode(SeriesFilterProxy.SORT_TITLE)
        self.series_stack.setCurrentIndex(1)
        self._run_series_scan(initial=True)
        self._restore_series_ui_state()
        if self._streaming_server is not None:
            # Server laeuft schon (mit series_library=None gestartet) --
            # neu starten, damit er die Serien jetzt mit ausliefert.
            self._start_streaming_server(show_errors=False)

    def _reload_series_from_db(self):
        if self._series_library is None:
            return
        series_list = self._db.list_series()
        progress: dict[int, tuple[int, int]] = {}
        for s in series_list:
            total, seen = self._db.count_episodes_for_series(s.id)
            progress[s.id] = (seen, total)
        self.series_model.set_series(series_list, progress)
        self._refresh_series_genre_options()
        self._update_series_status()

    def _refresh_series_genre_options(self):
        genres: set[str] = set()
        for i in range(self.series_model.rowCount()):
            idx = self.series_model.index(i)
            raw = self.series_model.data(idx, SERIES_GENRE_ROLE)
            if raw:
                for g in str(raw).split(","):
                    g = g.strip()
                    if g:
                        genres.add(g)

        current = self.series_genre_combo.currentData()
        self.series_genre_combo.blockSignals(True)
        self.series_genre_combo.clear()
        self.series_genre_combo.addItem("Alle Genres", None)
        for g in sorted(genres, key=str.lower):
            self.series_genre_combo.addItem(g, g)
        idx = self.series_genre_combo.findData(current)
        self.series_genre_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self.series_genre_combo.blockSignals(False)

    def _on_series_genre_changed(self, index: int):
        genre = self.series_genre_combo.itemData(index)
        self.series_proxy.set_genre_filter(genre)
        self._update_series_status()

    def _on_series_search_text_changed(self, text: str):
        self.series_proxy.set_search_text(text)
        self._update_series_status()

    def _on_series_sort_changed(self, index: int):
        mode = self.series_sort_combo.itemData(index)
        if mode:
            self.series_proxy.set_sort_mode(mode)

    def _set_series_filter(self, mode: str):
        self.series_filter_all_btn.setChecked(mode == "all")
        self.series_filter_neu_btn.setChecked(mode == "neu")
        self.series_filter_laufend_btn.setChecked(mode == "laufend")
        self.series_filter_archiv_btn.setChecked(mode == "archiv")
        self.series_proxy.set_filter_mode(mode)
        if mode == "all" and self.series_proxy.diagnostic_filter():
            self.series_proxy.set_diagnostic_filter(None)
        self._update_series_status()

    def _update_series_status(self):
        if self._series_library is None:
            return
        total_all = self.series_model.rowCount()
        visible = self.series_proxy.rowCount()
        active = [s for s in self.series_model.all_series() if not s.missing]
        neu = sum(1 for s in active if s.location == "NEU")
        laufend = sum(1 for s in active if s.location == "LAUFEND")
        archiv = sum(1 for s in active if s.location == "ARCHIV")

        if visible == total_all:
            text = f"{len(active)} Serien · {neu} neu · {laufend} laufend · {archiv} abgeschlossen"
        else:
            text = (f"{visible} von {total_all} Serien angezeigt · {neu} neu · "
                    f"{laufend} laufend · {archiv} abgeschlossen")

        diag_labels = {
            "unsynced": "nicht synchronisiert",
            "ambiguous_only": "mehrdeutig",
            "no_overview": "ohne Beschreibung",
            "no_cover": "ohne Cover",
            "missing_only": "fehlend (Ordner nicht gefunden)",
        }
        active_diag = diag_labels.get(self.series_proxy.diagnostic_filter())
        if active_diag:
            text += f"  ·  Filter: {active_diag} (in Einstellungen zurücksetzen oder 'Alle' klicken)"
        self.series_status_label.setText(text)

    def _run_series_scan(self, initial: bool):
        if self._series_library is None:
            return
        result = scan_series_library(self._series_library, self._db, force_full=False)
        self._reload_series_from_db()
        if not initial:
            self.series_status_label.setText(
                f"Scan fertig: {result.new_series} neue Serie(n), {result.updated_series} "
                f"aktualisiert, {result.new_episodes} neue Episode(n)")

    def _start_series_sync(self):
        if self._series_library is None:
            return
        if self._series_sync_worker is not None and self._series_sync_worker.isRunning():
            return
        scan_series_library(self._series_library, self._db, force_full=False)
        self._reload_series_from_db()

        pending = self._db.list_series_pending_sync()
        if not pending:
            QMessageBox.information(self, "Synchronisierung",
                                     "Alle Serien sind bereits aufbereitet. Nichts zu tun.")
            return

        self.series_sync_btn.setEnabled(False)
        self.series_progress_bar.setVisible(True)
        self.series_progress_bar.setRange(0, len(pending))
        self.series_progress_bar.setValue(0)
        self.series_progress_bar.setFormat(f"Synchronisiere 0 / {len(pending)}")

        self._series_sync_worker = SeriesSyncWorker(
            self._library, self._series_library, self._db, pending)
        self._series_sync_worker.progress.connect(self._on_series_sync_progress)
        self._series_sync_worker.series_updated.connect(self._on_series_updated)
        self._series_sync_worker.finished_sync.connect(self._on_series_sync_finished)
        self._series_sync_worker.error.connect(self._on_series_sync_error)
        self._series_sync_worker.start()

    def _on_series_sync_progress(self, done: int, total: int):
        self.series_progress_bar.setValue(done)
        self.series_progress_bar.setFormat(f"Synchronisiere {done} / {total}")

    def _on_series_updated(self, series):
        total, seen = self._db.count_episodes_for_series(series.id)
        self.series_model.update_series(series, (seen, total))
        self._update_series_status()

    def _on_series_sync_finished(self, ok_count: int, total: int):
        self.series_sync_btn.setEnabled(True)
        self.series_progress_bar.setVisible(False)
        self._reload_series_from_db()
        self.series_status_label.setText(
            f"Synchronisierung abgeschlossen: {ok_count} / {total} erfolgreich")

    def _on_series_sync_error(self, message: str):
        self.series_sync_btn.setEnabled(True)
        self.series_progress_bar.setVisible(False)
        QMessageBox.warning(self, "Synchronisierung", message)

    def _current_series(self, index):
        if not index.isValid() or self._series_library is None:
            return None
        series_id = self.series_proxy.data(index, SERIES_ID_ROLE)
        return self._db.get_series(series_id)

    def _on_series_item_clicked(self, index):
        series = self._current_series(index)
        if not series:
            return
        self._open_series_detail(series)

    def _open_series_detail(self, series):
        dlg = SeriesDetailDialog(self._library, self._series_library, self._db, series, self)
        dlg.series_changed.connect(self._on_series_updated)
        dlg.series_deleted.connect(self._on_series_deleted)
        dlg.exec()

    def _on_series_deleted(self, series_id: int):
        self.series_model.remove_series(series_id)
        self._update_series_status()

    def _play_series_next(self, series):
        nxt = next_unseen_episode(self._db, series)
        if nxt is None:
            episodes = [e for e in self._db.list_episodes_for_series(series.id) if e.missing == 0]
            if not episodes:
                QMessageBox.information(self, "Abspielen", "Keine Episoden gefunden.")
                return
            nxt = min(episodes, key=lambda e: (e.season_number, e.episode_number))
        try:
            play_episode(self._series_library, series, nxt)
        except Exception as e:
            QMessageBox.warning(self, "Wiedergabe nicht möglich", str(e))

    def _show_series_context_menu(self, pos):
        index = self.series_list_view.indexAt(pos)
        series = self._current_series(index)
        if not series:
            return

        menu = QMenu(self)
        play_action = menu.addAction("▶  Nächste Folge abspielen")
        detail_action = menu.addAction("ℹ  Details anzeigen")
        cover_action = menu.addAction("🖼  Cover aendern …")
        menu.addSeparator()
        status_action = None
        if series.location == "NEU":
            status_action = menu.addAction("▶  Serie beginnen")
        elif series.location == "LAUFEND":
            status_action = menu.addAction("✔  Serie abschliessen")
        else:
            status_action = menu.addAction("↺  Serie fortsetzen")
        mark_all_action = menu.addAction("✔✔  Alle Episoden als gesehen markieren")
        menu.addSeparator()
        resync_action = menu.addAction("🔁  Erneut synchronisieren")
        menu.addSeparator()
        delete_action = menu.addAction("🗑  Löschen …")

        action = menu.exec(self.series_list_view.viewport().mapToGlobal(pos))
        if action == play_action:
            self._play_series_next(series)
        elif action == detail_action:
            self._open_series_detail(series)
        elif action == cover_action:
            self._open_series_cover_picker(series)
        elif action == status_action:
            self._advance_series_status(series)
        elif action == mark_all_action:
            self._mark_all_series_episodes_seen(series)
        elif action == resync_action:
            self._db.reset_series_sync(series.id)
            self._reload_series_from_db()
        elif action == delete_action:
            self._delete_series(series)

    def _open_series_cover_picker(self, series):
        dlg = SeriesCoverPickerDialog(self._series_library, self._db, series, self)
        if dlg.exec():
            self._on_series_updated(self._db.get_series(series.id))

    def _advance_series_status(self, series):
        target = "LAUFEND" if series.location in ("NEU", "ARCHIV") else "ARCHIV"
        if series.location == "LAUFEND":
            answer = QMessageBox.question(
                self, "Serie abschliessen",
                f"'{series.display_title}' als abgeschlossen markieren und in den "
                "ARCHIV-Ordner verschieben?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
        try:
            updated = set_series_status(self._series_library, self._db, series, target)
            self._on_series_updated(updated)
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))

    def _mark_all_series_episodes_seen(self, series):
        answer = QMessageBox.question(
            self, "Alle Episoden als gesehen markieren",
            f"Wirklich ALLE Episoden von '{series.display_title}' auf einmal als "
            "gesehen markieren? Praktisch v.a. beim erstmaligen Einpflegen bereits "
            "komplett geschauter Serien.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            updated = mark_all_episodes_seen(self._series_library, self._db, series)
            self._on_series_updated(updated)
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))

    def _delete_series(self, series):
        answer = QMessageBox.question(
            self, "Serie löschen",
            f"'{series.display_title}' wirklich löschen?\n\n"
            "Der komplette Serienordner wird in den Windows-Papierkorb verschoben "
            "(nicht endgültig gelöscht) und kann von dort wiederhergestellt werden.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_series_to_trash(self._series_library, self._db, series)
        except Exception as e:
            QMessageBox.warning(self, "Löschen fehlgeschlagen", str(e))
            return
        self._on_series_deleted(series.id)

    # ================================================================
    # Gemeinsam: Einstellungen, Akzentfarbe, Streaming, Beenden
    # ================================================================

    def _open_settings(self):
        dlg = SettingsDialog(self._library, self._db, self)
        dlg.exec()
        result = dlg.diagnostic_result
        if result == "reload_extras":
            self._reload_extra_info_for_synced_movies()
        elif result and result.startswith("series_"):
            mode = result[len("series_"):]
            self.series_proxy.set_diagnostic_filter(mode)
            self._update_series_status()
            self.tabs.setCurrentIndex(1)
        elif result:
            self.proxy.set_diagnostic_filter(result)
            self._update_status()
            self.tabs.setCurrentIndex(0)

        if getattr(dlg, "series_root_changed", False):
            root = load_serien_root()
            if root is not None:
                self._activate_series_library(root)

        self._sync_streaming_server_state()
        self._apply_accent_color(self._library.config.accent_color)

    def _apply_accent_color(self, accent: str) -> None:
        """Wendet eine (evtl. neue) Akzentfarbe sofort an, ohne Neustart --
        sowohl im globalen Stylesheet als auch in beiden Kachel-Delegates
        (Hover-Schein, Rahmen, Status-Badges)."""
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(build_stylesheet(accent))
        self.card_delegate.set_accent_color(accent)
        self.list_view.viewport().update()
        self.series_card_delegate.set_accent_color(accent)
        self.series_list_view.viewport().update()

    def _sync_streaming_server_state(self) -> None:
        """Startet/stoppt den Streaming-Server passend zum aktuellen Stand
        der Einstellungen (nach dem Schliessen des Einstellungen-Dialogs)."""
        should_run = self._library.config.streaming_enabled
        if not should_run:
            self._stop_streaming_server()
            return
        port_changed = (
            self._streaming_server is not None
            and self._streaming_server.port != self._library.config.streaming_port
        )
        if self._streaming_server is None or port_changed:
            self._start_streaming_server(show_errors=True)

    def _reload_extra_info_for_synced_movies(self):
        movies = self._db.list_ok_missing_extra_info()
        if not movies:
            QMessageBox.information(
                self, "Zusatzinfos nachladen",
                "Bei allen bereits synchronisierten Filmen sind Besetzung, "
                "Genre und Trailer bereits vollständig. Nichts zu tun."
            )
            return

        if not self._library.config.tmdb_api_key:
            QMessageBox.warning(
                self, "Zusatzinfos nachladen",
                "Kein TMDb-API-Key hinterlegt. Bitte unter 'Einstellungen' einen "
                "kostenlosen API-Key eintragen."
            )
            return

        self.sync_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, len(movies))
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat(f"Zusatzinfos werden nachgeladen 0 / {len(movies)}")

        # Bewusst der SICHERE Weg: fragt direkt die bereits bekannte TMDb-ID
        # ab und ergaenzt NUR fehlende Besetzung/Genre/Trailer -- Titel,
        # Beschreibung, Cover und z.B. eine per Mehrdeutigkeits-Dropdown
        # getroffene Auswahl bleiben dabei garantiert unangetastet (kein
        # sync_status-Reset, keine erneute Titelsuche).
        self._extra_info_worker = ExtraInfoBackfillWorker(self._library, self._db, movies, self)
        self._extra_info_worker.progress.connect(self._on_extra_backfill_progress)
        self._extra_info_worker.movie_updated.connect(self._on_movie_updated)
        self._extra_info_worker.finished_all.connect(self._on_extra_backfill_finished)
        self._extra_info_worker.start()

    def _on_extra_backfill_progress(self, done: int, total: int):
        self.progress_bar.setValue(done)
        self.progress_bar.setFormat(f"Zusatzinfos werden nachgeladen {done} / {total}")

    def _on_extra_backfill_finished(self, ok_count: int, total: int):
        self.sync_btn.setEnabled(True)
        self.progress_bar.setVisible(False)
        self._refresh_genre_options()
        self._update_status()
        QMessageBox.information(
            self, "Zusatzinfos nachladen",
            f"Fertig: bei {ok_count} von {total} Filmen wurde etwas ergänzt."
        )

    def closeEvent(self, event):
        self._save_ui_state()

        if self._sync_worker is not None and self._sync_worker.isRunning():
            self._sync_worker.cancel()
            self._sync_worker.wait(2000)

        if self._series_sync_worker is not None and self._series_sync_worker.isRunning():
            self._series_sync_worker.cancel()
            self._series_sync_worker.wait(2000)

        self._stop_streaming_server()

        if self._library.config.backup_auto and self._library.config.backup_path:
            progress = QProgressDialog("Backup läuft, bitte warten …", None, 0, 0, self)
            progress.setWindowTitle("CineVault wird beendet")
            progress.setWindowModality(Qt.WindowModal)
            progress.setMinimumDuration(0)
            progress.setCancelButton(None)
            progress.show()
            QApplication.processEvents()
            try:
                create_backup(self._library, self._db, Path(self._library.config.backup_path))
            except Exception:
                # Beim Beenden bewusst nicht mit einem Fehlerdialog stoeren --
                # das naechste manuelle Backup zeigt Probleme ohnehin an.
                pass
            progress.close()

        super().closeEvent(event)
