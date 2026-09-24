"""
Optionaler Streaming-Server fuers Heim-WLAN -- zeigt Filme UND Serien
mobil-freundlich an und erlaubt, sie per Klick direkt in VLC (Android)
abzuspielen.

Bewusst FAST komplett lesend: Loeschen, Bearbeiten oder Synchronisieren ist
ueber das Netzwerk nicht moeglich. EINZIGE Ausnahme: Episoden koennen als
gesehen/ungesehen markiert werden (siehe /series/toggle_episode/<id>) --
dieselbe Funktion wie das Abhaken im Detail-Fenster, nur eben von unterwegs
aus nutzbar. Kein Loesch-/Bearbeitungsrisiko dadurch, aber ehrlich gesagt:
kein "rein lesend" mehr im strengen Sinne.

Technische Eckpunkte:
- Reine Python-Standardbibliothek (http.server), keine neue Abhaengigkeit.
- HTTP-Range-Requests werden manuell unterstuetzt (der eingebaute
  http.server kann das nicht von Haus aus) -- noetig, damit VLC im Video
  vor-/zurueckspulen kann.
- Zugriff auf die Datenbank ist unkritisch bzgl. Threads: die Database-
  Klasse sichert alle Zugriffe bereits selbst per Lock ab.
- Es wird niemals ein Dateipfad direkt aus der URL uebernommen -- immer nur
  eine Film-/Serien-/Episoden-ID, zu der der tatsaechliche Pfad aus der
  Datenbank nachgeschlagen wird. Directory-Traversal ist damit ausgeschlossen.
"""
from __future__ import annotations

import html
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

from .config import Library, SeriesLibrary, app_assets_dir
from .database import Database, Episode, Movie, Series
from .series_player import toggle_episode_seen
from .series_scanner import episode_video_path



