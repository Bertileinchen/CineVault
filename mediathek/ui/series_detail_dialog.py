from __future__ import annotations

import html
import json
import webbrowser

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QHBoxLayout, QLabel,
                                QLineEdit, QMessageBox, QPushButton, QScrollArea,
                                QTextEdit, QVBoxLayout, QWidget)

from ..config import Library, SeriesLibrary
from ..database import Database, Episode, Series
from ..series_player import (delete_series_to_trash, next_unseen_episode, open_series_folder,
                              play_episode, set_series_status, toggle_episode_seen)
from ..utils import parse_tmdb_id
from .detail_dialog import TmdbLinkInputDialog
from .native_window import apply_native_window_chrome
from .series_cover_dialog import SeriesCoverPickerDialog
from .series_sync_worker import SeriesManualAssignWorker
from .sync_worker import CandidatePosterWorker

STATUS_LABELS = {
    "pending": "Metadaten noch nicht synchronisiert",
    "not_found": "Bei TMDb nicht gefunden",
    "ambiguous": "Mehrdeutig – bitte unten auswählen",
    "error": "Fehler beim letzten Sync",
    "ok": "Metadaten aktuell",
    "manual": "Infos von Hand ergänzt",
}

LOCATION_LABELS = {
    "NEU": "Noch nicht begonnen",
    "LAUFEND": "Wird geschaut",
    "ARCHIV": "Abgeschlossen",
}


def _make_separator() -> QWidget:
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet("background-color: #2a2e3a;")
    return line


