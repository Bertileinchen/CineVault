"""
TMDb-Sync-Logik fuer Serien + Episoden -- bewusst OHNE jede Qt-Abhaengigkeit
(anders als bei Filmen, wo diese Funktionen direkt in mediathek/ui/
sync_worker.py neben den QThread-Klassen liegen). So bleibt die eigentliche
Sync-Logik fuer sich testbar, und mediathek/ui/series_sync_worker.py
enthaelt nur noch die duennen QThread-Wrapper drumherum (gleiches Prinzip
wie schon bei backup.py / BackupWorker).

Analog zu Filmen, aber fuer Serien: sobald eine Serie eindeutig zugeordnet
ist, wird zusaetzlich fuer JEDE ihrer bereits gescannten Episoden Titel +
Beschreibung von TMDb nachgeladen (auf Bert's Wunsch: volle Beschreibung
pro Folge, der grosse Sync-Durchlauf passiert ja ohnehin nur einmal).
"""
from __future__ import annotations

import json

from .config import Library, SeriesLibrary
from .database import Database, Series
from .metadata_client import TmdbClient, TmdbError
from .utils import parse_title_year, slugify

try:
    from PIL import Image
    _HAVE_PIL = True
except Exception:
    _HAVE_PIL = False


def save_series_poster(series_library: SeriesLibrary, series: Series, poster_bytes: bytes) -> str:
    """Analog zu _save_poster bei Filmen, nur eben in den Serien-eigenen
    Cover-Unterordner (siehe SeriesLibrary in config.py)."""
    filename = f"{slugify(series.folder_name)}_{series.id}.jpg"
    cover_path = series_library.dir_covers / filename
    thumb_path = series_library.dir_thumbs / filename

    cover_path.write_bytes(poster_bytes)
    if _HAVE_PIL:
        try:
            with Image.open(cover_path) as img:
                img = img.convert("RGB")
                img.thumbnail((240, 360))
                img.save(thumb_path, "JPEG", quality=85)
        except Exception:
            thumb_path.write_bytes(poster_bytes)
    else:
        thumb_path.write_bytes(poster_bytes)
    return filename


def sync_series_episodes(db: Database, client: TmdbClient, series: Series) -> tuple[int, int]:
    """Laedt fuer alle noch nicht synchronisierten Episoden einer bereits
    zugeordneten Serie (series.tmdb_id bekannt) Titel+Beschreibung von TMDb
    nach. Gibt (erfolgreich, insgesamt versucht) zurueck.

    Episoden, die TMDb unter dieser Staffel/Nummer nicht kennt (z.B.
    Spezial-/Bonusfolgen ohne offizielle Nummerierung), werden als
    'not_found' markiert -- bleiben aber ganz normal vorhanden und
    abspielbar, nur eben ohne Beschreibung (siehe Bert: 'wenns Infos gibt
    ok, sonst auch gut')."""
    if not series.tmdb_id:
        return 0, 0
    episodes = [e for e in db.list_episodes_for_series(series.id)
                if e.missing == 0 and e.sync_status in ("pending", "error", "not_found")]
    ok_count = 0
    for ep in episodes:
        details = client.get_episode_details(series.tmdb_id, ep.season_number, ep.episode_number)
        if details is None:
            db.set_episode_metadata_not_found(ep.id)
            continue
        title = details.get("name")
        overview = details.get("overview")
        db.set_episode_metadata_ok(ep.id, title, overview)
        ok_count += 1
    return ok_count, len(episodes)


def sync_single_series(library: Library, series_library: SeriesLibrary, db: Database,
                        client: TmdbClient, series: Series) -> Series:
    """Verarbeitet genau eine Serie (wird vom ThreadPool parallel
    aufgerufen): erst die Serien-Metadaten selbst, bei Erfolg danach alle
    ihre Episoden."""
    query, year = parse_title_year(series.folder_name)
    try:
        result, ambiguous, candidates = client.search_tv(query, year)
        if ambiguous:
            note = (
                "Mehrere gleichnamige Serien gefunden, kein Jahr im Ordnernamen "
                "erkennbar -- bitte unten die richtige auswählen."
            )
            db.set_series_metadata_ambiguous(series.id, note, json.dumps(candidates, ensure_ascii=False))
            return db.get_series(series.id)
        if not result:
            db.set_series_metadata_not_found(series.id)
            return db.get_series(series.id)

        title = result.get("name") or query
        original_title = result.get("original_name")
        first_air_date = result.get("first_air_date") or ""
        found_year = int(first_air_date[:4]) if first_air_date[:4].isdigit() else year
        overview = result.get("overview") or ""
        poster_path_remote = result.get("poster_path")
        tmdb_id = result.get("id")

        local_poster_name = None
        if poster_path_remote:
            poster_bytes = client.fetch_poster_bytes(poster_path_remote)
            local_poster_name = save_series_poster(series_library, series, poster_bytes)

        cast_names, genre_names, trailer_url, trailer_language = (
            client.get_tv_extra_details(tmdb_id) if tmdb_id else (None, None, None, None)
        )

        db.set_series_metadata_ok(series.id, tmdb_id, title, original_title, found_year,
                                   overview, local_poster_name, cast_names, trailer_url,
                                   trailer_language, genre_names)

        updated = db.get_series(series.id)
        if updated.tmdb_id:
            sync_series_episodes(db, client, updated)
    except TmdbError as e:
        db.set_series_metadata_error(series.id, str(e))
    except Exception as e:  # Netzwerkfehler, Timeouts etc.
        db.set_series_metadata_error(series.id, str(e))

    return db.get_series(series.id)


def assign_tv_id(library: Library, series_library: SeriesLibrary, db: Database,
                  series: Series, tmdb_id: int) -> Series:
    """Weist einer Serie DIREKT eine bestimmte TMDb-TV-ID zu -- OHNE
    Titelsuche/Aehnlichkeitspruefung, analog zu assign_tmdb_id() bei
    Filmen. Synchronisiert danach ebenfalls gleich alle Episoden."""
    client = TmdbClient(library.config.tmdb_api_key, library.config.tmdb_language)

    data = client.get_tv_by_id(tmdb_id)
    title = data.get("name") or series.folder_name
    original_title = data.get("original_name")
    first_air_date = data.get("first_air_date") or ""
    year = int(first_air_date[:4]) if first_air_date[:4].isdigit() else None
    overview = data.get("overview") or ""
    poster_path_remote = data.get("poster_path")

    local_poster_name = None
    if poster_path_remote:
        poster_bytes = client.fetch_poster_bytes(poster_path_remote)
        local_poster_name = save_series_poster(series_library, series, poster_bytes)

    cast_names, genre_names, trailer_url, trailer_language = client.get_tv_extra_details(tmdb_id)

    db.set_series_metadata_ok(series.id, tmdb_id, title, original_title, year, overview,
                               local_poster_name, cast_names, trailer_url, trailer_language, genre_names)

    updated = db.get_series(series.id)
    sync_series_episodes(db, client, updated)
    return db.get_series(series.id)
