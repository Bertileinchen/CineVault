from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .constants import CARD_H, CARD_W, MARGIN, POSTER_H, POSTER_W
from .movie_model import COMPLETENESS_ROLE, IS_MISSING_ROLE, LOCATION_ROLE, REWATCH_ROLE, YEAR_ROLE

# Wie stark die Kachel beim Hover maximal "aufploppt" (Pixel, bei Progress 1.0)
HOVER_MAX_INFLATE = 6
REWATCH_COLOR = QColor("#7c5cff")
BORDER_COLOR = QColor("#2f3340")


def _lerp_color(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _wrap_two_lines(fm: QFontMetrics, text: str, max_width: int) -> tuple[str, str]:
    """Bricht einen Titel auf maximal zwei Zeilen um (an Wortgrenzen). Passt
    die zweite Zeile noetigenfalls per Ellipse an, falls selbst sie noch zu
    lang waere."""
    words = text.split()
    if not words:
        return "", ""

    line1 = words[0]
    idx = 1
    while idx < len(words):
        trial = f"{line1} {words[idx]}"
        if fm.horizontalAdvance(trial) <= max_width:
            line1 = trial
            idx += 1
        else:
            break
    if fm.horizontalAdvance(line1) > max_width:
        line1 = fm.elidedText(line1, Qt.ElideRight, max_width)

    remaining = " ".join(words[idx:])
    if not remaining:
        return line1, ""
    if fm.horizontalAdvance(remaining) > max_width:
        remaining = fm.elidedText(remaining, Qt.ElideRight, max_width)
    return line1, remaining


class MovieCardDelegate(QStyledItemDelegate):
    def __init__(self, accent_color: str = "#4f7cff", parent=None):
        super().__init__(parent)
        self._accent = QColor(accent_color)

    def set_accent_color(self, accent_color: str) -> None:
        self._accent = QColor(accent_color)

    def sizeHint(self, option: QStyleOptionViewItem, index) -> QSize:
        return QSize(CARD_W, CARD_H)

    def _hover_progress(self, option: QStyleOptionViewItem, index) -> float:
        view = option.widget
        if view is not None and hasattr(view, "hover_progress_for"):
            return view.hover_progress_for(index.row())
        return 0.0

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing, True)

        progress = self._hover_progress(option, index)

        rect: QRect = option.rect
        card_rect = QRect(rect.x() + 3, rect.y() + 3, rect.width() - 6, rect.height() - 6)

        # Hintergrund: Selektion fest, Hover sanft eingeblendet ueber Progress.
        if option.state & QStyle.State_Selected:
            bg_path = QPainterPath()
            bg_path.addRoundedRect(QRectF(card_rect), 12, 12)
            painter.fillPath(bg_path, QColor("#262a35"))
        elif progress > 0.0:
            bg_path = QPainterPath()
            bg_path.addRoundedRect(QRectF(card_rect), 12, 12)
            bg_color = QColor("#262a35")
            bg_color.setAlphaF(0.85 * progress)
            painter.fillPath(bg_path, bg_color)

        # Basis-Position des Posters (unveraendert, damit Titel & Badges nicht
        # "springen") -- das eigentliche Zeichnen erfolgt in einem beim Hover
        # leicht vergroesserten Rechteck ("Lift"-Effekt).
        poster_x = card_rect.x() + (card_rect.width() - POSTER_W) // 2
        poster_y = card_rect.y() + MARGIN
        poster_rect = QRect(poster_x, poster_y, POSTER_W, POSTER_H)

        inflate = round(HOVER_MAX_INFLATE * progress)
        draw_rect = poster_rect.adjusted(-inflate, -inflate, inflate, inflate)

        # Sanftes Gluehen hinter dem Cover, staerker je weiter man "drin" ist.
        if progress > 0.0:
            glow_rect = draw_rect.adjusted(-5, -5, 5, 5)
            glow_path = QPainterPath()
            glow_path.addRoundedRect(QRectF(glow_rect), 14, 14)
            glow_color = QColor(self._accent)
            glow_color.setAlphaF(0.35 * progress)
            painter.fillPath(glow_path, glow_color)

        pixmap = index.data(Qt.DecorationRole)
        clip_path = QPainterPath()
        clip_path.addRoundedRect(QRectF(draw_rect), 10, 10)
        painter.save()
        painter.setClipPath(clip_path)
        if pixmap and not pixmap.isNull():
            if pixmap.size() == draw_rect.size():
                # Bereits passend vorskaliert (Normalfall) -> kein teures
                # erneutes Skalieren bei jedem Paint-Aufruf noetig.
                painter.drawPixmap(draw_rect.topLeft(), pixmap)
            else:
                scaled = pixmap.scaled(draw_rect.size(), Qt.KeepAspectRatioByExpanding,
                                        Qt.SmoothTransformation)
                dx = draw_rect.x() - (scaled.width() - draw_rect.width()) // 2
                dy = draw_rect.y() - (scaled.height() - draw_rect.height()) // 2
                painter.drawPixmap(dx, dy, scaled)
        else:
            painter.fillRect(draw_rect, QColor("#21242e"))
            painter.setPen(QColor("#5a5f6c"))
            painter.setFont(QFont(painter.font().family(), 9))
            painter.drawText(draw_rect, Qt.AlignCenter, "Kein Cover")
        painter.restore()

        # Rahmen um das Poster, faerbt sich beim Hover in Richtung Akzentfarbe.
        border_color = _lerp_color(BORDER_COLOR, self._accent, progress)
        painter.setPen(QPen(border_color, 1 + progress))
        painter.drawRoundedRect(QRectF(draw_rect), 10, 10)

        # "MISSING" (rot) hat Vorrang vor allem anderen -- ein Film, dessen
        # Ordner nicht mehr gefunden wurde, ist die dringendste Information.
        # Sonst "NEU" fuer ungesehene, "REWATCH" fuer zum nochmal-Ansehen
        # vorgemerkte Filme (alle am selben Platz, da praktisch nie mehrere
        # Zustaende gleichzeitig zutreffen).
        location = index.data(LOCATION_ROLE)
        is_rewatch = bool(index.data(REWATCH_ROLE))
        is_missing = bool(index.data(IS_MISSING_ROLE))
        if is_missing or location == "NEU" or is_rewatch:
            if is_missing:
                badge_text, badge_color = "MISSING", QColor("#e05f5f")
            elif location == "NEU":
                badge_text, badge_color = "NEU", self._accent
            else:
                badge_text, badge_color = "REWATCH", REWATCH_COLOR
            painter.setFont(QFont(painter.font().family(), 8, QFont.Bold))
            fm = QFontMetrics(painter.font())
            bw = fm.horizontalAdvance(badge_text) + 14
            bh = fm.height() + 6
            badge_rect = QRect(draw_rect.right() - bw - 6, draw_rect.top() + 6, bw, bh)
            badge_path = QPainterPath()
            badge_path.addRoundedRect(QRectF(badge_rect), bh / 2, bh / 2)
            painter.fillPath(badge_path, badge_color)
            painter.setPen(QColor("#ffffff"))
            painter.drawText(badge_rect, Qt.AlignCenter, badge_text)

        # Vollstaendigkeits-Indikator (kleiner Punkt): rot = weder Cover noch
        # Beschreibung vorhanden, gelb = nur eines von beiden, kein Punkt =
        # beides vorhanden (unabhaengig davon, ob automatisch oder von Hand
        # eingetragen).
        completeness = index.data(COMPLETENESS_ROLE)
        if completeness in ("missing", "partial"):
            dot_color = "#e05f5f" if completeness == "missing" else "#e0a83e"
            dot_rect = QRect(draw_rect.left() + 8, draw_rect.top() + 8, 10, 10)
            painter.setBrush(QColor(dot_color))
            painter.setPen(Qt.NoPen)
            painter.drawEllipse(dot_rect)

        # Titel (Position bleibt am unveraenderten poster_rect verankert,
        # damit das Layout beim Hover nicht "springt"). Echter 2-zeiliger
        # Umbruch an Wortgrenzen statt einzeiliger Kuerzung, da viele Titel
        # (bzw. Ordnernamen) sonst kaum lesbar waren.
        title = index.data(Qt.DisplayRole) or ""
        year = index.data(YEAR_ROLE)
        painter.setFont(QFont(painter.font().family(), 10, QFont.DemiBold))
        fm = QFontMetrics(painter.font())
        max_text_width = card_rect.width() - 2 * MARGIN
        line1, line2 = _wrap_two_lines(fm, title, max_text_width)

        line_height = fm.height()
        title_rect = QRect(card_rect.x() + MARGIN, poster_rect.bottom() + 8,
                            max_text_width, line_height * 2 + 4)
        title_color = _lerp_color(QColor("#e8e8ec"), QColor("#ffffff"), progress)
        painter.setPen(title_color)
        display_text = line1 if not line2 else f"{line1}\n{line2}"
        painter.drawText(title_rect, Qt.AlignHCenter | Qt.AlignTop, display_text)

        if year:
            year_rect = QRect(card_rect.x() + MARGIN, title_rect.bottom() + 2,
                               max_text_width, 18)
            painter.setPen(QColor("#9aa0ac"))
            painter.setFont(QFont(painter.font().family(), 8))
            painter.drawText(year_rect, Qt.AlignHCenter | Qt.AlignTop, str(year))

        painter.restore()
