from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QDialog, QFileDialog, QFormLayout,
                                QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
                                QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..config import Library, load_serien_root, save_filme_root, save_serien_root
from ..database import Database
from ..streaming import get_local_ip
from ..version import __version__
from .native_window import apply_native_window_chrome
from .styles import DEFAULT_ACCENT
from .sync_worker import BackupWorker


def _generate_qr_pixmap(data: str) -> QPixmap | None:
    """Erzeugt einen QR-Code als QPixmap. Gibt None zurueck, falls das
    optionale 'qrcode'-Paket (noch) nicht installiert ist -- die
    Netzwerkfreigabe selbst funktioniert davon unabhaengig, der QR-Code ist
    nur eine bequeme Abkuerzung zum Eintippen der Adresse."""
    try:
        import io
        import qrcode
        from qrcode.image.pil import PilImage
    except ImportError:
        return None

    img = qrcode.make(data, image_factory=PilImage, box_size=6, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    pm = QPixmap()
    pm.loadFromData(buf.getvalue())
    return pm if not pm.isNull() else None


class SettingsDialog(QDialog):
    def __init__(self, library: Library, db: Database, parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self.diagnostic_result: str | None = None   # wird von aussen (MainWindow) ausgelesen
        self.filme_root_changed = False              # dito -- signalisiert "Neustart noetig"
        self.series_root_changed = False              # dito -- Serien-Bereich neu laden (kein Neustart noetig)
        self._backup_worker: BackupWorker | None = None

        self.setWindowTitle("Einstellungen")
        self.setMinimumSize(500, 480)

        root_layout = QVBoxLayout(self)

        tabs = QTabWidget()
        tabs.addTab(self._build_appearance_tab(), "Darstellung")
        tabs.addTab(self._build_tmdb_tab(), "TMDb")
        tabs.addTab(self._build_paths_tab(), "Dateipfade")
        tabs.addTab(self._build_network_tab(), "Netzwerk")
        tabs.addTab(self._build_diagnostics_tab(), "Diagnose")
        root_layout.addWidget(tabs, stretch=1)

        btn_row = QHBoxLayout()
        version_label = QLabel(f"CineVault v{__version__}")
        version_label.setStyleSheet("color: #454b5c; font-size: 11px;")
        btn_row.addWidget(version_label)
        btn_row.addStretch(1)
        save_btn = QPushButton("Speichern")
        save_btn.setObjectName("primaryButton")
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        cancel_btn = QPushButton("Abbrechen")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        root_layout.addLayout(btn_row)

        apply_native_window_chrome(self)

    # ================================================================
    # Tab: Darstellung
    # ================================================================

    def _build_appearance_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        appearance_row = QHBoxLayout()
        appearance_row.addWidget(QLabel("Akzentfarbe:"))
        self.accent_color = self._library.config.accent_color
        self.accent_swatch_btn = QPushButton("")
        self.accent_swatch_btn.setFixedSize(36, 28)
        self.accent_swatch_btn.setToolTip("Klicken, um eine andere Farbe zu wählen")
        self.accent_swatch_btn.clicked.connect(self._pick_accent_color)
        appearance_row.addWidget(self.accent_swatch_btn)
        reset_accent_btn = QPushButton("Zurücksetzen")
        reset_accent_btn.clicked.connect(self._reset_accent_color)
        appearance_row.addWidget(reset_accent_btn)
        appearance_row.addStretch(1)
        layout.addLayout(appearance_row)
        self._update_accent_swatch()

        layout.addStretch(1)
        return w

    def _update_accent_swatch(self):
        self.accent_swatch_btn.setStyleSheet(
            f"background-color: {self.accent_color}; border-radius: 6px; "
            f"border: 1px solid #2f3340;"
        )

    def _pick_accent_color(self):
        color = QColorDialog.getColor(QColor(self.accent_color), self, "Akzentfarbe wählen")
        if color.isValid():
            self.accent_color = color.name()
            self._update_accent_swatch()

    def _reset_accent_color(self):
        self.accent_color = DEFAULT_ACCENT
        self._update_accent_swatch()

    # ================================================================
    # Tab: TMDb
    # ================================================================

    def _build_tmdb_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        info = QLabel(
            'Kostenlosen TMDb-API-Key erstellen: '
            '<a href="https://www.themoviedb.org/settings/api" style="color:#4f7cff;">'
            'themoviedb.org/settings/api</a>')
        info.setOpenExternalLinks(True)
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self.api_key_edit = QLineEdit(self._library.config.tmdb_api_key)
        form.addRow("TMDb API-Key:", self.api_key_edit)

        self.language_edit = QLineEdit(self._library.config.tmdb_language)
        form.addRow("Sprache (z.B. de-DE):", self.language_edit)

        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 10)
        self.concurrency_spin.setValue(self._library.config.sync_concurrency)
        form.addRow("Gleichzeitige Anfragen beim Sync:", self.concurrency_spin)

        layout.addLayout(form)
        layout.addStretch(1)
        return w

    # ================================================================
    # Tab: Dateipfade (FILME-Ordner + Backup)
    # ================================================================

    def _build_paths_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # ---- FILME-Ordner ----
        filme_label = QLabel("Bibliothek")
        filme_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        layout.addWidget(filme_label)

        filme_row = QHBoxLayout()
        self.filme_path_label = QLabel(str(self._library.root))
        self.filme_path_label.setStyleSheet("color: #b8bcc4; font-size: 12px;")
        self.filme_path_label.setWordWrap(True)
        filme_row.addWidget(self.filme_path_label, stretch=1)
        change_filme_btn = QPushButton("Ändern …")
        change_filme_btn.clicked.connect(self._change_filme_root)
        filme_row.addWidget(change_filme_btn)
        layout.addLayout(filme_row)

        layout.addSpacing(16)

        # ---- SERIEN-Ordner (komplett optional -- eigener Programmbereich) ----
        serien_label = QLabel("Serien (eigener, komplett getrennter Ordner)")
        serien_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        layout.addWidget(serien_label)

        serien_row = QHBoxLayout()
        current_serien_root = load_serien_root()
        self.serien_path_label = QLabel(str(current_serien_root) if current_serien_root else "(nicht eingerichtet)")
        self.serien_path_label.setStyleSheet("color: #b8bcc4; font-size: 12px;")
        self.serien_path_label.setWordWrap(True)
        serien_row.addWidget(self.serien_path_label, stretch=1)
        change_serien_btn = QPushButton("Ändern …" if current_serien_root else "Einrichten …")
        change_serien_btn.clicked.connect(self._change_serien_root)
        serien_row.addWidget(change_serien_btn)
        layout.addLayout(serien_row)

        layout.addSpacing(16)

        # ---- Backup ----
        backup_label = QLabel("Backup – sichert den kompletten Programmordner (Code + Datenbank + Cover)")
        backup_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        backup_label.setWordWrap(True)
        layout.addWidget(backup_label)

        backup_path_row = QHBoxLayout()
        self.backup_path_edit = QLineEdit(self._library.config.backup_path)
        self.backup_path_edit.setPlaceholderText("Zielordner für Backups auswählen …")
        backup_path_row.addWidget(self.backup_path_edit, stretch=1)
        browse_backup_btn = QPushButton("Durchsuchen …")
        browse_backup_btn.clicked.connect(self._browse_backup_path)
        backup_path_row.addWidget(browse_backup_btn)
        layout.addLayout(backup_path_row)

        backup_action_row = QHBoxLayout()
        self.backup_auto_check = QCheckBox("Automatisch bei jedem Beenden sichern")
        self.backup_auto_check.setChecked(self._library.config.backup_auto)
        backup_action_row.addWidget(self.backup_auto_check)
        backup_action_row.addStretch(1)
        self.backup_now_btn = QPushButton("Jetzt Backup erstellen")
        self.backup_now_btn.clicked.connect(self._backup_now)
        backup_action_row.addWidget(self.backup_now_btn)
        layout.addLayout(backup_action_row)

        self.backup_status_label = QLabel("")
        self.backup_status_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        self.backup_status_label.setWordWrap(True)
        layout.addWidget(self.backup_status_label)

        layout.addStretch(1)
        return w

    def _change_filme_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Neuen FILME-Ordner auswählen", str(self._library.root))
        if not chosen:
            return
        new_root = Path(chosen)
        answer = QMessageBox.question(
            self, "FILME-Ordner ändern",
            f"CineVault soll ab jetzt hier nach Filmen suchen:\n{new_root}\n\n"
            "Datenbank, Cover und Einstellungen bleiben unverändert erhalten "
            "(die liegen ja im Programmordner, nicht im FILME-Ordner selbst).\n\n"
            "CineVault muss danach einmal neu gestartet werden. Fortfahren?"
        )
        if answer != QMessageBox.Yes:
            return
        save_filme_root(new_root)
        self.filme_path_label.setText(str(new_root))
        self.filme_root_changed = True
        QMessageBox.information(
            self, "FILME-Ordner geändert",
            "Gespeichert. Bitte CineVault jetzt neu starten, damit die Änderung wirksam wird."
        )

    def _change_serien_root(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "SERIEN-Ordner auswählen", str(self._library.root))
        if not chosen:
            return
        new_root = Path(chosen)
        save_serien_root(new_root)
        self.serien_path_label.setText(str(new_root))
        self.series_root_changed = True
        QMessageBox.information(
            self, "SERIEN-Ordner eingerichtet",
            f"Gespeichert: {new_root}\n\n"
            "Der Serien-Bereich wird beim Schliessen dieses Dialogs automatisch geladen."
        )

    def _browse_backup_path(self):
        chosen = QFileDialog.getExistingDirectory(
            self, "Backup-Zielordner auswählen", self.backup_path_edit.text().strip())
        if chosen:
            self.backup_path_edit.setText(chosen)

    def _backup_now(self):
        path_text = self.backup_path_edit.text().strip()
        if not path_text:
            QMessageBox.warning(self, "Backup", "Bitte zuerst einen Zielordner auswählen.")
            return

        self.backup_now_btn.setEnabled(False)
        self.backup_now_btn.setText("⏳ Backup läuft …")
        self.backup_status_label.setText("Backup läuft, bitte warten …")

        self._backup_worker = BackupWorker(self._library, self._db, Path(path_text), self)
        self._backup_worker.finished_ok.connect(self._on_backup_finished)
        self._backup_worker.failed.connect(self._on_backup_failed)
        self._backup_worker.start()

    def _on_backup_finished(self, result):
        self.backup_now_btn.setEnabled(True)
        self.backup_now_btn.setText("Jetzt Backup erstellen")
        self.backup_status_label.setText(f"Zuletzt gesichert: {result.path}")
        QMessageBox.information(
            self, "Backup erstellt",
            f"Backup gespeichert unter:\n{result.path}\n\n"
            f"{result.files_copied} neue/geänderte Dateien übertragen, "
            f"{result.files_skipped} bereits vorhandene übersprungen."
        )

    def _on_backup_failed(self, message: str):
        self.backup_now_btn.setEnabled(True)
        self.backup_now_btn.setText("Jetzt Backup erstellen")
        self.backup_status_label.setText("")
        QMessageBox.warning(self, "Backup fehlgeschlagen", message)

    # ================================================================
    # Tab: Netzwerk (Streaming)
    # ================================================================

    def _build_network_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        streaming_label = QLabel(
            "Netzwerkfreigabe – im selben WLAN erreichbar (Android). Zeigt Filme "
            "und Serien; einzige Ausnahme vom sonst reinen Lesezugriff: Episoden "
            "können von unterwegs als gesehen/ungesehen markiert werden.")
        streaming_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        streaming_label.setWordWrap(True)
        layout.addWidget(streaming_label)

        self.streaming_enabled_check = QCheckBox("Aktivieren")
        self.streaming_enabled_check.setChecked(self._library.config.streaming_enabled)
        self.streaming_enabled_check.toggled.connect(self._update_streaming_hint)
        layout.addWidget(self.streaming_enabled_check)

        streaming_port_row = QHBoxLayout()
        streaming_port_row.addWidget(QLabel("Port:"))
        self.streaming_port_spin = QSpinBox()
        self.streaming_port_spin.setRange(1024, 65535)
        self.streaming_port_spin.setValue(self._library.config.streaming_port)
        self.streaming_port_spin.valueChanged.connect(self._update_streaming_hint)
        streaming_port_row.addWidget(self.streaming_port_spin)
        streaming_port_row.addStretch(1)
        layout.addLayout(streaming_port_row)

        layout.addSpacing(12)

        # Prominenter, zentrierter Block mit QR-Code + Adresse -- das ist ja
        # der Teil, den man am Handy tatsaechlich braucht.
        prominent_block = QVBoxLayout()
        prominent_block.setSpacing(10)

        self.qr_label = QLabel()
        self.qr_label.setFixedSize(180, 180)
        self.qr_label.setAlignment(Qt.AlignCenter)
        self.qr_label.setStyleSheet("background-color: #ffffff; border-radius: 10px;")
        prominent_block.addWidget(self.qr_label, alignment=Qt.AlignHCenter)

        self.streaming_url_label = QLabel("")
        self.streaming_url_label.setAlignment(Qt.AlignCenter)
        self.streaming_url_label.setStyleSheet(
            "color: #ffffff; font-size: 17px; font-weight: 600; "
            "background-color: #21242e; border: 1px solid #2f3340; "
            "border-radius: 8px; padding: 10px 16px;")
        prominent_block.addWidget(self.streaming_url_label)

        self.streaming_hint_label = QLabel("")
        self.streaming_hint_label.setStyleSheet("color: #7d8595; font-size: 12px;")
        self.streaming_hint_label.setWordWrap(True)
        self.streaming_hint_label.setAlignment(Qt.AlignCenter)
        self.streaming_hint_label.setFixedWidth(260)
        prominent_block.addWidget(self.streaming_hint_label)

        centered_row = QHBoxLayout()
        centered_row.addStretch(1)
        centered_row.addLayout(prominent_block)
        centered_row.addStretch(1)
        layout.addLayout(centered_row)
        layout.addSpacing(8)
        self._update_streaming_hint()

        warning_label = QLabel(
            "⚠ Rein lesend – niemand im WLAN kann darüber etwas löschen, bearbeiten "
            "oder synchronisieren. Trotzdem: nur in vertrauenswürdigen Netzwerken "
            "aktivieren (z. B. nicht im Firmen- oder Gäste-WLAN)."
        )
        warning_label.setStyleSheet("color: #e0a83e; font-size: 11px;")
        warning_label.setWordWrap(True)
        layout.addWidget(warning_label)

        layout.addStretch(1)
        return w

    def _update_streaming_hint(self):
        if self.streaming_enabled_check.isChecked():
            ip = get_local_ip()
            port = self.streaming_port_spin.value()
            url = f"http://{ip}:{port}"

            self.streaming_url_label.setText(url)
            self.streaming_url_label.setVisible(True)

            hint = (
                "Am Handy im selben WLAN im Browser aufrufen oder QR-Code "
                "scannen (wirksam nach dem Speichern)."
            )
            self.streaming_hint_label.setText(hint)

            qr_pixmap = _generate_qr_pixmap(url)
            if qr_pixmap is not None:
                self.qr_label.setPixmap(
                    qr_pixmap.scaled(self.qr_label.size(), Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation))
                self.qr_label.setVisible(True)
            else:
                self.qr_label.setVisible(False)
        else:
            self.streaming_url_label.setVisible(False)
            self.streaming_hint_label.setText("")
            self.qr_label.setVisible(False)

    # ================================================================
    # Tab: Diagnose
    # ================================================================

    def _build_diagnostics_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)

        # Kleiner, bewusst unauffaelliger Diagnose-Bereich -- wird man
        # vermutlich nur selten brauchen.
        diag_label = QLabel("Diagnose-Filter (Filme) – Übersicht auf Filme mit fehlenden Infos filtern")
        diag_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        diag_label.setWordWrap(True)
        layout.addWidget(diag_label)

        for text, mode in (
            ("Nicht synchronisierte Filme anzeigen", "unsynced"),
            ("Mehrdeutige Filme anzeigen", "ambiguous_only"),
            ("Filme ohne Beschreibung anzeigen", "no_overview"),
            ("Filme ohne Cover anzeigen", "no_cover"),
            ("Fehlende Filme anzeigen (Ordner nicht mehr gefunden)", "missing_only"),
        ):
            btn = self._make_diagnostic_link(text, mode)
            layout.addWidget(btn)

        layout.addSpacing(16)

        # Dieselben Diagnose-Filter, aber fuer den Serien-Bereich -- eigene
        # Codes ("series_"-Prefix), damit die Oberflaeche weiss, auf welchen
        # der beiden (komplett getrennten) Bereiche sie angewendet werden.
        diag_series_label = QLabel("Diagnose-Filter (Serien)")
        diag_series_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        diag_series_label.setWordWrap(True)
        layout.addWidget(diag_series_label)

        for text, mode in (
            ("Nicht synchronisierte Serien anzeigen", "series_unsynced"),
            ("Mehrdeutige Serien anzeigen", "series_ambiguous_only"),
            ("Serien ohne Beschreibung anzeigen", "series_no_overview"),
            ("Serien ohne Cover anzeigen", "series_no_cover"),
            ("Fehlende Serien anzeigen (Ordner nicht mehr gefunden)", "series_missing_only"),
        ):
            btn = self._make_diagnostic_link(text, mode)
            layout.addWidget(btn)

        layout.addSpacing(16)

        # Eigener Bereich, bewusst getrennt von den reinen Filtern oben:
        # das hier ist keine Ansichts-Filterung, sondern eine echte Aktion,
        # die Netzwerkanfragen ausloest und Daten ergaenzt.
        action_label = QLabel("Nachladen – ergänzt fehlende Daten bei bereits zugeordneten Filmen")
        action_label.setStyleSheet("color: #5a5f6c; font-size: 11px;")
        action_label.setWordWrap(True)
        layout.addWidget(action_label)

        reload_extras_btn = self._make_diagnostic_link(
            "Fehlende Besetzung/Genre/Trailer nachladen", "reload_extras")
        layout.addWidget(reload_extras_btn)

        layout.addStretch(1)
        return w

    def _make_diagnostic_link(self, text: str, mode: str) -> QPushButton:
        btn = QPushButton(text)
        btn.setFlat(True)
        btn.setCursor(Qt.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { color: #7d8595; text-align: left; border: none; "
            "background: transparent; padding: 2px 0px; font-size: 12px; } "
            "QPushButton:hover { color: #4f7cff; }"
        )
        btn.clicked.connect(lambda: self._show_diagnostic(mode))
        return btn

    def _show_diagnostic(self, mode: str):
        self.diagnostic_result = mode
        self.accept()

    # ================================================================
    # Speichern
    # ================================================================

    def _save(self):
        self._library.config.tmdb_api_key = self.api_key_edit.text().strip()
        self._library.config.tmdb_language = self.language_edit.text().strip() or "de-DE"
        self._library.config.sync_concurrency = self.concurrency_spin.value()
        self._library.config.backup_path = self.backup_path_edit.text().strip()
        self._library.config.backup_auto = self.backup_auto_check.isChecked()
        self._library.config.streaming_enabled = self.streaming_enabled_check.isChecked()
        self._library.config.streaming_port = self.streaming_port_spin.value()
        self._library.config.accent_color = self.accent_color
        self._library.save_config()
        self.accept()