MIME_TYPES = {
    ".mp4": "video/mp4",
    ".mkv": "video/x-matroska",
    ".avi": "video/x-msvideo",
    ".mov": "video/quicktime",
    ".m4v": "video/x-m4v",
    ".wmv": "video/x-ms-wmv",
    ".ts": "video/mp2t",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")
_CHUNK_SIZE = 256 * 1024


def get_local_ip() -> str:
    """Ermittelt die eigene LAN-IP (z.B. 192.168.x.x) -- der klassische
    Trick darueber, eine UDP-'Verbindung' zu oeffnen ohne wirklich Daten zu
    senden. Funktioniert zuverlaessiger als socket.gethostbyname(), das auf
    manchen Windows-Rechnern eine falsche/nicht erreichbare Adresse liefert."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        s.close()


def _mime_for(path: Path) -> str:
    return MIME_TYPES.get(path.suffix.lower(), "application/octet-stream")


def _page_shell(title: str, body: str, active_nav: str | None = None) -> bytes:
    nav = ""
    if active_nav:
        movies_active = " active" if active_nav == "movies" else ""
        series_active = " active" if active_nav == "series" else ""
        nav = (
            '<div class="nav">'
            f'<a class="navlink{movies_active}" href="/">🎬 Filme</a>'
            f'<a class="navlink{series_active}" href="/series">📺 Serien</a>'
            '</div>'
        )
    html_doc = f"""<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#14161c">
<link rel="icon" href="/icon.png">
<link rel="apple-touch-icon" href="/icon.png">
<link rel="manifest" href="/manifest.json">
<title>{html.escape(title)}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{
    background: #14161c; color: #e8e8ec; margin: 0; padding: 16px;
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
  }}
  h1 {{ font-size: 20px; margin: 0 0 16px 0; }}
  a {{ color: inherit; }}
  .nav {{ display: flex; gap: 8px; margin-bottom: 16px; }}
  .navlink {{
    padding: 8px 16px; border-radius: 8px; text-decoration: none;
    color: #9aa0ac; font-weight: 600; font-size: 14px;
  }}
  .navlink.active {{ background: #21242e; color: #e8e8ec; }}
  .grid {{
    display: grid; grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
    gap: 14px;
  }}
  .card {{ text-decoration: none; color: inherit; display: block; position: relative; }}
  .card img {{
    width: 100%; aspect-ratio: 2 / 3; object-fit: cover; border-radius: 10px;
    background: #21242e; display: block;
  }}
  .card .title {{
    font-size: 13px; margin-top: 6px; text-align: center; line-height: 1.3;
  }}
  .card .badge {{
    position: absolute; top: 6px; right: 6px; background: #4f7cff; color: #fff;
    font-size: 10px; font-weight: 700; padding: 3px 8px; border-radius: 999px;
  }}
  .card .badge.laufend {{ background: #e0a83e; }}
  .toolbar {{ margin-bottom: 16px; }}
  .search-row {{
    display: flex; gap: 8px; margin-bottom: 8px;
  }}
  .search-row input[type="text"] {{
    flex: 1; background: #21242e; border: 1px solid #2f3340; border-radius: 8px;
    color: #e8e8ec; padding: 10px 12px; font-size: 15px;
  }}
  .search-row button {{
    background: #4f7cff; color: #fff; border: none; border-radius: 8px;
    padding: 0 16px; font-size: 16px;
  }}
  .select-row {{
    display: flex; gap: 8px; margin-bottom: 10px;
  }}
  .select-row select {{
    flex: 1; min-width: 0; background: #21242e; border: 1px solid #2f3340;
    border-radius: 8px; color: #e8e8ec; padding: 8px; font-size: 13px;
  }}
  .filters {{ display: flex; gap: 8px; flex-wrap: wrap; }}
  .pill {{
    display: inline-block; padding: 8px 14px; border-radius: 999px;
    background: #21242e; border: 1px solid #2f3340; text-decoration: none;
    color: #e8e8ec; font-size: 13px;
  }}
  .pill.active {{ background: #4f7cff; border-color: #4f7cff; color: #fff; }}
  .count {{ color: #7d8595; font-size: 12px; margin: 10px 0 16px 0; }}
  .backlink {{ display: inline-block; margin-bottom: 16px; color: #4f7cff; text-decoration: none; }}
  .detail-cover {{
    width: 100%; max-width: 260px; border-radius: 12px; background: #21242e;
    display: block; margin: 0 auto 16px auto;
  }}
  .detail-title {{ font-size: 22px; font-weight: 700; margin-bottom: 4px; }}
  .detail-meta {{ color: #9aa0ac; font-size: 13px; margin-bottom: 12px; }}
  .detail-overview {{ color: #d7d9e0; font-size: 14px; line-height: 1.5; margin-bottom: 20px; }}
  .btn {{
    display: block; text-align: center; padding: 14px; border-radius: 10px;
    text-decoration: none; font-weight: 600; margin-bottom: 10px;
  }}
  .btn-primary {{ background: #4f7cff; color: #fff; }}
  .btn-secondary {{ background: #21242e; color: #e8e8ec; border: 1px solid #2f3340; }}
  .empty {{ color: #7d8595; }}
  .season-header {{
    color: #e8e8ec; font-size: 15px; font-weight: 700; margin: 18px 0 6px 0;
  }}
  .episode-row {{
    display: flex; align-items: center; gap: 10px; padding: 8px 0;
    border-bottom: 1px solid #21242e;
  }}
  .episode-row .ep-toggle {{
    font-size: 20px; text-decoration: none; flex-shrink: 0; width: 26px; text-align: center;
  }}
  .episode-row .ep-title {{ flex: 1; font-size: 14px; color: #d7d9e0; }}
  .episode-row .ep-play {{
    background: #4f7cff; color: #fff; text-decoration: none; border-radius: 50%;
    width: 30px; height: 30px; display: flex; align-items: center; justify-content: center;
    flex-shrink: 0; font-size: 12px;
  }}
</style>
</head>
<body>
{nav}
{body}
</body>
</html>"""
    return html_doc.encode("utf-8")


FILTER_LABELS = [
    ("all", "Alle"),
    ("unseen", "Ungesehen"),
    ("seen", "Gesehen"),
    ("rewatch", "Rewatch"),
]

SORT_LABELS = [
    ("title", "Titel (A–Z)"),
    ("added", "Älteste zuerst"),
    ("year", "Jahr (neueste zuerst)"),
]


def _collect_genres(movies: list[Movie]) -> list[str]:
    genres: set[str] = set()
    for m in movies:
        if m.genre_names:
            for g in m.genre_names.split(","):
                g = g.strip()
                if g:
                    genres.add(g)
    return sorted(genres, key=str.lower)


def _filter_movies(movies: list[Movie], q: str, filter_mode: str, genre: str) -> list[Movie]:
    q = q.strip().lower()
    genre_lower = genre.strip().lower()
    result = []
    for m in movies:
        if filter_mode == "unseen" and m.location != "NEU":
            continue
        if filter_mode == "seen" and m.location != "ARCHIV":
            continue
        if filter_mode == "rewatch" and not m.rewatch:
            continue
        if genre_lower:
            movie_genres = [g.strip().lower() for g in (m.genre_names or "").split(",") if g.strip()]
            if genre_lower not in movie_genres:
                continue
        if q and q not in m.folder_name.lower():
            continue
        result.append(m)
    return result


def _sort_movies(movies: list[Movie], sort_mode: str) -> list[Movie]:
    if sort_mode == "added":
        return sorted(movies, key=lambda m: m.folder_ctime or 0)
    if sort_mode == "year":
        # Filme ohne bekanntes Jahr rutschen unabhaengig von der Richtung
        # ans Ende (0 als Ersatzwert, kleiner als jedes echte Jahr);
        # bei gleichem Jahr alphabetisch als Tie-Breaker.
        return sorted(movies, key=lambda m: (-(m.year or 0), (m.folder_name or "").lower()))
    return sorted(movies, key=lambda m: (m.folder_name or "").lower())


def _render_overview_page(all_movies: list[Movie], q: str, filter_mode: str,
                           sort_mode: str, genre: str) -> bytes:
    movies = _sort_movies(_filter_movies(all_movies, q, filter_mode, genre), sort_mode)
    q_encoded = quote(q)
    genre_encoded = quote(genre)
    all_genres = _collect_genres(all_movies)

    filter_pills = []
    for mode, label in FILTER_LABELS:
        active = " active" if mode == filter_mode else ""
        filter_pills.append(
            f'<a class="pill{active}" href="/?filter={mode}&q={q_encoded}'
            f'&sort={sort_mode}&genre={genre_encoded}">{label}</a>'
        )

    sort_options = "".join(
        f'<option value="{mode}"{" selected" if mode == sort_mode else ""}>{label}</option>'
        for mode, label in SORT_LABELS
    )
    genre_options = '<option value="">Alle Genres</option>' + "".join(
        f'<option value="{html.escape(g)}"{" selected" if g == genre else ""}>{html.escape(g)}</option>'
        for g in all_genres
    )

    toolbar = f"""
<div class="toolbar">
  <form method="get" action="/">
    <input type="hidden" name="filter" value="{html.escape(filter_mode)}">
    <div class="search-row">
      <input type="text" name="q" value="{html.escape(q)}" placeholder="Filme durchsuchen …">
      <button type="submit">🔍</button>
    </div>
    <div class="select-row">
      <select name="sort" onchange="this.form.submit()">{sort_options}</select>
      <select name="genre" onchange="this.form.submit()">{genre_options}</select>
    </div>
  </form>
  <div class="filters">{"".join(filter_pills)}</div>
</div>
<div class="count">{len(movies)} Film{"e" if len(movies) != 1 else ""}</div>
"""

    if not movies:
        body = "<h1>🎬 CineVault Mobile</h1>" + toolbar + "<p class='empty'>Keine Filme gefunden.</p>"
        return _page_shell("CineVault Mobile", body, active_nav="movies")

    cards = []
    for m in movies:
        cover_url = f"/cover/{m.id}" if m.poster_path else ""
        img_tag = f'<img src="{cover_url}" alt="">' if cover_url else '<img alt="">'
        cards.append(
            f'<a class="card" href="/watch/{m.id}?filter={filter_mode}&q={q_encoded}'
            f'&sort={sort_mode}&genre={genre_encoded}">{img_tag}'
            f'<div class="title">{html.escape(m.folder_name)}</div></a>'
        )
    body = "<h1>🎬 CineVault Mobile</h1>" + toolbar + '<div class="grid">' + "".join(cards) + "</div>"
    return _page_shell("CineVault Mobile", body, active_nav="movies")


def _render_watch_page(movie: Movie, host: str, back_url: str, is_android: bool) -> bytes:
    cover_url = f"/cover/{movie.id}" if movie.poster_path else ""
    cover_tag = f'<img class="detail-cover" src="{cover_url}" alt="">' if cover_url else ""

    meta_parts = []
    if movie.year:
        meta_parts.append(str(movie.year))
    meta_parts.append("Ungesehen" if movie.location == "NEU" else "Gesehen")
    if movie.genre_names:
        meta_parts.append(movie.genre_names)
    meta = html.escape(" · ".join(meta_parts))

    overview = html.escape(movie.overview or "Keine Beschreibung vorhanden.")

    if is_android:
        # Android: VLC direkt per Intent-Link starten.
        vlc_url = (
            f"intent://{host}/stream/{movie.id}"
            f"#Intent;scheme=http;package=org.videolan.vlc;type=video/*;end"
        )
    else:
        # Windows/Desktop kennen "intent://" nicht. Stattdessen eine winzige
        # .m3u-Playlist-Datei anbieten: VLC registriert sich unter Windows
        # bei der Installation ueblicherweise selbst als Standard-Handler
        # fuer diesen Dateityp, wodurch ein Klick die Datei direkt in VLC
        # oeffnet (bzw. der Browser bietet nach dem kurzen Download "Oeffnen"
        # an) -- ganz ohne eigene Protokoll-Registrierung noetig.
        vlc_url = f"/playlist/{movie.id}.m3u"

    body = f"""
<a class="backlink" href="{back_url}">&larr; Zur Übersicht</a>
{cover_tag}
<div class="detail-title">{html.escape(movie.folder_name)}</div>
<div class="detail-meta">{meta}</div>
<a class="btn btn-primary" href="{vlc_url}">▶ In VLC abspielen</a>
<div class="detail-overview">{overview}</div>
"""
    return _page_shell(movie.folder_name, body, active_nav="movies")


def _safe_filename(name: str) -> str:
    """Entfernt Zeichen, die in einem HTTP-Header/Dateinamen Probleme
    machen koennten (Anfuehrungszeichen, Zeilenumbrueche etc.)."""
    cleaned = re.sub(r'[\\"\r\n]', "_", name).strip()
    return cleaned[:120] or "film"


SERIES_FILTER_LABELS = [
    ("all", "Alle"),
    ("neu", "Neu"),
    ("laufend", "Laufend"),
    ("archiv", "Archiv"),
]


def _collect_series_genres(series_list: list[Series]) -> list[str]:
    genres: set[str] = set()
    for s in series_list:
        if s.genre_names:
            for g in s.genre_names.split(","):
                g = g.strip()
                if g:
                    genres.add(g)
    return sorted(genres, key=str.lower)


def _filter_series(series_list: list[Series], q: str, filter_mode: str, genre: str) -> list[Series]:
    q = q.strip().lower()
    genre_lower = genre.strip().lower()
    result = []
    for s in series_list:
        if filter_mode == "neu" and s.location != "NEU":
            continue
        if filter_mode == "laufend" and s.location != "LAUFEND":
            continue
        if filter_mode == "archiv" and s.location != "ARCHIV":
            continue
        if genre_lower:
            series_genres = [g.strip().lower() for g in (s.genre_names or "").split(",") if g.strip()]
            if genre_lower not in series_genres:
                continue
        if q and q not in s.folder_name.lower():
            continue
        result.append(s)
    return result


def _sort_series(series_list: list[Series], sort_mode: str) -> list[Series]:
    if sort_mode == "added":
        return sorted(series_list, key=lambda s: s.folder_ctime or 0)
    if sort_mode == "year":
        return sorted(series_list, key=lambda s: (-(s.first_air_year or 0), (s.folder_name or "").lower()))
    return sorted(series_list, key=lambda s: (s.folder_name or "").lower())


def _render_series_overview_page(all_series: list[Series], episode_counts: dict[int, tuple[int, int]],
                                  q: str, filter_mode: str, sort_mode: str, genre: str) -> bytes:
    series_list = _sort_series(_filter_series(all_series, q, filter_mode, genre), sort_mode)
    q_encoded = quote(q)
    genre_encoded = quote(genre)
    all_genres = _collect_series_genres(all_series)

    filter_pills = []
    for mode, label in SERIES_FILTER_LABELS:
        active = " active" if mode == filter_mode else ""
        filter_pills.append(
            f'<a class="pill{active}" href="/series?filter={mode}&q={q_encoded}'
            f'&sort={sort_mode}&genre={genre_encoded}">{label}</a>'
        )

    sort_options = "".join(
        f'<option value="{mode}"{" selected" if mode == sort_mode else ""}>{label}</option>'
        for mode, label in SORT_LABELS
    )
    genre_options = '<option value="">Alle Genres</option>' + "".join(
        f'<option value="{html.escape(g)}"{" selected" if g == genre else ""}>{html.escape(g)}</option>'
        for g in all_genres
    )

    toolbar = f"""
<div class="toolbar">
  <form method="get" action="/series">
    <input type="hidden" name="filter" value="{html.escape(filter_mode)}">
    <div class="search-row">
      <input type="text" name="q" value="{html.escape(q)}" placeholder="Serien durchsuchen …">
      <button type="submit">🔍</button>
    </div>
    <div class="select-row">
      <select name="sort" onchange="this.form.submit()">{sort_options}</select>
      <select name="genre" onchange="this.form.submit()">{genre_options}</select>
    </div>
  </form>
  <div class="filters">{"".join(filter_pills)}</div>
</div>
<div class="count">{len(series_list)} Serie{"n" if len(series_list) != 1 else ""}</div>
"""

    if not series_list:
        body = "<h1>📺 CineVault Mobile</h1>" + toolbar + "<p class='empty'>Keine Serien gefunden.</p>"
        return _page_shell("CineVault Mobile", body, active_nav="series")

    cards = []
    for s in series_list:
        cover_url = f"/series/cover/{s.id}" if s.poster_path else ""
        img_tag = f'<img src="{cover_url}" alt="">' if cover_url else '<img alt="">'
        badge = ""
        if s.location == "NEU":
            badge = '<div class="badge">NEU</div>'
        elif s.location == "LAUFEND":
            badge = '<div class="badge laufend">LAUFEND</div>'
        cards.append(
            f'<a class="card" href="/series/watch/{s.id}?filter={filter_mode}&q={q_encoded}'
            f'&sort={sort_mode}&genre={genre_encoded}">{img_tag}{badge}'
            f'<div class="title">{html.escape(s.folder_name)}</div></a>'
        )
    body = "<h1>📺 CineVault Mobile</h1>" + toolbar + '<div class="grid">' + "".join(cards) + "</div>"
    return _page_shell("CineVault Mobile", body, active_nav="series")


def _episode_vlc_url(host: str, episode: Episode, is_android: bool) -> str:
    if is_android:
        return (
            f"intent://{host}/series/stream/{episode.id}"
            f"#Intent;scheme=http;package=org.videolan.vlc;type=video/*;end"
        )
    return f"/series/playlist/{episode.id}.m3u"


def _render_series_watch_page(series: Series, episodes: list[Episode], host: str,
                               back_url: str, self_url: str, is_android: bool) -> bytes:
    cover_url = f"/series/cover/{series.id}" if series.poster_path else ""
    cover_tag = f'<img class="detail-cover" src="{cover_url}" alt="">' if cover_url else ""

    location_labels = {"NEU": "Noch nicht begonnen", "LAUFEND": "Wird geschaut", "ARCHIV": "Abgeschlossen"}
    meta_parts = []
    if series.first_air_year:
        meta_parts.append(str(series.first_air_year))
    meta_parts.append(location_labels.get(series.location, series.location))
    if series.genre_names:
        meta_parts.append(series.genre_names)
    active_episodes = [e for e in episodes if e.missing == 0]
    seen_count = sum(1 for e in active_episodes if e.seen)
    meta_parts.append(f"{seen_count}/{len(active_episodes)} gesehen")
    meta = html.escape(" · ".join(meta_parts))

    overview = html.escape(series.overview or "Keine Beschreibung vorhanden.")

    unseen = [e for e in active_episodes if not e.seen]
    next_ep = min(unseen, key=lambda e: (e.season_number, e.episode_number)) if unseen else None
    play_button = ""
    if next_ep is not None:
        vlc_url = _episode_vlc_url(host, next_ep, is_android)
        play_button = (
            f'<a class="btn btn-primary" href="{vlc_url}">'
            f'▶ S{next_ep.season_number:02d}E{next_ep.episode_number:02d} abspielen</a>'
        )

    # Nach dem Abhaken einer Episode soll wieder GENAU diese Seite (mit
    # denselben Filter-Parametern) erscheinen, nicht die Uebersicht.
    back_encoded = quote(self_url)

    episodes_html = []
    sorted_episodes = sorted(active_episodes, key=lambda e: (e.season_number, e.episode_number))
    current_season = None
    for ep in sorted_episodes:
        if ep.season_number != current_season:
            current_season = ep.season_number
            episodes_html.append(f'<div class="season-header">Staffel {current_season:02d}</div>')
        toggle_symbol = "☑" if ep.seen else "☐"
        toggle_url = f"/series/toggle_episode/{ep.id}?back={back_encoded}"
        title = f"S{ep.season_number:02d}E{ep.episode_number:02d}"
        if ep.title:
            title += f" – {html.escape(ep.title)}"
        ep_vlc_url = _episode_vlc_url(host, ep, is_android)
        episodes_html.append(
            f'<div class="episode-row">'
            f'<a class="ep-toggle" href="{toggle_url}">{toggle_symbol}</a>'
            f'<span class="ep-title">{title}</span>'
            f'<a class="ep-play" href="{ep_vlc_url}">▶</a>'
            f'</div>'
        )

    body = f"""
<a class="backlink" href="{back_url}">&larr; Zur Übersicht</a>
{cover_tag}
<div class="detail-title">{html.escape(series.display_title)}</div>
<div class="detail-meta">{meta}</div>
{play_button}
<div class="detail-overview">{overview}</div>
{"".join(episodes_html)}
"""
    return _page_shell(series.display_title, body, active_nav="series")


def _make_handler(library: Library, db: Database, series_library: SeriesLibrary | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "CineVault/1.0"

        def log_message(self, format, *args):  # noqa: A002 - Signatur von BaseHTTPRequestHandler
            pass  # unterdrueckt die Standard-Konsolenausgabe pro Request

        def _movie_or_404(self, movie_id_str: str) -> Movie | None:
            try:
                movie_id = int(movie_id_str)
            except ValueError:
                self.send_error(404)
                return None
            movie = db.get(movie_id)
            if movie is None or movie.missing:
                self.send_error(404)
                return None
            return movie

        def _series_or_404(self, series_id_str: str) -> Series | None:
            if series_library is None:
                self.send_error(404)
                return None
            try:
                series_id = int(series_id_str)
            except ValueError:
                self.send_error(404)
                return None
            series = db.get_series(series_id)
            if series is None or series.missing:
                self.send_error(404)
                return None
            return series

        def _episode_or_404(self, episode_id_str: str) -> Episode | None:
            if series_library is None:
                self.send_error(404)
                return None
            try:
                episode_id = int(episode_id_str)
            except ValueError:
                self.send_error(404)
                return None
            episode = db.get_episode(episode_id)
            if episode is None or episode.missing:
                self.send_error(404)
                return None
            return episode

        def do_GET(self):  # noqa: N802 - von BaseHTTPRequestHandler vorgegeben
            parsed = urlparse(self.path)
            path = parsed.path
            query = parse_qs(parsed.query)

            if path == "/" or path == "":
                self._handle_overview(query)
            elif path.startswith("/watch/"):
                self._handle_watch(path[len("/watch/"):], query)
            elif path.startswith("/cover/"):
                self._handle_cover(path[len("/cover/"):])
            elif path.startswith("/stream/"):
                self._handle_stream(path[len("/stream/"):])
            elif path.startswith("/playlist/") and path.endswith(".m3u"):
                self._handle_playlist(path[len("/playlist/"):-len(".m3u")])
            elif path == "/series" or path == "/series/":
                self._handle_series_overview(query)
            elif path.startswith("/series/watch/"):
                self._handle_series_watch(path[len("/series/watch/"):], query)
            elif path.startswith("/series/cover/"):
                self._handle_series_cover(path[len("/series/cover/"):])
            elif path.startswith("/series/stream/"):
                self._handle_series_stream(path[len("/series/stream/"):])
            elif path.startswith("/series/playlist/") and path.endswith(".m3u"):
                self._handle_series_playlist(path[len("/series/playlist/"):-len(".m3u")])
            elif path.startswith("/series/toggle_episode/"):
                self._handle_toggle_episode(path[len("/series/toggle_episode/"):], query)
            elif path == "/icon.png":
                self._handle_app_icon()
            elif path == "/manifest.json":
                self._handle_manifest()
            else:
                self.send_error(404)

        def _handle_app_icon(self):
            icon_path = app_assets_dir() / "cinevault.png"
            if not icon_path.exists():
                self.send_error(404)
                return
            self._serve_file(icon_path, allow_range=False)

        def _handle_manifest(self):
            manifest = (
                '{"name":"CineVault Mobile","short_name":"CV Mobile","start_url":"/",'
                '"display":"standalone","background_color":"#14161c",'
                '"theme_color":"#14161c","icons":['
                '{"src":"/icon.png","sizes":"256x256","type":"image/png","purpose":"any maskable"}'
                ']}'
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/manifest+json")
            self.send_header("Content-Length", str(len(manifest)))
            self.end_headers()
            self.wfile.write(manifest)

        def _send_html(self, body: bytes):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _send_redirect(self, location: str):
            self.send_response(302)
            self.send_header("Location", location)
            self.end_headers()

        def _handle_overview(self, query: dict):
            q = query.get("q", [""])[0]
            filter_mode = query.get("filter", ["all"])[0]
            if filter_mode not in ("all", "unseen", "seen", "rewatch"):
                filter_mode = "all"
            sort_mode = query.get("sort", ["title"])[0]
            if sort_mode not in ("title", "added", "year"):
                sort_mode = "title"
            genre = query.get("genre", [""])[0]

            all_movies = [m for m in db.list_movies() if not m.missing]
            body = _render_overview_page(all_movies, q, filter_mode, sort_mode, genre)
            self._send_html(body)

        def _handle_watch(self, movie_id_str: str, query: dict):
            movie = self._movie_or_404(movie_id_str)
            if movie is None:
                return
            q = query.get("q", [""])[0]
            filter_mode = query.get("filter", ["all"])[0]
            sort_mode = query.get("sort", ["title"])[0]
            genre = query.get("genre", [""])[0]
            back_url = (
                f"/?filter={quote(filter_mode)}&q={quote(q)}"
                f"&sort={quote(sort_mode)}&genre={quote(genre)}"
            )
            host = self.headers.get("Host", f"{get_local_ip()}:{self.server.server_port}")
            user_agent = self.headers.get("User-Agent", "")
            is_android = "android" in user_agent.lower()
            body = _render_watch_page(movie, host, back_url, is_android)
            self._send_html(body)

        def _handle_playlist(self, movie_id_str: str):
            movie = self._movie_or_404(movie_id_str)
            if movie is None:
                return
            host = self.headers.get("Host", f"{get_local_ip()}:{self.server.server_port}")
            stream_url = f"http://{host}/stream/{movie.id}"
            playlist = (
                f"#EXTM3U\n#EXTINF:-1,{movie.folder_name}\n{stream_url}\n"
            ).encode("utf-8")
            filename = _safe_filename(movie.folder_name)
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-mpegurl")
            self.send_header("Content-Disposition", f'attachment; filename="{filename}.m3u"')
            self.send_header("Content-Length", str(len(playlist)))
            self.end_headers()
            self.wfile.write(playlist)

        def _handle_cover(self, movie_id_str: str):
            movie = self._movie_or_404(movie_id_str)
            if movie is None:
                return
            if not movie.poster_path:
                self.send_error(404)
                return
            cover_path = library.dir_covers / movie.poster_path
            if not cover_path.exists():
                cover_path = library.dir_thumbs / movie.poster_path
            if not cover_path.exists():
                self.send_error(404)
                return
            self._serve_file(cover_path, allow_range=False)

        def _handle_stream(self, movie_id_str: str):
            movie = self._movie_or_404(movie_id_str)
            if movie is None:
                return
            if not movie.video_path:
                self.send_error(404)
                return
            video_path = Path(movie.video_path)
            if not video_path.exists():
                self.send_error(404)
                return
            self._serve_file(video_path, allow_range=True)

        # ---------------- Serien ----------------

        def _handle_series_overview(self, query: dict):
            if series_library is None:
                self.send_error(404)
                return
            q = query.get("q", [""])[0]
            filter_mode = query.get("filter", ["all"])[0]
            if filter_mode not in ("all", "neu", "laufend", "archiv"):
                filter_mode = "all"
            sort_mode = query.get("sort", ["title"])[0]
            if sort_mode not in ("title", "added", "year"):
                sort_mode = "title"
            genre = query.get("genre", [""])[0]

            all_series = [s for s in db.list_series() if not s.missing]
            episode_counts = {s.id: db.count_episodes_for_series(s.id) for s in all_series}
            body = _render_series_overview_page(all_series, episode_counts, q, filter_mode, sort_mode, genre)
            self._send_html(body)

        def _handle_series_watch(self, series_id_str: str, query: dict):
            series = self._series_or_404(series_id_str)
            if series is None:
                return
            q = query.get("q", [""])[0]
            filter_mode = query.get("filter", ["all"])[0]
            sort_mode = query.get("sort", ["title"])[0]
            genre = query.get("genre", [""])[0]
            back_url = (
                f"/series?filter={quote(filter_mode)}&q={quote(q)}"
                f"&sort={quote(sort_mode)}&genre={quote(genre)}"
            )
            self_url = (
                f"/series/watch/{series.id}?filter={quote(filter_mode)}&q={quote(q)}"
                f"&sort={quote(sort_mode)}&genre={quote(genre)}"
            )
            host = self.headers.get("Host", f"{get_local_ip()}:{self.server.server_port}")
            user_agent = self.headers.get("User-Agent", "")
            is_android = "android" in user_agent.lower()
            episodes = db.list_episodes_for_series(series.id)
            body = _render_series_watch_page(series, episodes, host, back_url, self_url, is_android)
            self._send_html(body)

        def _handle_toggle_episode(self, episode_id_str: str, query: dict):
            episode = self._episode_or_404(episode_id_str)
            if episode is None:
                return
            series = db.get_series(episode.series_id)
            if series is None:
                self.send_error(404)
                return
            try:
                toggle_episode_seen(series_library, db, series, episode, not episode.seen)
            except Exception:
                pass  # Verschieben o.ae. fehlgeschlagen -- Abhaken bleibt trotzdem bestmoeglich erhalten
            back = query.get("back", [f"/series/watch/{series.id}"])[0]
            self._send_redirect(back)

        def _handle_series_playlist(self, episode_id_str: str):
            episode = self._episode_or_404(episode_id_str)
            if episode is None:
                return
            host = self.headers.get("Host", f"{get_local_ip()}:{self.server.server_port}")
            stream_url = f"http://{host}/series/stream/{episode.id}"
            label = f"S{episode.season_number:02d}E{episode.episode_number:02d}"
            playlist = f"#EXTM3U\n#EXTINF:-1,{label}\n{stream_url}\n".encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "audio/x-mpegurl")
            self.send_header("Content-Disposition", f'attachment; filename="{_safe_filename(label)}.m3u"')
            self.send_header("Content-Length", str(len(playlist)))
            self.end_headers()
            self.wfile.write(playlist)

        def _handle_series_cover(self, series_id_str: str):
            series = self._series_or_404(series_id_str)
            if series is None:
                return
            if not series.poster_path:
                self.send_error(404)
                return
            cover_path = series_library.dir_covers / series.poster_path
            if not cover_path.exists():
                cover_path = series_library.dir_thumbs / series.poster_path
            if not cover_path.exists():
                self.send_error(404)
                return
            self._serve_file(cover_path, allow_range=False)

        def _handle_series_stream(self, episode_id_str: str):
            episode = self._episode_or_404(episode_id_str)
            if episode is None:
                return
            series = db.get_series(episode.series_id)
            if series is None:
                self.send_error(404)
                return
            video_path = episode_video_path(series_library, series, episode.relative_path)
            if not video_path.exists():
                self.send_error(404)
                return
            self._serve_file(video_path, allow_range=True)

        def _serve_file(self, path: Path, allow_range: bool):
            file_size = path.stat().st_size
            content_type = _mime_for(path)
            range_header = self.headers.get("Range") if allow_range else None

            start, end = 0, file_size - 1
            is_partial = False
            if range_header:
                match = _RANGE_RE.match(range_header)
                if match:
                    start = int(match.group(1))
                    end = int(match.group(2)) if match.group(2) else file_size - 1
                    end = min(end, file_size - 1)
                    is_partial = True

            length = end - start + 1

            try:
                self.send_response(206 if is_partial else 200)
                self.send_header("Content-Type", content_type)
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Content-Length", str(length))
                if is_partial:
                    self.send_header("Content-Range", f"bytes {start}-{end}/{file_size}")
                self.end_headers()

                with open(path, "rb") as f:
                    f.seek(start)
                    remaining = length
                    while remaining > 0:
                        chunk = f.read(min(_CHUNK_SIZE, remaining))
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                        remaining -= len(chunk)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass  # Nutzer hat Wiedergabe abgebrochen/gewechselt -- kein Fehlerfall

    return Handler


class CineVaultStreamingServer:
    """Startet/stoppt den lokalen Streaming-Server. Laeuft in einem eigenen
    Hintergrund-Thread (daemon), blockiert also weder den Programmstart noch
    die Oberflaeche."""

    def __init__(self, library: Library, db: Database, series_library: SeriesLibrary | None = None,
                 port: int = 8765):
        self.library = library
        self.db = db
        self.series_library = series_library
        handler_cls = _make_handler(library, db, series_library)
        self.httpd = ThreadingHTTPServer(("0.0.0.0", port), handler_cls)
        self.port = self.httpd.server_address[1]
        self._thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    @property
    def url(self) -> str:
        return f"http://{get_local_ip()}:{self.port}"
