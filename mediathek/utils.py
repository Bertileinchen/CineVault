from __future__ import annotations

import difflib
import re
import unicodedata

_YEAR_RE = re.compile(r"(?:\(|\[|\.|\s|_)(19\d{2}|20\d{2})(?:\)|\]|\.|\s|_|$)")
_CLEAN_RE = re.compile(r"[\.\_]+")
_TAG_RE = re.compile(
    r"\b(1080p|720p|2160p|4k|uhd|bluray|blu-ray|bdrip|brrip|webrip|web-dl|webdl|"
    r"hdtv|dvdrip|x264|x265|hevc|h264|h265|aac|ac3|dts|multi|german|deutsch|"
    r"dl|extended|remastered|repack|proper|complete|limited)\b",
    re.IGNORECASE,
)
_LEADING_ARTICLE_RE = re.compile(r"^(der|die|das|the|a|an|le|la|les|el|los|las)\s+", re.IGNORECASE)


def parse_title_year(folder_name: str) -> tuple[str, int | None]:
    """Extrahiert einen moeglichst sauberen Suchtitel + Jahr aus einem Ordnernamen.

    Beispiele:
      'Der.Herr.der.Ringe.2001.German.1080p.BluRay' -> ('Der Herr der Ringe', 2001)
      'Inception (2010)'                             -> ('Inception', 2010)
      'Dune Part Two'                                -> ('Dune Part Two', None)
    """
    name = folder_name.strip()

    year = None
    m = _YEAR_RE.search(name)
    if m:
        year = int(m.group(1))
        # Nur die Jahreszahl selbst entfernen (nicht die komplette
        # Match-Spanne inkl. der umschliessenden Trennzeichen) -- sonst
        # rutschen die Woerter davor/danach ungewollt zusammen, z.B. wurde
        # aus "Ringe.2001.German" faelschlich "RingeGerman" statt
        # "Ringe German".
        year_start, year_end = m.span(1)
        name = name[:year_start] + " " + name[year_end:]

    name = name.replace("(", " ").replace(")", " ").replace("[", " ").replace("]", " ")
    name = _CLEAN_RE.sub(" ", name)
    name = _TAG_RE.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" -._")

    if not name:
        name = folder_name

    return name, year


def slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_")
    return text.lower() or "cover"


def normalize_for_match(text: str) -> str:
    """Reduziert einen Titel auf reinen Kleinbuchstaben-Kern zum Vergleichen:
    Akzente entfernt, Satzzeichen weg, fuehrender Artikel entfernt,
    Mehrfach-Leerzeichen zusammengefasst. So werden z.B. 'Ä'/'ae', Doppelpunkte
    oder 'Der Herr...' vs 'Herr...' nicht faelschlich als unterschiedlich
    gewertet."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = _LEADING_ARTICLE_RE.sub("", text)
    return text


def title_similarity(a: str, b: str) -> float:
    """Aehnlichkeit zweier (bereits normalisierter) Titel, 0.0 bis 1.0."""
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


_TMDB_URL_RE = re.compile(r"themoviedb\.org/(?:movie|tv)/(\d+)")
_LEADING_DIGITS_RE = re.compile(r"^(\d+)")


def parse_tmdb_id(text: str) -> int | None:
    """Extrahiert eine TMDb-ID aus einer Nutzereingabe -- fuer Filme UND
    Serien (die TMDb-Linkstruktur unterscheidet sich nur im Pfad-Segment
    '/movie/' vs. '/tv/', die ID selbst wird identisch extrahiert). Akzeptiert:
    - einen kompletten TMDb-Link, z.B.
      'https://www.themoviedb.org/movie/603-the-matrix' oder
      'https://www.themoviedb.org/tv/456-the-simpsons'
    - eine reine ID ('603')
    - eine ID mit angehaengtem Titel-Slug ('603-the-matrix')
    Gibt None zurueck, wenn nichts Sinnvolles erkannt werden konnte."""
    text = text.strip()
    if not text:
        return None
    m = _TMDB_URL_RE.search(text)
    if m:
        return int(m.group(1))
    if text.isdigit():
        return int(text)
    m2 = _LEADING_DIGITS_RE.match(text)
    if m2:
        return int(m2.group(1))
    return None
