"""
Duenner Client fuer die TMDb-API (https://www.themoviedb.org/documentation/api).

Ein kostenloser API-Key kann hier erstellt werden:
https://www.themoviedb.org/settings/api

Dies ist die EINZIGE Stelle im Programm, die Internetzugriffe durchfuehrt.
"""
from __future__ import annotations

import requests

from .utils import normalize_for_match, title_similarity

TMDB_BASE = "https://api.themoviedb.org/3"
IMAGE_BASE = "https://image.tmdb.org/t/p"
POSTER_SIZE = "w500"
THUMB_SIZE = "w185"

# Ab hier gilt ein Treffer allein aufgrund der Titelaehnlichkeit als sicher
# genug (unabhaengig vom Jahr).
STRICT_TITLE_THRESHOLD = 0.84
# Wenn zusaetzlich das Erscheinungsjahr exakt uebereinstimmt, reicht eine
# schon eine moderate Titelaehnlichkeit (z.B. leicht abweichender Untertitel).
YEAR_MATCH_TITLE_THRESHOLD = 0.55


class TmdbError(Exception):
    pass


class TmdbClient:
    def __init__(self, api_key: str, language: str = "de-DE", timeout: float = 10.0):
        self.api_key = api_key
        self.language = language
        self.timeout = timeout
        self.session = requests.Session()

    def _get(self, path: str, params: dict) -> dict:
        params = dict(params)
        params["api_key"] = self.api_key
        params.setdefault("language", self.language)
        resp = self.session.get(f"{TMDB_BASE}{path}", params=params, timeout=self.timeout)
        if resp.status_code == 401:
            raise TmdbError("API-Key ungueltig oder fehlt.")
        resp.raise_for_status()
        return resp.json()

    # Wird nur eingesetzt, wenn KEIN Jahr aus dem Dateinamen bekannt ist:
    # zwei (oder mehr) fast identisch benannte Treffer mit unterschiedlichem
    # Erscheinungsjahr (typisch bei Remakes, z.B. "Ben-Hur" 1959 vs. 2016)
    # gelten dann als mehrdeutig, statt bevorzugt den populaersten/aeltesten
    # zu erraten.
    AMBIGUITY_SIMILARITY_GAP = 0.08
    MAX_AMBIGUOUS_CANDIDATES = 5

    def search_movie(self, query: str, year: int | None = None
                      ) -> tuple[dict | None, bool, list[dict]]:
        """Sucht einen Film. Liefert (Treffer_oder_None, mehrdeutig, Kandidaten).

        Ein Treffer wird NUR dann akzeptiert, wenn dessen Titel wirklich zum
        gesuchten Titel passt (siehe STRICT_TITLE_THRESHOLD /
        YEAR_MATCH_TITLE_THRESHOLD). Damit werden Ordner mit kurzen oder
        mehrdeutigen Titeln (z.B. 'Haus') nicht faelschlich mit einem ganz
        anderen, aehnlich klingenden Film verknuepft -- lieber kein Treffer
        als ein falscher.

        Wenn ohne Jahresangabe mehrere gleichnamige Filme (typischerweise
        Remakes) in Frage kommen, wird das als 'mehrdeutig' zurueckgemeldet
        und die betroffenen Kandidaten (TMDb-ID, Titel, Jahr) werden
        mitgeliefert -- der Aufrufer kann sie z.B. als Auswahl-Dropdown
        anzeigen, statt selbst einen davon zu erraten."""
        params = {"query": query, "include_adult": "false"}
        if year:
            params["year"] = year
        data = self._get("/search/movie", params)
        results = data.get("results") or []

        if not results and year:
            # Ohne Jahr nochmal versuchen (Jahr evtl. falsch geparst)
            data = self._get("/search/movie", {"query": query, "include_adult": "false"})
            results = data.get("results") or []

        if not results:
            return None, False, []

        norm_query = normalize_for_match(query)

        scored = []
        for r in results:
            title = r.get("title") or ""
            original_title = r.get("original_title") or ""
            sim = max(
                title_similarity(norm_query, normalize_for_match(title)),
                title_similarity(norm_query, normalize_for_match(original_title)),
            )
            release_date = r.get("release_date") or ""
            candidate_year = int(release_date[:4]) if release_date[:4].isdigit() else None
            year_match = year is not None and candidate_year == year
            rank = sim + (0.2 if year_match else 0.0)
            scored.append((rank, sim, year_match, candidate_year, r))

        scored.sort(key=lambda t: t[0], reverse=True)
        best_rank, best_sim, best_year_match, best_year, best_candidate = scored[0]

        accepted = (
            best_sim >= STRICT_TITLE_THRESHOLD
            or (best_year_match and best_sim >= YEAR_MATCH_TITLE_THRESHOLD)
        )
        if not accepted:
            return None, False, []

        # Mehrdeutigkeits-Check: nur relevant, wenn wir selbst kein Jahr zur
        # Verfuegung hatten (sonst haette year_match bereits disambiguiert).
        # Alle Treffer mit (fast) identischem Titel und ausreichender
        # Aehnlichkeit werden gesammelt (nicht nur die Top-2), damit auch
        # seltene Faelle mit 3+ Versionen vollstaendig erfasst werden.
        if year is None:
            best_norm_title = normalize_for_match(best_candidate.get("title") or "")
            min_sim = STRICT_TITLE_THRESHOLD - self.AMBIGUITY_SIMILARITY_GAP
            same_title_candidates = [
                (cand_year, cand) for (_, sim, _, cand_year, cand) in scored
                if sim >= min_sim and normalize_for_match(cand.get("title") or "") == best_norm_title
            ]
            distinct_years = {cy for cy, _ in same_title_candidates if cy}
            if len(same_title_candidates) > 1 and len(distinct_years) > 1:
                # Nach Jahr deduplizieren (TMDb liefert manchmal doppelte
                # Eintraege), neueste zuerst.
                seen_years = set()
                deduped = []
                for cand_year, cand in sorted(same_title_candidates, key=lambda t: t[0] or 0, reverse=True):
                    if cand_year in seen_years:
                        continue
                    seen_years.add(cand_year)
                    deduped.append(cand)
                candidates = [
                    {
                        "id": c.get("id"),
                        "title": c.get("title"),
                        "year": int((c.get("release_date") or "")[:4]) if (c.get("release_date") or "")[:4].isdigit() else None,
                        "poster_path": c.get("poster_path"),
                        "overview": c.get("overview") or None,
                        "overview_language": "de" if c.get("overview") else None,
                    }
                    for c in deduped[: self.MAX_AMBIGUOUS_CANDIDATES]
                ]
                # TMDb liefert die Beschreibung oft nicht in jeder Sprache
                # (v.a. bei aelteren/weniger populaeren Filmen). Fuer
                # Kandidaten ohne deutsche Beschreibung wird gezielt
                # nachgefragt, damit im Auswahl-Dropdown trotzdem etwas zu
                # lesen ist (mit Hinweis, dass es die englische ist).
                for cand in candidates:
                    if cand["overview"] or cand["id"] is None:
                        continue
                    try:
                        details = self._get(f"/movie/{cand['id']}", {"language": "en-US"})
                    except Exception:
                        continue
                    en_overview = details.get("overview")
                    if en_overview:
                        cand["overview"] = en_overview
                        cand["overview_language"] = "en"
                return None, True, candidates

        return best_candidate, False, []

    def get_extra_details(self, tmdb_id: int, max_cast: int = 6
                           ) -> tuple[str | None, str | None, str | None, str | None]:
        """Liefert (Besetzung, Genres -- beide kommagetrennt, YouTube-Trailer-URL,
        Sprachkuerzel des Trailers 'de'/'en'/None). Bevorzugt einen deutschen
        Trailer; nur falls TMDb dazu keinen hat, wird ein englischer als
        Fallback verwendet (deutlich hoehere Verfuegbarkeit)."""
        cast_names: str | None = None
        genre_names: str | None = None

        try:
            data = self._get(f"/movie/{tmdb_id}", {"append_to_response": "credits"})
        except Exception:
            return None, None, None, None

        cast_list = (data.get("credits") or {}).get("cast") or []
        names = [c.get("name") for c in cast_list[:max_cast] if c.get("name")]
        if names:
            cast_names = ", ".join(names)

        genre_list = data.get("genres") or []
        genres = [g.get("name") for g in genre_list if g.get("name")]
        if genres:
            genre_names = ", ".join(genres)

        # Mehrere Sprachvarianten der Reihe nach probieren, bis ein
        # YouTube-Trailer gefunden wird. "de-DE" und "de" liefern bei TMDb
        # nicht immer identische Treffer, daher beide versuchen.
        trailer_url = None
        trailer_lang = None
        for lang_param, lang_label in (("de-DE", "de"), ("de", "de"), ("en-US", "en")):
            try:
                vdata = self._get(f"/movie/{tmdb_id}/videos", {"language": lang_param})
            except Exception:
                continue
            videos = vdata.get("results") or []
            found = self._pick_trailer_url(videos)
            if found:
                trailer_url = found
                trailer_lang = lang_label
                break

        return cast_names, genre_names, trailer_url, trailer_lang

    @staticmethod
    def _pick_trailer_url(videos: list[dict]) -> str | None:
        youtube_videos = [v for v in videos if v.get("site") == "YouTube" and v.get("key")]
        if not youtube_videos:
            return None

        def score(v: dict) -> tuple:
            return (
                v.get("type") == "Trailer",
                v.get("official", False),
                v.get("type") in ("Trailer", "Teaser"),
            )

        best = max(youtube_videos, key=score)
        return f"https://www.youtube.com/watch?v={best['key']}"

    def fetch_poster_bytes(self, poster_path: str, size: str = POSTER_SIZE) -> bytes:
        url = f"{IMAGE_BASE}/{size}{poster_path}"
        resp = self.session.get(url, timeout=self.timeout)
        resp.raise_for_status()
        return resp.content

    def get_movie_by_id(self, tmdb_id: int) -> dict:
        """Laedt einen Film direkt anhand seiner TMDb-ID -- OHNE Titelsuche
        und OHNE Aehnlichkeitspruefung. Fuer die manuelle Zuweisung, wenn der
        Nutzer den korrekten TMDb-Link selbst angibt (z.B. weil die
        automatische Suche wegen abweichender Schreibweise nichts fand)."""
        return self._get(f"/movie/{tmdb_id}", {})

    # ================================================================
    # Serien (komplett eigener Bereich, siehe database.py/config.py) --
    # bewusst als eigene, parallele Methoden statt mit den Film-Methoden
    # oben zusammengelegt, damit beide Bereiche fuer sich lesbar bleiben.
    # TMDb nennt bei Serien Titel/Erscheinungsdatum anders als bei Filmen
    # ('name'/'original_name' statt 'title', 'first_air_date' statt
    # 'release_date') -- das ist der einzige inhaltliche Unterschied.
    # ================================================================

    def search_tv(self, query: str, year: int | None = None
                   ) -> tuple[dict | None, bool, list[dict]]:
        """Analog zu search_movie, aber fuer Serien (/search/tv)."""
        params = {"query": query, "include_adult": "false"}
        if year:
            params["first_air_date_year"] = year
        data = self._get("/search/tv", params)
        results = data.get("results") or []

        if not results and year:
            data = self._get("/search/tv", {"query": query, "include_adult": "false"})
            results = data.get("results") or []

        if not results:
            return None, False, []

        norm_query = normalize_for_match(query)

        scored = []
        for r in results:
            name = r.get("name") or ""
            original_name = r.get("original_name") or ""
            sim = max(
                title_similarity(norm_query, normalize_for_match(name)),
                title_similarity(norm_query, normalize_for_match(original_name)),
            )
            first_air_date = r.get("first_air_date") or ""
            candidate_year = int(first_air_date[:4]) if first_air_date[:4].isdigit() else None
            year_match = year is not None and candidate_year == year
            rank = sim + (0.2 if year_match else 0.0)
            scored.append((rank, sim, year_match, candidate_year, r))

        scored.sort(key=lambda t: t[0], reverse=True)
        best_rank, best_sim, best_year_match, best_year, best_candidate = scored[0]

        accepted = (
            best_sim >= STRICT_TITLE_THRESHOLD
            or (best_year_match and best_sim >= YEAR_MATCH_TITLE_THRESHOLD)
        )
        if not accepted:
            return None, False, []

        if year is None:
            best_norm_name = normalize_for_match(best_candidate.get("name") or "")
            min_sim = STRICT_TITLE_THRESHOLD - self.AMBIGUITY_SIMILARITY_GAP
            same_name_candidates = [
                (cand_year, cand) for (_, sim, _, cand_year, cand) in scored
                if sim >= min_sim and normalize_for_match(cand.get("name") or "") == best_norm_name
            ]
            distinct_years = {cy for cy, _ in same_name_candidates if cy}
            if len(same_name_candidates) > 1 and len(distinct_years) > 1:
                seen_years = set()
                deduped = []
                for cand_year, cand in sorted(same_name_candidates, key=lambda t: t[0] or 0, reverse=True):
                    if cand_year in seen_years:
                        continue
                    seen_years.add(cand_year)
                    deduped.append(cand)
                candidates = [
                    {
                        "id": c.get("id"),
                        "title": c.get("name"),
                        "year": int((c.get("first_air_date") or "")[:4]) if (c.get("first_air_date") or "")[:4].isdigit() else None,
                        "poster_path": c.get("poster_path"),
                        "overview": c.get("overview") or None,
                        "overview_language": "de" if c.get("overview") else None,
                    }
                    for c in deduped[: self.MAX_AMBIGUOUS_CANDIDATES]
                ]
                for cand in candidates:
                    if cand["overview"] or cand["id"] is None:
                        continue
                    try:
                        details = self._get(f"/tv/{cand['id']}", {"language": "en-US"})
                    except Exception:
                        continue
                    en_overview = details.get("overview")
                    if en_overview:
                        cand["overview"] = en_overview
                        cand["overview_language"] = "en"
                return None, True, candidates

        return best_candidate, False, []

    def get_tv_extra_details(self, tmdb_id: int, max_cast: int = 6
                              ) -> tuple[str | None, str | None, str | None, str | None]:
        """Analog zu get_extra_details, aber fuer Serien."""
        cast_names: str | None = None
        genre_names: str | None = None

        try:
            data = self._get(f"/tv/{tmdb_id}", {"append_to_response": "credits"})
        except Exception:
            return None, None, None, None

        cast_list = (data.get("credits") or {}).get("cast") or []
        names = [c.get("name") for c in cast_list[:max_cast] if c.get("name")]
        if names:
            cast_names = ", ".join(names)

        genre_list = data.get("genres") or []
        genres = [g.get("name") for g in genre_list if g.get("name")]
        if genres:
            genre_names = ", ".join(genres)

        trailer_url = None
        trailer_lang = None
        for lang_param, lang_label in (("de-DE", "de"), ("de", "de"), ("en-US", "en")):
            try:
                vdata = self._get(f"/tv/{tmdb_id}/videos", {"language": lang_param})
            except Exception:
                continue
            videos = vdata.get("results") or []
            found = self._pick_trailer_url(videos)
            if found:
                trailer_url = found
                trailer_lang = lang_label
                break

        return cast_names, genre_names, trailer_url, trailer_lang

    def get_tv_by_id(self, tmdb_id: int) -> dict:
        """Laedt eine Serie direkt anhand ihrer TMDb-ID -- fuer die manuelle
        Zuweisung, analog zu get_movie_by_id."""
        return self._get(f"/tv/{tmdb_id}", {})

    def get_episode_details(self, tv_id: int, season_number: int,
                             episode_number: int) -> dict | None:
        """Liefert Titel+Beschreibung EINER Episode. None bei Fehler (z.B.
        die Episode existiert auf TMDb unter dieser Staffel/Nummer nicht --
        kommt bei Spezial-/Bonusfolgen ohne offizielle Nummerierung vor).
        Ein fehlender Treffer ist damit kein Programmfehler: die Episode
        bleibt ganz normal vorhanden und abspielbar, nur eben ohne
        Beschreibung."""
        try:
            return self._get(f"/tv/{tv_id}/season/{season_number}/episode/{episode_number}", {})
        except Exception:
            return None


def download_image_from_url(url: str, timeout: float = 15.0) -> bytes:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    return resp.content
