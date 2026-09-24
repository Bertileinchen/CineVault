from __future__ import annotations

import shutil
import webbrowser
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (QDialog, QFileDialog, QHBoxLayout, QLabel, QLineEdit,
                                QMessageBox, QPushButton, QVBoxLayout, QWidget)

from ..config import Library
from ..database import Database, Movie
from ..metadata_client import download_image_from_url
from ..utils import slugify
from .native_window import apply_native_window_chrome

try:
    from PIL import Image
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


class CoverPickerDialog(QDialog):
    def __init__(self, library: Library, db: Database, movie: Movie, parent=None):
        super().__init__(parent)
        self._library = library
        self._db = db
        self._movie = movie
        self.result_poster_filename: str | None = None

        self.setWindowTitle(f"Cover aendern – {movie.display_title}")
        self.setMinimumWidth(440)

        layout = QVBoxLayout(self)

        preview_row = QHBoxLayout()
        self.preview_label = QLabel()
        self.preview_label.setFixedSize(140, 200)
        self.preview_label.setStyleSheet("background-color: #21242e; border-radius: 8px;")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self._load_current_preview()
        preview_row.addWidget(self.preview_label)

        info_col = QVBoxLayout()
        info_col.addWidget(QLabel(f"<b>{movie.display_title}</b>"))
        info_col.addWidget(QLabel("Aktuelles Cover (falls vorhanden)."))
        info_col.addStretch(1)
        preview_row.addLayout(info_col)
        layout.addLayout(preview_row)

        layout.addWidget(_hline())

        # Option 1: Datei von Festplatte
        file_btn = QPushButton("📁  Von Festplatte waehlen …")
        file_btn.clicked.connect(self._pick_from_file)
        layout.addWidget(file_btn)

        layout.addWidget(_hline())

        # Option 2: URL
        layout.addWidget(QLabel("Bild-URL:"))
        url_row = QHBoxLayout()
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText("https://... (Link auf ein Bild)")
        url_row.addWidget(self.url_edit)
        url_btn = QPushButton("Uebernehmen")
        url_btn.clicked.connect(self._pick_from_url)
        url_row.addWidget(url_btn)
        layout.addLayout(url_row)

        layout.addWidget(_hline())

        # Option 3: Suchmaschine oeffnen
        search_btn = QPushButton("🔍  Google-Bildersuche im Browser oeffnen")
        search_btn.clicked.connect(self._open_search)
        layout.addWidget(search_btn)
        layout.addWidget(QLabel(
            "Tipp: Bild im Browser mit Rechtsklick 'Grafikadresse kopieren' "
            "und oben als URL einfuegen."))

        layout.addWidget(_hline())

        close_row = QHBoxLayout()
        close_row.addStretch(1)
        close_btn = QPushButton("Schliessen")
        close_btn.clicked.connect(self.reject)
        close_row.addWidget(close_btn)
        layout.addLayout(close_row)

        apply_native_window_chrome(self)

    def _load_current_preview(self):
        if self._movie.poster_path:
            pm = QPixmap(str(self._library.dir_thumbs / self._movie.poster_path))
            if not pm.isNull():
                self.preview_label.setPixmap(
                    pm.scaled(self.preview_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
                return
        self.preview_label.setText("Kein Cover")

    def _open_search(self):
        query = self._movie.display_title
        if self._movie.year:
            query += f" {self._movie.year}"
        url = "https://www.google.com/search?tbm=isch&q=" + query.replace(" ", "+") + "+filmposter"
        webbrowser.open(url)

    def _pick_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Cover-Bild waehlen", "", "Bilder (*.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        try:
            data = Path(path).read_bytes()
            self._save_cover(data)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Bild konnte nicht geladen werden:\n{e}")

    def _pick_from_url(self):
        url = self.url_edit.text().strip()
        if not url:
            return
        try:
            data = download_image_from_url(url)
            self._save_cover(data)
        except Exception as e:
            QMessageBox.warning(self, "Fehler", f"Bild konnte nicht heruntergeladen werden:\n{e}")

    def _save_cover(self, data: bytes):
        filename = f"{slugify(self._movie.folder_name)}_{self._movie.id}_manual.jpg"
        cover_path = self._library.dir_covers / filename
        thumb_path = self._library.dir_thumbs / filename

        tmp_path = cover_path.with_suffix(".tmp")
        tmp_path.write_bytes(data)

        if _HAVE_PIL:
            try:
                with Image.open(tmp_path) as img:
                    img = img.convert("RGB")
                    img.save(cover_path, "JPEG", quality=92)
                    thumb = img.copy()
                    thumb.thumbnail((240, 360))
                    thumb.save(thumb_path, "JPEG", quality=85)
                tmp_path.unlink(missing_ok=True)
            except Exception:
                shutil.move(str(tmp_path), str(cover_path))
                shutil.copy(str(cover_path), str(thumb_path))
        else:
            shutil.move(str(tmp_path), str(cover_path))
            shutil.copy(str(cover_path), str(thumb_path))

        self._db.set_manual_cover(self._movie.id, filename)
        self.result_poster_filename = filename
        QMessageBox.information(self, "Erledigt", "Cover wurde aktualisiert.")
        self.accept()


def _hline() -> QWidget:
    line = QWidget()
    line.setFixedHeight(1)
    line.setStyleSheet("background-color: #2a2e3a;")
    return line
