"""
Konfigurationsverwaltung.

Grundsatz: Im FILME-Ordner liegen ausschliesslich die Filme selbst (NEU/
ARCHIV) -- keinerlei Programmdaten. Datenbank, Cover, Einstellungen (inkl.
TMDb-API-Key) und der Zeiger auf den FILME-Ordner liegen alle zusammen in
einem "Mediathek"-Unterordner direkt NEBEN der .exe (bzw. neben main.py im
Entwicklungsbetrieb) -- also im Programmordner selbst, z.B.
C:\\Programme\\CineVault\\Mediathek\\.

Das ergibt Sinn, weil ohnehin schon die Datenbank dort liegt: Tauscht man
nur die .exe/die Skript-Dateien aus (neue Version im selben Ordner), bleiben
alle Daten -- inklusive Cover -- automatisch erhalten, da "Mediathek" ein
eigener Unterordner ist. Der FILME-Ordner mit den eigentlichen Filmen bleibt
dabei vollkommen unberuehrt.
"""
from __future__ import annotations

import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "CineVault"

# Ordnernamen innerhalb von FILME bzw. SERIEN
DIR_NEU = "NEU"
DIR_ARCHIV = "ARCHIV"
DIR_LAUFEND = "LAUFEND"   # nur bei Serien: begonnen, aber noch nicht fertig/finalisiert

# Ordnername innerhalb des Programmordners
DIR_PROGRAMMDATEN = "Mediathek"   # enthaelt DB + config.json + pointer.json + MEDIA
DIR_MEDIA = "MEDIA"               # Unterordner von DIR_PROGRAMMDATEN


def program_dir() -> Path:
    """Der Ordner, in dem die .exe liegt (PyInstaller --onefile) bzw. im
    Entwicklungsbetrieb der Ordner, der main.py enthaelt."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    # sys.argv[0] ist beim normalen "python main.py"-Start main.py selbst
    return Path(sys.argv[0]).resolve().parent


def app_data_dir() -> Path:
    p = program_dir() / DIR_PROGRAMMDATEN
    p.mkdir(parents=True, exist_ok=True)
    return p


def app_assets_dir() -> Path:
    """Pfad zum 'assets'-Ordner (Icons etc.). Bei einer PyInstaller-.exe
    liegen mitgepackte Dateien im temporaeren Entpackordner (sys._MEIPASS),
    nicht neben der .exe selbst -- daher bewusst anders aufgeloest als
    program_dir()."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        base = Path(sys._MEIPASS)
    else:
        base = Path(__file__).resolve().parent.parent
    return base / "assets"


def pointer_file() -> Path:
    return app_data_dir() / "pointer.json"


def _read_pointer_data() -> dict:
    pf = pointer_file()
    if pf.exists():
        try:
            return json.loads(pf.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _write_pointer_data(data: dict) -> None:
    pointer_file().write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_filme_root() -> Path | None:
    data = _read_pointer_data()
    root = Path(data.get("filme_root", ""))
    if str(data.get("filme_root", "")) and root.exists():
        return root
    return None


def save_filme_root(root: Path) -> None:
    data = _read_pointer_data()
    data["filme_root"] = str(root)
    _write_pointer_data(data)


def load_serien_root() -> Path | None:
    """Der SERIEN-Wurzelordner ist komplett optional -- wer die Serien-
    Funktion nicht nutzt, muss dafuer nichts einrichten."""
    data = _read_pointer_data()
    root = Path(data.get("serien_root", ""))
    if str(data.get("serien_root", "")) and root.exists():
        return root
    return None


def save_serien_root(root: Path) -> None:
    data = _read_pointer_data()
    data["serien_root"] = str(root)
    _write_pointer_data(data)


@dataclass
class LibraryConfig:
    tmdb_api_key: str = ""
    tmdb_language: str = "de-DE"
    sync_concurrency: int = 6
    backup_path: str = ""
    backup_auto: bool = False
    streaming_enabled: bool = False
    streaming_port: int = 8765
    accent_color: str = "#4f7cff"
    extra: dict = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> "LibraryConfig":
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                return cls(
                    tmdb_api_key=data.get("tmdb_api_key", ""),
                    tmdb_language=data.get("tmdb_language", "de-DE"),
                    sync_concurrency=data.get("sync_concurrency", 6),
                    backup_path=data.get("backup_path", ""),
                    backup_auto=data.get("backup_auto", False),
                    streaming_enabled=data.get("streaming_enabled", False),
                    streaming_port=data.get("streaming_port", 8765),
                    accent_color=data.get("accent_color", "#4f7cff"),
                    extra=data.get("extra", {}),
                )
            except Exception:
                pass
        return cls()

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "tmdb_api_key": self.tmdb_api_key,
                    "tmdb_language": self.tmdb_language,
                    "sync_concurrency": self.sync_concurrency,
                    "backup_path": self.backup_path,
                    "backup_auto": self.backup_auto,
                    "streaming_enabled": self.streaming_enabled,
                    "streaming_port": self.streaming_port,
                    "accent_color": self.accent_color,
                    "extra": self.extra,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )


class Library:
    """Buendelt alle Pfade: NEU/ARCHIV liegen in FILME, alles andere
    (Datenbank, Cover, Einstellungen) liegt im Programmordner (siehe
    app_data_dir())."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir_neu = self.root / DIR_NEU
        self.dir_archiv = self.root / DIR_ARCHIV

        self.dir_programmdaten = app_data_dir()
        self.db_path = self.dir_programmdaten / "mediathek.db"
        self.config_path = self.dir_programmdaten / "config.json"

        self.dir_media = self.dir_programmdaten / DIR_MEDIA
        self.dir_covers = self.dir_media / "covers"
        self.dir_thumbs = self.dir_media / "thumbs"

        for d in (self.dir_neu, self.dir_archiv, self.dir_media,
                  self.dir_covers, self.dir_thumbs):
            d.mkdir(parents=True, exist_ok=True)

        self._migrate_legacy_data()

        self.config = LibraryConfig.load(self.config_path)

    def _migrate_legacy_data(self) -> None:
        """Migriert Daten aus aelteren Programmversionen, damit nichts
        verloren geht:
        1. DB/Config aus FILME\\Mediathek\\... (sehr alte Version, als
           Programmdaten noch im FILME-Ordner lagen).
        2. Cover aus FILME\\MEDIA\\... (vorherige Version, in der nur die
           Cover noch im FILME-Ordner lagen, DB aber schon im
           Programmordner)."""
        # 1. DB + Config
        legacy_dir = self.root / DIR_PROGRAMMDATEN
        if not self.db_path.exists() and legacy_dir.exists():
            legacy_db = legacy_dir / "mediathek.db"
            legacy_config = legacy_dir / "config.json"
            try:
                if legacy_db.exists():
                    legacy_db.replace(self.db_path)
                if legacy_config.exists():
                    legacy_config.replace(self.config_path)
            except OSError:
                pass

        # 2. Cover (MEDIA), vormals direkt im FILME-Ordner
        legacy_media = self.root / DIR_MEDIA
        if legacy_media.exists() and legacy_media != self.dir_media:
            for sub in ("covers", "thumbs"):
                legacy_sub = legacy_media / sub
                target_sub = self.dir_media / sub
                if not legacy_sub.exists():
                    continue
                target_sub.mkdir(parents=True, exist_ok=True)
                for f in legacy_sub.iterdir():
                    dest = target_sub / f.name
                    if not dest.exists():
                        try:
                            shutil.move(str(f), str(dest))
                        except OSError:
                            pass
            # Leeren alten MEDIA-Ordner in FILME aufraeumen, falls jetzt leer.
            try:
                for sub in ("covers", "thumbs"):
                    legacy_sub = legacy_media / sub
                    if legacy_sub.exists() and not any(legacy_sub.iterdir()):
                        legacy_sub.rmdir()
                if not any(legacy_media.iterdir()):
                    legacy_media.rmdir()
            except OSError:
                pass

    def save_config(self) -> None:
        self.config.save(self.config_path)


class SeriesLibrary:
    """Analog zu Library, aber fuer Serien: eigener Wurzelordner mit NEU/
    LAUFEND/ARCHIV (der Zwischenzustand 'begonnen, aber noch nicht fertig'
    gibt es nur bei Serien). Nutzt bewusst dieselbe Datenbank, Config und
    denselben Programmdaten-Ordner wie die Film-Library -- eigener
    Programmbereich in der Oberflaeche, aber keine zweite, separate
    Infrastruktur noetig. Cover liegen in einem eigenen Unterordner, damit
    sie sich mit Film-Covern nicht in die Quere kommen koennen. Ein
    bestehendes Backup sichert Serien-Daten dadurch automatisch mit, ohne
    dass dafuer irgendetwas Zusaetzliches noetig war."""

    def __init__(self, root: Path, movie_library: Library):
        self.root = Path(root)
        self.dir_neu = self.root / DIR_NEU
        self.dir_laufend = self.root / DIR_LAUFEND
        self.dir_archiv = self.root / DIR_ARCHIV

        self.dir_media = movie_library.dir_media / "series"
        self.dir_covers = self.dir_media / "covers"
        self.dir_thumbs = self.dir_media / "thumbs"

        for d in (self.dir_neu, self.dir_laufend, self.dir_archiv,
                  self.dir_media, self.dir_covers, self.dir_thumbs):
            d.mkdir(parents=True, exist_ok=True)

    def dir_for_location(self, location: str) -> Path:
        return {"NEU": self.dir_neu, "LAUFEND": self.dir_laufend, "ARCHIV": self.dir_archiv}[location]