class SeriesDetailDialog(QDialog):
    """Analog zu MovieDetailDialog -- bewusst dasselbe Funktionsset (Cover
    ändern, TMDb-Link manuell zuweisen, Ordner öffnen, Bearbeiten/Speichern/
    Abbrechen, Löschen, Abspielen, Trailer), NUR ohne Rewatch (ergibt bei
    Serien keinen Sinn) und ZUSAETZLICH mit der Episoden-Checkliste + einer
    Status-Aktion statt des einfachen Gesehen/Ungesehen-Umschalters."""

    series_changed = Signal(object)   # Series
    series_deleted = Signal(int)      # series_id

    def __init__(self, library: Library, series_library: SeriesLibrary, db: Database,
                 series: Series, parent=None):
        super().__init__(parent)
        self._library = library
        self._series_library = series_library
        self._db = db
        self._series = series
        self._edit_mode = False
        self._manual_worker: SeriesManualAssignWorker | None = None
        self._episode_checkboxes: dict[int, QCheckBox] = {}
        self._season_checkboxes: dict[int, QCheckBox] = {}
        self._season_bodies: dict[int, QWidget] = {}
        self._season_toggle_btns: dict[int, QPushButton] = {}
        try:
            self._collapsed_seasons: set[int] = set(json.loads(series.collapsed_seasons or "[]"))
        except (ValueError, TypeError):
            self._collapsed_seasons = set()

        self.setWindowTitle(series.display_title)
        self.setMinimumSize(760, 560)

        root = QHBoxLayout(self)

        # ---------------- Cover links ----------------
        left = QVBoxLayout()
        self.cover_label = QLabel()
        self.cover_label.setFixedSize(220, 320)
        self.cover_label.setStyleSheet("background-color: #21242e; border-radius: 10px;")
        self.cover_label.setAlignment(Qt.AlignCenter)
        left.addWidget(self.cover_label)

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
        self.delete_btn.clicked.connect(self._delete_series)
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

        # Mehrdeutigkeits-Dropdown -- identisch zum Film-Pendant.
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

        self.genre_label = QLabel()
        self.genre_label.setObjectName("detailMeta")
        self.genre_label.setWordWrap(True)
        right.addWidget(self.genre_label)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Genres, kommagetrennt (z.B. Drama, Krimi)")
        self.genre_edit.setVisible(False)
        right.addWidget(self.genre_edit)

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
        self.overview_edit.setMaximumHeight(110)
        right.addWidget(self.overview_edit)

        # "Naechste Folge abspielen" ist die dominante Aktion (Aequivalent
        # zum einfachen Abspielen-Button bei Filmen -- eine Serie besteht
        # aber aus vielen Dateien, daher wird die naechste ungesehene
        # Episode gespielt), direkt daneben der Trailer.
        play_row = QHBoxLayout()
        self.play_btn = QPushButton("▶  Nächste Folge abspielen")
        self.play_btn.setObjectName("primaryButton")
        self.play_btn.clicked.connect(self._play_next)
        play_row.addWidget(self.play_btn)

        self.trailer_btn = QPushButton("▶  Trailer")
        self.trailer_btn.clicked.connect(self._open_trailer)
        play_row.addWidget(self.trailer_btn)

        self.trailer_edit = QLineEdit()
        self.trailer_edit.setPlaceholderText("YouTube-Trailer-Link")
        self.trailer_edit.setVisible(False)
        play_row.addWidget(self.trailer_edit, stretch=1)

        right.addLayout(play_row)

        # Status-Aktion (Aequivalent zum Gesehen/Ungesehen-Umschalter bei
        # Filmen): manueller Wechsel zwischen NEU/LAUFEND/ARCHIV. Automatisch
        # wandert die Serie ja schon beim ersten Abhaken einer Episode nach
        # LAUFEND -- das hier ist der manuelle Weg fuer alle drei Uebergaenge.
        status_row = QHBoxLayout()
        self.status_btn = QPushButton()
        self.status_btn.clicked.connect(self._advance_status)
        status_row.addWidget(self.status_btn)
        status_row.addStretch(1)
        right.addLayout(status_row)

        # ---------------- Episoden-Checkliste ----------------
        episodes_label = QLabel("Episoden")
        episodes_label.setStyleSheet("color: #9aa0ac; font-size: 12px; margin-top: 4px;")
        right.addWidget(episodes_label)

        self.episodes_scroll = QScrollArea()
        self.episodes_scroll.setWidgetResizable(True)
        self.episodes_scroll.setStyleSheet(
            "QScrollArea { background: #1b1e27; border-radius: 8px; border: none; }")
        self.episodes_container = QWidget()
        self.episodes_layout = QVBoxLayout(self.episodes_container)
        self.episodes_layout.setContentsMargins(10, 8, 10, 8)
        self.episodes_layout.setSpacing(2)
        self.episodes_scroll.setWidget(self.episodes_container)
        right.addWidget(self.episodes_scroll, stretch=1)

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self._close_dialog)
        close_row.addWidget(close_btn)
        right.addLayout(close_row)

        root.addLayout(right, stretch=1)

        self._populate_episode_list()
        self._refresh_ui()
        # Scrollbar-Bereich steht erst nach dem ersten Layout-Durchlauf fest
        # -- deshalb einen Tick verzoegert setzen (Standard-Qt-Muster).
        QTimer.singleShot(0, self._restore_scroll_position)
        apply_native_window_chrome(self)

    def _restore_scroll_position(self):
        try:
            self.episodes_scroll.verticalScrollBar().setValue(self._series.episode_scroll_position)
        except Exception:
            pass

    def _save_scroll_position(self):
        try:
            pos = self.episodes_scroll.verticalScrollBar().value()
            self._db.set_series_ui_state(self._series.id, episode_scroll_position=pos)
        except Exception:
            pass

    def _close_dialog(self):
        self._save_scroll_position()
        self.accept()

    def closeEvent(self, event):
        self._save_scroll_position()
        super().closeEvent(event)

    # ---------------- Anzeige ----------------

    def _refresh_ui(self):
        s = self._series
        self.title_label.setText(s.display_title)
        meta_parts = []
        if s.first_air_year:
            meta_parts.append(str(s.first_air_year))
        meta_parts.append(LOCATION_LABELS.get(s.location, s.location))
        meta_parts.append(STATUS_LABELS.get(s.sync_status, s.sync_status))
        episodes = self._db.list_episodes_for_series(s.id)
        active_episodes = [e for e in episodes if e.missing == 0]
        if active_episodes:
            seen_count = sum(1 for e in active_episodes if e.seen)
            meta_parts.append(f"{seen_count}/{len(active_episodes)} Episoden gesehen")
        self.meta_label.setText(" · ".join(meta_parts))

        if s.sync_status in ("ambiguous", "error") and s.sync_error:
            self.note_label.setText(s.sync_error)
            self.note_label.setVisible(True)
        else:
            self.note_label.setVisible(False)

        self._populate_ambiguous_candidates()

        if s.genre_names:
            self.genre_label.setText(f"Genre: {s.genre_names}")
            self.genre_label.setVisible(True)
        else:
            self.genre_label.setVisible(False)

        if s.cast_names:
            self.cast_label.setText(f"Besetzung: {s.cast_names}")
            self.cast_label.setVisible(True)
        else:
            self.cast_label.setVisible(False)

        self.overview_edit.setPlainText(s.overview or "Keine Beschreibung vorhanden.")

        if s.poster_path:
            pm = QPixmap(str(self._series_library.dir_covers / s.poster_path))
            if pm.isNull():
                pm = QPixmap(str(self._series_library.dir_thumbs / s.poster_path))
            if not pm.isNull():
                self.cover_label.setPixmap(
                    pm.scaled(self.cover_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.cover_label.setText("Kein Cover")
        else:
            self.cover_label.setText("Kein Cover")

        nxt = next_unseen_episode(self._db, s)
        if nxt is not None:
            self.play_btn.setEnabled(True)
            self.play_btn.setText(f"▶  S{nxt.season_number:02d}E{nxt.episode_number:02d} abspielen")
        else:
            self.play_btn.setEnabled(bool(active_episodes))
            self.play_btn.setText("▶  Alles gesehen – erste Folge nochmal ansehen"
                                   if active_episodes else "▶  Keine Episoden gefunden")

        if s.location == "NEU":
            self.status_btn.setText("▶  Serie beginnen")
        elif s.location == "LAUFEND":
            self.status_btn.setText("✔  Serie abschliessen")
        else:
            self.status_btn.setText("↺  Serie fortsetzen")

        has_real_trailer_link = bool(s.trailer_url) and s.trailer_url.startswith("http")
        self.trailer_btn.setVisible(has_real_trailer_link)
        if has_real_trailer_link:
            if s.trailer_language == "de":
                self.trailer_btn.setText("▶  Trailer (DE)")
                self.trailer_btn.setToolTip("")
            elif s.trailer_language == "en":
                self.trailer_btn.setText("▶  Trailer (EN)")
                self.trailer_btn.setToolTip("Kein deutscher Trailer verfügbar")
            else:
                self.trailer_btn.setText("▶  Trailer")
                self.trailer_btn.setToolTip("")

    # ---------------- Episoden-Checkliste ----------------

    def _populate_episode_list(self):
        """Baut die Episoden-Checkliste einmalig auf (nicht bei jedem
        Abhaken neu, das waere bei Serien mit vielen hundert Episoden
        unnoetig teuer -- siehe _on_episode_toggled fuer die leichte
        Aktualisierung einzelner Zeilen). Gruppiert IMMER nach Staffel --
        auch wenn es nur eine gibt (dann eben nur 'Staffel 01')."""
        while self.episodes_layout.count():
            item = self.episodes_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._episode_checkboxes = {}
        self._season_checkboxes = {}
        self._season_bodies = {}
        self._season_toggle_btns = {}

        episodes = [e for e in self._db.list_episodes_for_series(self._series.id) if e.missing == 0]
        episodes.sort(key=lambda e: (e.season_number, e.episode_number))
        if not episodes:
            empty_label = QLabel("Keine Episoden gefunden.")
            empty_label.setStyleSheet("color: #5a5f6c;")
            self.episodes_layout.addWidget(empty_label)
            return

        seasons = sorted({e.season_number for e in episodes})
        for i, season_num in enumerate(seasons):
            if i > 0:
                self.episodes_layout.addWidget(_make_separator())

            season_episodes = [e for e in episodes if e.season_number == season_num]
            self.episodes_layout.addWidget(self._make_season_header(season_num, season_episodes))

            body = QWidget()
            body_layout = QVBoxLayout(body)
            body_layout.setContentsMargins(0, 0, 0, 0)
            body_layout.setSpacing(2)
            for ep in season_episodes:
                body_layout.addWidget(self._make_episode_row(ep))
            self.episodes_layout.addWidget(body)
            self._season_bodies[season_num] = body
            body.setVisible(season_num not in self._collapsed_seasons)

        self.episodes_layout.addStretch(1)

    def _make_season_header(self, season_num: int, season_episodes: list[Episode]) -> QWidget:
        """Staffel-Ueberschrift MIT eigener Checkbox davor (hakt alle
        Episoden dieser Staffel auf einmal ab/aus) UND einem Pfeil zum
        Ein-/Ausklappen der darunterliegenden Episoden."""
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 10, 2, 6)
        row_layout.setSpacing(8)

        checkbox = QCheckBox()
        checkbox.setTristate(True)
        checkbox.setCheckState(self._season_check_state(season_episodes))
        checkbox.setToolTip("Alle Episoden dieser Staffel abhaken/entabhaken")
        checkbox.clicked.connect(lambda _checked=False, s=season_num: self._on_season_toggled(s))
        row_layout.addWidget(checkbox)
        self._season_checkboxes[season_num] = checkbox

        toggle_btn = QPushButton("▾" if season_num not in self._collapsed_seasons else "▸")
        toggle_btn.setFlat(True)
        toggle_btn.setFixedWidth(20)
        toggle_btn.setToolTip("Staffel ein-/ausklappen")
        toggle_btn.setStyleSheet(
            "QPushButton { border: none; background: transparent; color: #9aa0ac; "
            "font-size: 13px; } QPushButton:hover { color: #e8e8ec; }")
        toggle_btn.clicked.connect(lambda _checked=False, s=season_num: self._toggle_season_collapse(s))
        row_layout.addWidget(toggle_btn)
        self._season_toggle_btns[season_num] = toggle_btn

        header_label = QLabel(f"Staffel {season_num:02d}")
        header_label.setStyleSheet("color: #e8e8ec; font-size: 15px; font-weight: 700;")
        header_label.setCursor(Qt.PointingHandCursor)
        header_label.mousePressEvent = lambda _ev, s=season_num: self._toggle_season_collapse(s)
        row_layout.addWidget(header_label)
        row_layout.addStretch(1)

        return row

    @staticmethod
    def _season_check_state(season_episodes: list[Episode]):
        seen_count = sum(1 for e in season_episodes if e.seen)
        if seen_count == 0:
            return Qt.Unchecked
        if seen_count == len(season_episodes):
            return Qt.Checked
        return Qt.PartiallyChecked

    def _toggle_season_collapse(self, season_num: int):
        body = self._season_bodies.get(season_num)
        btn = self._season_toggle_btns.get(season_num)
        if body is None:
            return
        now_visible = not body.isVisible()
        body.setVisible(now_visible)
        if btn is not None:
            btn.setText("▾" if now_visible else "▸")
        if now_visible:
            self._collapsed_seasons.discard(season_num)
        else:
            self._collapsed_seasons.add(season_num)
        self._db.set_series_ui_state(
            self._series.id, collapsed_seasons=json.dumps(sorted(self._collapsed_seasons)))

    def _on_season_toggled(self, season_num: int):
        episodes = [e for e in self._db.list_episodes_for_series(self._series.id)
                    if e.missing == 0 and e.season_number == season_num]
        if not episodes:
            return
        # Sind schon alle abgehakt -> diesmal alle ENTabhaken, sonst alle abhaken.
        target = not all(e.seen for e in episodes)
        updated_series = self._series
        try:
            for ep in episodes:
                _, updated_series = toggle_episode_seen(
                    self._series_library, self._db, updated_series, ep, target)
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))
        self._series = updated_series
        self._populate_episode_list()
        self._refresh_ui()
        self.series_changed.emit(self._series)

    def _make_episode_row(self, ep: Episode) -> QWidget:
        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(2, 2, 2, 2)
        row_layout.setSpacing(8)

        checkbox = QCheckBox()
        checkbox.setChecked(bool(ep.seen))
        checkbox.toggled.connect(lambda checked, eid=ep.id: self._on_episode_toggled(eid, checked))
        row_layout.addWidget(checkbox)
        self._episode_checkboxes[ep.id] = checkbox

        label_text = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
        if ep.title:
            label_text += f" – {ep.title}"
        label = QLabel(label_text)
        label.setStyleSheet("color: #d7d9e0;")
        label.setWordWrap(True)
        row_layout.addWidget(label, stretch=1)

        # Deutlich als "Abspielen" erkennbarer runder Button (Play-Dreieck
        # allein war bei kleiner Groesse teils schwer als Button erkennbar).
        play_btn = QPushButton("▶")
        play_btn.setFixedSize(26, 26)
        play_btn.setToolTip("Diese Episode abspielen")
        accent = self._library.config.accent_color
        play_btn.setStyleSheet(
            f"QPushButton {{ background-color: {accent}; color: white; "
            f"border-radius: 13px; font-size: 11px; padding: 0px; border: none; }} "
            f"QPushButton:hover {{ background-color: {accent}; opacity: 0.85; }}"
        )
        play_btn.clicked.connect(lambda _checked=False, eid=ep.id: self._play_episode_by_id(eid))
        row_layout.addWidget(play_btn)

        return row

    def _on_episode_toggled(self, episode_id: int, checked: bool):
        episode = self._db.get_episode(episode_id)
        if episode is None:
            return
        try:
            updated_episode, updated_series = toggle_episode_seen(
                self._series_library, self._db, self._series, episode, checked)
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))
            # Checkbox auf den tatsaechlichen (unveraenderten) Stand zuruecksetzen.
            cb = self._episode_checkboxes.get(episode_id)
            if cb is not None:
                cb.blockSignals(True)
                cb.setChecked(bool(episode.seen))
                cb.blockSignals(False)
            return

        # Staffel-Checkbox (falls vorhanden) auf den neuen Stand bringen,
        # ohne die ganze Liste neu aufzubauen.
        season_cb = self._season_checkboxes.get(episode.season_number)
        if season_cb is not None:
            season_episodes = [e for e in self._db.list_episodes_for_series(self._series.id)
                                if e.missing == 0 and e.season_number == episode.season_number]
            season_cb.blockSignals(True)
            season_cb.setCheckState(self._season_check_state(season_episodes))
            season_cb.blockSignals(False)

        series_location_changed = updated_series.location != self._series.location
        self._series = updated_series
        self._refresh_ui()  # leichter Header-Refresh (Episodenliste selbst bleibt stehen)
        self.series_changed.emit(self._series)

    def _play_episode_by_id(self, episode_id: int):
        episode = self._db.get_episode(episode_id)
        if episode is None:
            return
        try:
            play_episode(self._series_library, self._series, episode)
        except Exception as e:
            QMessageBox.warning(self, "Wiedergabe nicht möglich", str(e))

    def _play_next(self):
        nxt = next_unseen_episode(self._db, self._series)
        if nxt is None:
            episodes = [e for e in self._db.list_episodes_for_series(self._series.id) if e.missing == 0]
            if not episodes:
                return
            nxt = min(episodes, key=lambda e: (e.season_number, e.episode_number))
        try:
            play_episode(self._series_library, self._series, nxt)
        except Exception as e:
            QMessageBox.warning(self, "Wiedergabe nicht möglich", str(e))

    # ---------------- Status-Aktion ----------------

    def _advance_status(self):
        if self._series.location == "NEU":
            target = "LAUFEND"
        elif self._series.location == "LAUFEND":
            answer = QMessageBox.question(
                self, "Serie abschliessen",
                f"'{self._series.display_title}' als abgeschlossen markieren und in den "
                "ARCHIV-Ordner verschieben?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            target = "ARCHIV"
        else:
            target = "LAUFEND"
        try:
            self._series = set_series_status(self._series_library, self._db, self._series, target)
            self._refresh_ui()
            self.series_changed.emit(self._series)
        except Exception as e:
            QMessageBox.warning(self, "Aktion fehlgeschlagen", str(e))

    # ---------------- Bearbeiten-Modus ----------------

    def _enter_edit_mode(self):
        s = self._series
        self._edit_mode = True

        self.title_edit.setText(s.display_title)
        self.genre_edit.setText(s.genre_names or "")
        self.cast_edit.setText(s.cast_names or "")
        if not s.overview:
            self.overview_edit.setPlainText("")
        self.overview_edit.setReadOnly(False)
        self.overview_edit.setStyleSheet("border: 1px solid #4f7cff;")

        self.title_label.setVisible(False)
        self.title_edit.setVisible(True)
        self.genre_label.setVisible(False)
        self.genre_edit.setVisible(True)
        self.cast_label.setVisible(False)
        self.cast_edit.setVisible(True)

        self.trailer_btn.setVisible(False)
        has_real_trailer_link = bool(s.trailer_url) and s.trailer_url.startswith("http")
        if has_real_trailer_link:
            self.trailer_edit.setText(s.trailer_url)
            self.trailer_edit.setVisible(True)
        else:
            self.trailer_edit.setVisible(False)

        self.play_btn.setVisible(False)
        self.status_btn.setVisible(False)
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
        self.status_btn.setVisible(True)
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
        new_title = self.title_edit.text().strip() or self._series.display_title
        new_genre = self.genre_edit.text().strip()
        new_cast = self.cast_edit.text().strip()
        new_overview = self.overview_edit.toPlainText().strip()
        new_trailer = self.trailer_edit.text().strip() if self.trailer_edit.isVisible() else None

        self._db.set_series_manual_edit(
            self._series.id,
            title=new_title,
            overview=new_overview,
            cast_names=new_cast,
            genre_names=new_genre,
            trailer_url=new_trailer if new_trailer else None,
        )
        self._series = self._db.get_series(self._series.id)
        self._leave_edit_mode()
        self._refresh_ui()
        self.series_changed.emit(self._series)

    # ---------------- Mehrdeutigkeit ----------------

    def _populate_ambiguous_candidates(self):
        s = self._series
        show = False
        self._ambiguous_poster_cache = {}
        if s.sync_status == "ambiguous" and s.ambiguous_candidates:
            try:
                candidates = json.loads(s.ambiguous_candidates)
            except Exception:
                candidates = []
            if candidates:
                self.ambiguous_combo.blockSignals(True)
                self.ambiguous_combo.clear()
                for c in candidates:
                    year = c.get("year")
                    label = f"{c.get('title')} ({year})" if year else str(c.get("title"))
                    self.ambiguous_combo.addItem(label, c)
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
        self._manual_worker = SeriesManualAssignWorker(
            self._library, self._series_library, self._db, self._series, tmdb_id, self)
        self._manual_worker.finished_ok.connect(self._on_manual_assign_ok)
        self._manual_worker.failed.connect(self._on_ambiguous_pick_failed)
        self._manual_worker.start()

    def _on_ambiguous_pick_failed(self, message: str):
        self.ambiguous_pick_btn.setEnabled(True)
        self.ambiguous_pick_btn.setText("Übernehmen")
        QMessageBox.warning(self, "Fehler", f"TMDb-Daten konnten nicht geladen werden:\n{message}")

    # ---------------- TMDb-Link manuell zuweisen ----------------

    def _assign_tmdb_manually(self):
        dlg = TmdbLinkInputDialog(self._series.folder_name, self)
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
        self._manual_worker = SeriesManualAssignWorker(
            self._library, self._series_library, self._db, self._series, tmdb_id, self)
        self._manual_worker.finished_ok.connect(self._on_manual_assign_ok)
        self._manual_worker.failed.connect(self._on_manual_assign_failed)
        self._manual_worker.start()

    def _on_manual_assign_ok(self, series: Series):
        self._series = series
        self.assign_btn.setEnabled(True)
        self.assign_btn.setText("🔗  TMDb-Link manuell zuweisen")
        self.ambiguous_pick_btn.setEnabled(True)
        self.ambiguous_pick_btn.setText("Übernehmen")
        self._leave_edit_mode()
        self._populate_episode_list()  # Episodentitel koennen sich durch den Sync geaendert haben
        self._refresh_ui()
        self.series_changed.emit(self._series)

    def _on_manual_assign_failed(self, message: str):
        self.assign_btn.setEnabled(True)
        self.assign_btn.setText("🔗  TMDb-Link manuell zuweisen")
        QMessageBox.warning(self, "Fehler", f"TMDb-Daten konnten nicht geladen werden:\n{message}")

    # ---------------- Ordner & Loeschen ----------------

    def _open_folder(self):
        try:
            open_series_folder(self._series_library, self._series)
        except Exception as e:
            QMessageBox.warning(self, "Ordner konnte nicht geöffnet werden", str(e))

    def _delete_series(self):
        answer = QMessageBox.question(
            self, "Serie löschen",
            f"'{self._series.display_title}' wirklich löschen?\n\n"
            "Der komplette Serienordner wird in den Windows-Papierkorb verschoben "
            "(nicht endgültig gelöscht) und kann von dort wiederhergestellt werden.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            delete_series_to_trash(self._series_library, self._db, self._series)
        except Exception as e:
            QMessageBox.warning(self, "Löschen fehlgeschlagen", str(e))
            return
        self.series_deleted.emit(self._series.id)
        self.accept()

    # ---------------- Sonstige Aktionen ----------------

    def _open_trailer(self):
        if self._series.trailer_url:
            webbrowser.open(self._series.trailer_url)

    def _change_cover(self):
        dlg = SeriesCoverPickerDialog(self._series_library, self._db, self._series, self)
        if dlg.exec() == QDialog.Accepted:
            self._series = self._db.get_series(self._series.id)
            self._refresh_ui()
            self.series_changed.emit(self._series)
