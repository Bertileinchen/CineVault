from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from .constants import CARD_H, CARD_W, MARGIN, POSTER_H, POSTER_W
from .movie_delegate import _lerp_color, _wrap_two_lines
from .series_model import IS_MISSING_ROLE, LOCATION_ROLE, PROGRESS_ROLE, YEAR_ROLE

HOVER_MAX_INFLATE = 6
LAUFEND_COLOR = QColor("#e0a83e")
ARCHIV_COLOR = QColor("#5a5f6c")
BORDER_COLOR = QColor("#2f3340")


class SeriesCardDelegate(QStyledItemDelegate):
    """Analog zu MovieCardDelegate, aber mit dem 3-Status-Badge (NEU/
    LAUFEND/keins bei ARCHIV -- ein fertig geschauter Titel braucht keine
    staendige Kennzeichnung mehr) und einer Fortschrittsanzeige ('12/24')
    fuer begonnene Serien."""

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

        poster_x = card_rect.x() + (card_rect.width() - POSTER_W) // 2
        poster_y = card_rect.y() + MARGIN
        poster_rect = QRect(poster_x, poster_y, POSTER_W, POSTER_H)

        inflate = round(HOVER_MAX_INFLATE * progress)
        draw_rect = poster_rect.adjusted(-inflate, -inflate, inflate, inflate)

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

        border_color = _lerp_color(BORDER_COLOR, self._accent, progress)
        painter.setPen(QPen(border_color, 1 + progress))
        painter.drawRoundedRect(QRectF(draw_rect), 10, 10)

        # Status-Badge: "MISSING" (rot) hat Vorrang, sonst NEU (Akzentfarbe)
        # oder LAUFEND (gelb-orange). ARCHIV (fertig geschaut) bekommt
        # bewusst KEIN Badge mehr -- ein abgeschlossener Titel braucht keine
        # staendige Kennzeichnung.
        location = index.data(LOCATION_ROLE)
        is_missing = bool(index.data(IS_MISSING_ROLE))
        if is_missing or location in ("NEU", "LAUFEND"):
            if is_missing:
                badge_text, badge_color = "MISSING", QColor("#e05f5f")
            elif location == "NEU":
                badge_text, badge_color = "NEU", self._accent
            else:
                badge_text, badge_color = "LAUFEND", LAUFEND_COLOR
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

        # Fortschritt ("12/24") unten links auf dem Cover, sobald mindestens
        # eine Episode abgehakt wurde -- bei frisch begonnenen/fertigen
        # Serien nicht sonderlich aussagekraeftig (0/x bzw. x/x), daher nur
        # dazwischen angezeigt.
        seen_count, total_count = index.data(PROGRESS_ROLE) or (0, 0)
        if total_count > 0:
            progress_text = f"{seen_count}/{total_count}"
            painter.setFont(QFont(painter.font().family(), 8, QFont.Bold))
            fm = QFontMetrics(painter.font())
            pw = fm.horizontalAdvance(progress_text) + 12
            ph = fm.height() + 6
            progress_rect = QRect(draw_rect.left() + 6, draw_rect.bottom() - ph - 6, pw, ph)
            progress_path = QPainterPath()
            progress_path.addRoundedRect(QRectF(progress_rect), ph / 2, ph / 2)
            bg = QColor("#14161c")
            bg.setAlphaF(0.85)
            painter.fillPath(progress_path, bg)
            painter.setPen(QColor("#e8e8ec"))
            painter.drawText(progress_rect, Qt.AlignCenter, progress_text)

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
