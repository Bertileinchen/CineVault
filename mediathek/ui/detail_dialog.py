from __future__ import annotations

import html
import json
import webbrowser
from urllib.parse import quote

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel,
                                QLineEdit, QMessageBox, QPushButton, QTextEdit, QVBoxLayout)

from ..config import Library
from ..database import Database, Movie
from ..player import delete_movie_to_trash, mark_as_seen, mark_as_unseen, open_movie_folder, play_movie
from ..utils import parse_title_year, parse_tmdb_id
from .cover_dialog import CoverPickerDialog
from .native_window import apply_native_window_chrome
from .sync_worker import CandidatePosterWorker, ManualAssignWorker

STATUS_LABELS = {
    "pending": "Metadaten noch nicht synchronisiert",
    "not_found": "Bei TMDb nicht gefunden",
    "ambiguous": "Mehrdeutig – bitte unten auswählen",
    "error": "Fehler beim letzten Sync",
    "ok": "Metadaten aktuell",
    "manual": "Infos von Hand ergänzt",
}


class TmdbLinkInputDialog(QDialog):
    """Kleiner Dialog fuer die manuelle TMDb-Zuweisung -- mit direkt
    anklickbarem Such-Link (spart den Umweg, erst selbst zu themoviedb.org
    zu gehen und dort zu suchen)."""

    def __init__(self, folder_name: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("TMDb-Link manuell zuweisen")
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)

        clean_title, _year = parse_title_year(folder_name)

        search_url = "https://www.themoviedb.org/search?query=" + quote(clean_title)
        link_label = QLabel(
            f'🔍 <a href="{search_url}" style="color:#4f7cff;">'
            f'"{html.escape(clean_title)}" auf TMDb suchen</a>'
        )
        link_label.setOpenExternalLinks(True)
        layout.addWidget(link_label)

        info_label = QLabel(
            "TMDb-Link oder ID einfügen, z.B.\n"
            "https://www.themoviedb.org/movie/603-the-matrix   oder einfach   603"
        )
        info_label.setWordWrap(True)
        layout.addWidget(info_label)

        self.input_edit = QLineEdit()
        self.input_edit.returnPressed.connect(self.accept)
        layout.addWidget(self.input_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        ok_btn = QPushButton("Übernehmen")
        ok_btn.setObjectName("primaryButton")
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        apply_native_window_chrome(self)

    def text(self) -> str:
        return self.input_edit.text().strip()


class MovieDetailDialog(QDialog):
    movie_changed = Signal(object)  # Movie
    movie_deleted = Signal(int)     # movie_id

    def __init__(self, library: Library, db: Database, movie: Movie, parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self._movie = movie
        self._edit_mode = False
        self._manual_worker: ManualAssignWorker | None = None

        self.setWindowTitle(movie.display_title)
        self.setMinimumSize(680, 500)

        root = QHBoxLayout(self)

        # ---------------- Cover links ----------------
        left = QVBoxLayout()
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(220, 320)
        self.cover_label.setStyleSheet("background-color: #21242e; border-radius: 10px;")
        self.cover_label.setAlignment(Qt.AlignCenter)
        left.addWidget(self.cover_label)

        # Diese beiden Aktionen gehoeren inhaltlich zum Bearbeiten der
        # Filminfos und werden daher nur im Bearbeiten-Modus eingeblendet.
        self.cover_btn = QPushButton("Cover ändern …")
        self.cover_btn.clicked.connect(self._change_cover)
        self.cover_btn.setVisible(False)
        left.addWidget(self.cover_btn)

        self.assign_btn = QPushButton("🔗  TMDb-Link manuell zuweisen")
        self.assign_btn.clicked.connect(self._assign_tmdb_manually)
        self.assign_btn.setVisible(False)
        left.addWidget(self.assign_btn)

        left.addStretch(1)

        self.open_folder_btn = QPushButton("📂  Ordner öffnen")
        self.open_folder_btn.clicked.connect(self._open_folder)
        left.addWidget(self.open_folder_btn)

        # Administrative Aktionen kompakt in einer Zeile: "Bearbeiten" morpht
        # an gleicher Stelle zu "Speichern"/"Abbrechen", direkt daneben
        # "Löschen" -- alles zusammen direkt unter "Ordner öffnen".
        bottom_row = QHBoxLayout()
        self.edit_btn = QPushButton("✏  Bearbeiten")
        self.edit_btn.clicked.connect(self._enter_edit_mode)
        bottom_row.addWidget(self.edit_btn)

        self.save_btn = QPushButton("💾  Speichern")
        self.save_btn.setObjectName("primaryButton")
        self.save_btn.setVisible(False)
        self.save_btn.clicked.connect(self._save_edits)
        bottom_row.addWidget(self.save_btn)

        self.cancel_edit_btn = QPushButton("Abbrechen")
        self.cancel_edit_btn.setVisible(False)
        self.cancel_edit_btn.clicked.connect(self._cancel_edit_mode)
        bottom_row.addWidget(self.cancel_edit_btn)

        self.delete_btn = QPushButton("🗑  Löschen")
        self.delete_btn.setStyleSheet(
            "QPushButton { color: #e05f5f; } QPushButton:hover { border: 1px solid #e05f5f; }")
        self.delete_btn.clicked.connect(self._delete_movie)
        bottom_row.addWidget(self.delete_btn)

        left.addLayout(bottom_row)

        root.addLayout(left)

        # ---------------- Infos rechts ----------------
        right = QVBoxLayout()

        self.title_label = QLabel()
        self.title_label.setObjectName("detailTitle")
        self.title_label.setWordWrap(True)
        right.addWidget(self.title_label)

        self.title_edit = QLineEdit()
        self.title_edit.setVisible(False)
        right.addWidget(self.title_edit)

        self.meta_label = QLabel()
        self.meta_label.setObjectName("detailMeta")
        self.meta_label.setWordWrap(True)
        right.addWidget(self.meta_label)

        self.note_label = QLabel()
        self.note_label.setStyleSheet("color: #e0a83e; font-size: 12px;")
        self.note_label.setWordWrap(True)
        right.addWidget(self.note_label)

        # Nur sichtbar bei Status "Mehrdeutig": Auswahl-Dropdown der von
        # TMDb gefundenen, gleichnamigen Filme (z.B. Remakes) inkl. Jahr.
        ambiguous_row = QHBoxLayout()
        self.ambiguous_combo = QComboBox()
        ambiguous_row.addWidget(self.ambiguous_combo, stretch=1)
        self.ambiguous_pick_btn = QPushButton("Übernehmen")
        self.ambiguous_pick_btn.setObjectName("primaryButton")
        self.ambiguous_pick_btn.clicked.connect(self._pick_ambiguous_candidate)
        ambiguous_row.addWidget(self.ambiguous_pick_btn)
        self.ambiguous_row_widgets = (self.ambiguous_combo, self.ambiguous_pick_btn)
        right.addLayout(ambiguous_row)
        self.ambiguous_combo.currentIndexChanged.connect(self._on_ambiguous_selection_changed)

        # Vorschau (Cover + Beschreibung) des gerade im Dropdown ausgewaehlten
        # Kandidaten -- macht die Unterscheidung deutlich einfacher als nur
        # Titel + Jahr.
        ambiguous_preview_row = QHBoxLayout()
        self.ambiguous_poster_label = QLabel()
        self.ambiguous_poster_label.setFixedSize(80, 118)
        self.ambiguous_poster_label.setStyleSheet(
            "background-color: #21242e; border-radius: 6px; color: #5a5f6c; font-size: 10px;")
        self.ambiguous_poster_label.setAlignment(Qt.AlignCenter)
        self.ambiguous_poster_label.setWordWrap(True)
        ambiguous_preview_row.addWidget(self.ambiguous_poster_label)

        self.ambiguous_overview_label = QLabel()
        self.ambiguous_overview_label.setTextFormat(Qt.RichText)
        self.ambiguous_overview_label.setWordWrap(True)
        self.ambiguous_overview_label.setMinimumHeight(118)
        self.ambiguous_overview_label.setStyleSheet(
            "color: #d7d9e0; font-size: 12px; background-color: #1b1e27; "
            "border-radius: 6px; padding: 8px;")
        self.ambiguous_overview_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        ambiguous_preview_row.addWidget(self.ambiguous_overview_label, stretch=1)

        self.ambiguous_preview_widgets = (self.ambiguous_poster_label, self.ambiguous_overview_label)
        right.addLayout(ambiguous_preview_row)

        self._ambiguous_poster_cache: dict[int, QPixmap] = {}
        self._poster_worker: CandidatePosterWorker | None = None

        # Genre
        self.genre_label = QLabel()
        self.genre_label.setObjectName("detailMeta")
        self.genre_label.setWordWrap(True)
        right.addWidget(self.genre_label)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Genres, kommagetrennt (z.B. Action, Komödie)")
        self.genre_edit.setVisible(False)
        right.addWidget(self.genre_edit)

        # Besetzung
        self.cast_label = QLabel()
        self.cast_label.setObjectName("detailMeta")
        self.cast_label.setWordWrap(True)
        right.addWidget(self.cast_label)

        self.cast_edit = QLineEdit()
        self.cast_edit.setPlaceholderText("Besetzung, kommagetrennt")
        self.cast_edit.setVisible(False)
        right.addWidget(self.cast_edit)

        self.overview_edit = QTextEdit()
        self.overview_edit.setReadOnly(True)
        right.addWidget(self.overview_edit, stretch=1)

        # "Abspielen" ist die dominante Aktion in diesem Fenster, direkt
        # daneben der (bewusst kurz gehaltene) Trailer-Link-Button -- und im
        # Bearbeiten-Modus, an derselben Stelle, das editierbare
        # Trailer-Link-Feld (falls ein echter Link vorliegt). "YouTube" steht
        # nicht extra im Text -- ist ohnehin klar.
        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶  Abspielen")
        self.play_btn.setObjectName("primaryButton")
        self.play_btn.clicked.connect(self._play)
        play_row.addWidget(self.play_btn)

        self.trailer_btn = QPushButton("▶  Trailer")
        self.trailer_btn.clicked.connect(self._open_trailer)
        play_row.addWidget(self.trailer_btn)

        self.trailer_edit = QLineEdit()
        self.trailer_edit.setPlaceholderText("YouTube-Trailer-Link")
        self.trailer_edit.setVisible(False)
        play_row.addWidget(self.trailer_edit, stretch=1)

        right.addLayout(play_row)

        # Gesehen/Ungesehen + Rewatch zusammen in einer Zeile, unterhalb vom
        # Trailer -- das sind Status-Aktionen, keine Kern-Bedienung wie
        # Abspielen/Trailer.
        status_row = QHBoxLayout()
        self.toggle_seen_btn = QPushButton()
        self.toggle_seen_btn.clicked.connect(self._toggle_seen)
        status_row.addWidget(self.toggle_seen_btn)

        self.rewatch_btn = QPushButton()
        self.rewatch_btn.clicked.connect(self._toggle_rewatch)
        status_row.addWidget(self.rewatch_btn)
        status_row.addStretch(1)
        right.addLayout(status_row)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        right.addLayout(close_row)

        root.addLayout(right, stretch=1)

        self._refresh_ui()
        apply_native_window_chrome(self)

    # ---------------- Anzeige ----------------

    def _refresh_ui(self):
        m = self._movie
        self.title_label.setText(m.display_title)
        meta_parts = []
        if m.year:
            meta_parts.append(str(m.year))
        meta_parts.append("Ungesehen (NEU)" if m.is_unseen else "Gesehen (ARCHIV)")
        meta_parts.append(STATUS_LABELS.get(m.sync_status, m.sync_status))
        if m.rewatch:
            meta_parts.append("Zum Nochmal-Ansehen vorgemerkt")
        self.meta_label.setText(" · ".join(meta_parts))

        if m.sync_status in ("ambiguous", "error") and m.sync_error:
            self.note_label.setText(m.sync_error)
            self.note_label.setVisible(True)
        else:
            self.note_label.setVisible(False)

        self._populate_ambiguous_candidates()

        if m.genre_names:
            self.genre_label.setText(f"Genre: {m.genre_names}")
            self.genre_label.setVisible(True)
        else:
            self.genre_label.setVisible(False)

        if m.cast_names:
            self.cast_label.setText(f"Besetzung: {m.cast_names}")
            self.cast_label.setVisible(True)
        else:
            self.cast_label.setVisible(False)

        self.overview_edit.setPlainText(m.overview or "Keine Beschreibung vorhanden.")

        if m.poster_path:
            pm = QPixmap(str(self._library.dir_covers / m.poster_path))
            if pm.isNull():
                pm = QPixmap(str(self._library.dir_thumbs / m.poster_path))
            if not pm.isNull():
                self.cover_label.setPixmap(
                    pm.scaled(self.cover_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.cover_label.setText("Kein Cover")
        else:
            self.cover_label.setText("Kein Cover")

        self.toggle_seen_btn.setText(
            "Als gesehen markieren" if m.is_unseen else "Als ungesehen markieren")
        self.play_btn.setEnabled(bool(m.video_path))

        # "Rewatch" ergibt nur fuer bereits gesehene (ARCHIV) Filme Sinn.
        self.rewatch_btn.setVisible(not m.is_unseen)
        self.rewatch_btn.setText(
            "✖  Nicht mehr für Rewatch vormerken" if m.rewatch else "🔁  Für Rewatch vormerken")

        has_real_trailer_link = bool(m.trailer_url) and m.trailer_url.startswith("http")
        self.trailer_btn.setVisible(has_real_trailer_link)
        if has_real_trailer_link:
            if m.trailer_language == "de":
                self.trailer_btn.setText("▶  Trailer (DE)")
                self.trailer_btn.setToolTip("")
            elif m.trailer_language == "en":
                self.trailer_btn.setText("▶  Trailer (EN)")
                self.trailer_btn.setToolTip("Kein deutscher Trailer verfügbar")
            else:
                self.trailer_btn.setText("▶  Trailer")
                self.trailer_btn.setToolTip("")

    # ---------------- Bearbeiten-Modus ----------------

    def _enter_edit_mode(self):
        m = self._movie
        self._edit_mode = True

        self.title_edit.setText(m.display_title)
        self.genre_edit.setText(m.genre_names or "")
        self.cast_edit.setText(m.cast_names or "")
        if not m.overview:
            self.overview_edit.setPlainText("")
        self.overview_edit.setReadOnly(False)
        self.overview_edit.setStyleSheet("border: 1px solid #4f7cff;")

        self.title_label.setVisible(False)
        self.title_edit.setVisible(True)
        self.genre_label.setVisible(False)
        self.genre_edit.setVisible(True)
        self.cast_label.setVisible(False)
        self.cast_edit.setVisible(True)

        # Trailer: im Bearbeiten-Modus nur editierbar, wenn es sich um einen
        # echten Link handelt (nicht bloss eine Suchanfrage) -- ansonsten
        # weder Button noch Feld anzeigen.
        self.trailer_btn.setVisible(False)
        has_real_trailer_link = bool(m.trailer_url) and m.trailer_url.startswith("http")
        if has_real_trailer_link:
            self.trailer_edit.setText(m.trailer_url)
            self.trailer_edit.setVisible(True)
        else:
            self.trailer_edit.setVisible(False)

        self.play_btn.setVisible(False)
        self.toggle_seen_btn.setVisible(False)
        self.rewatch_btn.setVisible(False)
        self.edit_btn.setVisible(False)
        self.save_btn.setVisible(True)
        self.cancel_edit_btn.setVisible(True)
        self.delete_btn.setVisible(False)

        for w in self.ambiguous_row_widgets + self.ambiguous_preview_widgets:
            w.setVisible(False)

        self.cover_btn.setVisible(True)
        self.assign_btn.setVisible(True)

    def _leave_edit_mode(self):
        self._edit_mode = False
        self.overview_edit.setReadOnly(True)
        self.overview_edit.setStyleSheet("")

        self.title_edit.setVisible(False)
        self.title_label.setVisible(True)
        self.genre_edit.setVisible(False)
        self.cast_edit.setVisible(False)
        self.trailer_edit.setVisible(False)

        self.play_btn.setVisible(True)
        self.toggle_seen_btn.setVisible(True)
        self.edit_btn.setVisible(True)
        self.save_btn.setVisible(False)
        self.cancel_edit_btn.setVisible(False)
        self.delete_btn.setVisible(True)

        self.cover_btn.setVisible(False)
        self.assign_btn.setVisible(False)

    def _cancel_edit_mode(self):
        self._leave_edit_mode()
        self._refresh_ui()

    def _save_edits(self):
        new_title = self.title_edit.text().strip() or self._movie.display_title
        new_genre = self.genre_edit.text().strip()
        new_cast = self.cast_edit.text().strip()
        new_overview = self.overview_edit.toPlainText().strip()
        new_trailer = self.trailer_edit.text().strip() if self.trailer_edit.isVisible() else None

        self._db.set_manual_edit(
            self._movie.id,
            title=new_title,
            overview=new_overview,
            cast_names=new_cast,
            genre_names=new_genre,
            trailer_url=new_trailer if new_trailer else None,
        )
        self._movie = self._db.get(self._movie.id)
        self._leave_edit_mode()
        self._refresh_ui()
        self.movie_changed.emit(self._movie)

    def _populate_ambiguous_candidates(self):
        m = self._movie
        show = False
        self._ambiguous_poster_cache = {}
        if m.sync_status == "ambiguous" and m.ambiguous_candidates:
            try:
                candidates = json.loads(m.ambiguous_candidates)
            except Exception:
                candidates = []
            if candidates:
                self.ambiguous_combo.blockSignals(True)
                self.ambiguous_combo.clear()
                for c in candidates:
                    year = c.get("year")
                    label = f"{c.get('title')} ({year})" if year else str(c.get("title"))
                    self.ambiguous_combo.addItem(label, c)  # komplettes Dict als itemData
                self.ambiguous_combo.blockSignals(False)
                show = True
                self._start_candidate_poster_fetch(candidates)
                self._on_ambiguous_selection_changed(0)
        for w in self.ambiguous_row_widgets + self.ambiguous_preview_widgets:
            w.setVisible(show)

    def _start_candidate_poster_fetch(self, candidates: list[dict]):
        self._poster_worker = CandidatePosterWorker(self._library, candidates, self)
        self._poster_worker.poster_ready.connect(self._on_candidate_poster_ready)
        self._poster_worker.start()

    def _on_candidate_poster_ready(self, tmdb_id: int, pixmap):
        self._ambiguous_poster_cache[tmdb_id] = pixmap
        current = self.ambiguous_combo.currentData()
        if current and current.get("id") == tmdb_id:
            self._show_ambiguous_poster(pixmap)

    def _on_ambiguous_selection_changed(self, index: int):
        data = self.ambiguous_combo.itemData(index)
        if not data:
            return
        overview = data.get("overview") or "Keine Beschreibung verfügbar."
        escaped = html.escape(overview).replace("\n", "<br>")
        if data.get("overview_language") == "en":
            escaped = "<i>(keine deutsche Beschreibung verfügbar, zeige Englisch)</i><br>" + escaped
        self.ambiguous_overview_label.setText(escaped)

        cached = self._ambiguous_poster_cache.get(data.get("id"))
        if cached is not None:
            self._show_ambiguous_poster(cached)
        else:
            self.ambiguous_poster_label.setPixmap(QPixmap())
            self.ambiguous_poster_label.setText("Lädt Cover …" if data.get("poster_path") else "Kein Cover")

    def _show_ambiguous_poster(self, pixmap):
        self.ambiguous_poster_label.setText("")
        self.ambiguous_poster_label.setPixmap(
            pixmap.scaled(self.ambiguous_poster_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _pick_ambiguous_candidate(self):
        data = self.ambiguous_combo.currentData()
        if not data:
            return
        tmdb_id = data.get("id")
        if tmdb_id is None:
            return
        self.ambiguous_pick_btn.setEnabled(False)
        self.ambiguous_pick_btn.setText("Wird geladen …")
        self._manual_worker = ManualAssignWorker(self._library, self._db, self._movie, tmdb_id, self)
        self._manual_worker.finished_ok.connect(self._on_manual_assign_ok)
        self._manual_worker.failed.connect(self._on_ambiguous_pick_failed)
        self._manual_worker.start()

    def _on_ambiguous_pick_failed(self, message: str):
        self.ambiguous_pick_btn.setEnabled(True)
        self.ambiguous_pick_btn.setText("Übernehmen")
        QMessageBox.warning(self, "Fehler", f"TMDb-Daten konnten nicht geladen werden:\n{message}")

    # ---------------- TMDb-Link manuell zuweisen ----------------

    def _assign_tmdb_manually(self):
        dlg = TmdbLinkInputDialog(self._movie.folder_name, self)
        if dlg.exec() != QDialog.Accepted:
            return
        text = dlg.text()
        if not text:
            return
        tmdb_id = parse_tmdb_id(text)
        if tmdb_id is None:
            QMessageBox.warning(self, "Ungültige Eingabe",
                                 "Daraus konnte keine TMDb-ID erkannt werden.")
            return

        self.assign_btn.setEnabled(False)
        self.assign_btn.setText("Wird geladen …")
        self._manual_worker = ManualAssignWorker(self._library, self._db, self._movie, tmdb_id, self)
        self._manual_worker.finished_ok.connect(self._on_manual_assign_ok)
        self._manual_worker.failed.connect(self._on_manual_assign_failed)
        self._manual_worker.start()

    def _on_manual_assign_ok(self, movie: Movie):
        self._movie = movie
        self.assign_btn.setEnabled(True)
        self.assign_btn.setText("🔗  TMDb-Link manuell zuweisen")
        self.ambiguous_pick_btn.setEnabled(True)
        self.ambiguous_pick_btn.setText("Übernehmen")
        self._leave_edit_mode()
        self._refresh_ui()
        self.movie_changed.emit(self._movie)

    def _on_manual_assign_failed(self, message: str):
        self.assign_btn.setEnabled(True)
        self.assign_btn.setText("🔗  TMDb-Link manuell zuweisen")
        QMessageBox.warning(self, "Fehler", f"TMDb-Daten konnten nicht geladen werden:\n{message}")

    # ---------------- Ordner & Loeschen ----------------

    def _open_folder(self):
        try:
            open_movie_folder(self._library, self._movie)
        except Exception as e:
            QMessageBox.warning(self, "Ordner konnte nicht geöffnet werden", str(e))

    def _delete_movie(self):
        answer = QMessageBox.question(
            self, "Film löschen",
            f"'{self._movie.display_title}' wirklich löschen?\n\n"
            "Der Ordner wird in den Windows-Papierkorb verschoben (nicht "
            "endgültig gelöscht) und kann von dort wiederhergestellt werden.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_movie_to_trash(self._library, self._db, self._movie)
        except Exception as e:
            QMessageBox.warning(self, "Löschen fehlgeschlagen", str(e))
            return
        self.movie_deleted.emit(self._movie.id)
        self.accept()

    # ---------------- Sonstige Aktionen ----------------

    def _open_trailer(self):
        if self._movie.trailer_url:
            webbrowser.open(self._movie.trailer_url)

    def _play(self):
        try:
            play_movie(self._movie)
        except Exception as e:
            QMessageBox.warning(self, "Wiedergabe nicht moeglich", str(e))

    def _toggle_seen(self):
        try:
            if self._movie.is_unseen:
                self._movie = mark_as_seen(self._library, self._db, self._movie)
            else:
                self._movie = mark_as_unseen(self._library, self._db, self._movie)
            self._refresh_ui()
            self.movie_changed.emit(self._movie)
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))

    def _toggle_rewatch(self):
        self._db.set_rewatch(self._movie.id, not self._movie.rewatch)
        self._movie = self._db.get(self._movie.id)
        self._refresh_ui()
        self.movie_changed.emit(self._movie)

    def _change_cover(self):
        dlg = CoverPickerDialog(self._library, self._db, self._movie, self)
        if dlg.exec() == QDialog.Accepted:
            self._movie = self._db.get(self._movie.id)
            self._refresh_ui()
            self.movie_changed.emit(self._movie)
