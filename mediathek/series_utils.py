"""
Erkennung von Staffel-/Episodennummern aus Ordner- und Dateinamen.

Unterstuetzte Muster (deckt die ueblichen Konventionen ab):
- Staffelordner: "Staffel 01", "Staffel 1", "Season 01", "Season 1",
  oder ein Ordner, dessen Name ausschliesslich aus "S01"/"S1" besteht.
- Episodendateien: "S01E02", "1x02", "Episode 02", "Folge 02", "Ep 02",
  oder ersatzweise eine fuehrende Nummer im Dateinamen ("02 - Titel.mkv").
- Findet sich in einem Dateinamen gar keine Nummer, wird sie ueber die
  alphabetische Reihenfolge innerhalb der Staffel vergeben (siehe
  resolve_episode_numbers) -- deckt den Normalfall "1 Datei = 1 Folge,
  vernuenftig benannt" zuverlaessig ab, auch wenn keine explizite Nummer im
  Dateinamen steht.
"""
from __future__ import annotations

import re
from pathlib import Path

_SXXEYY_RE = re.compile(r"[Ss](\d{1,2})[\s\.\-_]*[Ee](\d{1,3})")
_NXM_RE = re.compile(r"(?<!\d)(\d{1,2})[xX](\d{1,3})(?!\d)")

_SEASON_KEYWORD_RE = re.compile(r"(?:staffel|season)\s*0*(\d{1,3})\b", re.IGNORECASE)
_SEASON_SHORT_RE = re.compile(r"^s\s*0*(\d{1,3})$", re.IGNORECASE)

_NON_EPISODE_KEYWORDS = (
    "extras", "extra", "bonus", "bonusmaterial", "behind the scenes",
    "making of", "featurette", "deleted scenes", "outtakes", "bloopers",
    "interview", "interviews", "trailer", "trailers", "sample", "samples",
    "artwork", "poster", "posters", "soundtrack", "subs", "untertitel", "subtitles",
)


def is_non_episode_folder_name(name: str) -> bool:
    """Ordner, die typischerweise KEINE eigentlichen Episoden enthalten
    (Bonus-/Zusatzmaterial) -- werden auch dann uebersprungen, wenn
    zufaellig eine Videodatei drinsteckt (z.B. ein Making-of-Clip)."""
    lowered = name.strip().lower()
    return any(keyword in lowered for keyword in _NON_EPISODE_KEYWORDS)

_EPISODE_KEYWORD_RE = re.compile(r"(?:episode|folge|ep)\s*0*(\d{1,4})\b", re.IGNORECASE)
_LEADING_NUMBER_RE = re.compile(r"^0*(\d{1,4})\b")
_ANY_NUMBER_RE = re.compile(r"(\d{1,4})")
_NATURAL_SPLIT_RE = re.compile(r"(\d+)")


def parse_season_episode_from_filename(name: str) -> tuple[int | None, int | None]:
    """Versucht Staffel UND Episode direkt aus einem Dateinamen zu lesen
    (z.B. fuer Dateien, die direkt im Serienordner liegen, ohne eigenen
    Staffelordner). Gibt (None, None) zurueck, wenn kein eindeutiges Muster
    gefunden wurde."""
    m = _SXXEYY_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = _NXM_RE.search(name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None


def parse_season_number_from_folder(folder_name: str) -> int | None:
    """Erkennt eine Staffelnummer aus einem Ordnernamen. Gibt None zurueck,
    wenn der Ordner nicht wie ein Staffelordner aussieht (z.B. "Extras",
    "Behind the Scenes") -- solche Ordner werden vom Scanner bewusst
    uebersprungen statt geraten."""
    name = folder_name.strip()
    m = _SEASON_KEYWORD_RE.search(name)
    if m:
        return int(m.group(1))
    m = _SEASON_SHORT_RE.match(name)
    if m:
        return int(m.group(1))
    return None


def parse_episode_number_from_filename(name: str) -> int | None:
    """Erkennt eine Episodennummer aus einem Dateinamen, wenn die Staffel
    bereits aus dem umgebenden Ordner bekannt ist. Probiert der Reihe nach:
    SxxEyy/NxM (nur die Episode-Gruppe daraus), 'Episode/Folge/Ep NN', eine
    fuehrende Nummer im Dateinamen, und als letzten Versuch irgendeine
    Nummer im Dateinamen (deckt z.B. "Dragon Ball 047 - Titel.mkv" ab, wo
    die Nummer nicht ganz am Anfang steht). Wichtig fuer Serien mit sehr
    vielen, uneinheitlich benannten Episoden (z.B. Animes mit 200+ Folgen
    direkt in einem Ordner ohne Staffelstruktur): eine tatsaechlich aus dem
    Dateinamen gelesene Nummer bleibt bei kuenftigen Scans stabil, waehrend
    eine rein alphabetisch vergebene Ersatznummer sich verschieben koennte,
    sobald eine Datei dazwischen hinzukommt/verschwindet -- und damit den
    'gesehen'-Status der falschen Episode zuordnen wuerde."""
    stem = Path(name).stem
    m = _SXXEYY_RE.search(stem)
    if m:
        return int(m.group(2))
    m = _NXM_RE.search(stem)
    if m:
        return int(m.group(2))
    m = _EPISODE_KEYWORD_RE.search(stem)
    if m:
        return int(m.group(1))
    m = _LEADING_NUMBER_RE.match(stem)
    if m:
        return int(m.group(1))
    m = _ANY_NUMBER_RE.search(stem)
    if m:
        return int(m.group(1))
    return None


def _natural_sort_key(name: str) -> list:
    """Zerlegt einen Dateinamen in Text-/Zahl-Abschnitte, damit '2' vor '10'
    einsortiert wird statt (rein alphabetisch) danach -- wichtig als
    Ersatz-Sortierung fuer Episoden ganz ohne per Regex erkennbare Nummer."""
    parts = _NATURAL_SPLIT_RE.split(name.lower())
    return [int(p) if p.isdigit() else p for p in parts]


def resolve_episode_numbers(items: list[tuple[str, Path]]) -> dict[Path, int]:
    """Ordnet jedem Element in 'items' -- (Name-zum-Erkennen, tatsaechliche
    Videodatei) -- eine Episodennummer zu. Der 'Name zum Erkennen' ist meist
    einfach der Dateiname, kann aber bei Serien mit einem Ordner PRO Episode
    (typisch bei Szene-Releases) auch der aussagekraeftigere Ordnername sein
    (siehe series_scanner.py). Elemente mit erkennbarer Nummer behalten
    diese; der Rest wird natuerlich sortiert (2 vor 10, nicht alphabetisch
    10 vor 2) und erhaelt der Reihe nach die naechste noch freie Nummer
    (ab 1)."""
    resolved: dict[Path, int] = {}
    unresolved: list[tuple[str, Path]] = []
    used_numbers: set[int] = set()

    for name, path in items:
        n = parse_episode_number_from_filename(name)
        if n is not None and n not in used_numbers:
            resolved[path] = n
            used_numbers.add(n)
        else:
            unresolved.append((name, path))

    unresolved.sort(key=lambda item: _natural_sort_key(item[0]))
    next_number = 1
    for _name, path in unresolved:
        while next_number in used_numbers:
            next_number += 1
        resolved[path] = next_number
        used_numbers.add(next_number)
        next_number += 1

    return resolved
