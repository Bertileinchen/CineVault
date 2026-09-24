from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPropertyAnimation, QTimer
from PySide6.QtWidgets import QAbstractItemView, QListView

HOVER_DURATION_MS = 160
SCROLL_ANIM_DURATION_MS = 260
SCROLL_PIXELS_PER_NOTCH = 170  # "Weite" eines Mausrad-"Klicks" (Standard-Notch = 120)


class MovieListView(QListView):
    """QListView mit sanft animiertem Hover-Effekt auf den Film-Kacheln
    (Kachel waechst/leuchtet leicht auf) sowie fluessigem, animiert
    abgefedertem Scrollen statt abrupter, ruckartiger Spruenge pro
    Mausrad-Tick."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)

        # Pixelweises statt zeilenweises Scrollen -> Grundlage fuer fluessiges
        # Verhalten (kein Sprung auf volle Zeilenhoehen).
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        self._hover_row = -1
        self._hover_progress = 0.0
        self._leaving_row = -1
        self._leaving_start = 0.0

        self._elapsed = QElapsedTimer()
        self._easing = QEasingCurve(QEasingCurve.OutCubic)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)  # ~60 FPS
        self._anim_timer.timeout.connect(self._on_tick)

        # Sanft abgefedertes Mausrad-Scrollen: statt den Scrollbalken beim
        # Wheel-Event hart auf den neuen Wert zu springen, wird animiert
        # dorthin geglitten (aehnlich wie bei Trackpads/Touch-Oberflaechen).
        self._scroll_anim = QPropertyAnimation(self, b"")
        self._scroll_target = 0

    # ---------------- Groesseren, angenehmeren Scrollschritt setzen ----------------

    def setModel(self, model):  # noqa: N802 (Qt-Namenskonvention)
        super().setModel(model)
        self._tune_scrollbar()

    def _tune_scrollbar(self):
        bar = self.verticalScrollBar()
        if bar is not None:
            bar.setSingleStep(48)
            self._scroll_target = bar.value()
            self._scroll_anim.stop()
            self._scroll_anim = QPropertyAnimation(bar, b"value", self)
            self._scroll_anim.setEasingCurve(QEasingCurve.OutCubic)

    # ---------------- Sanft animiertes Mausrad-Scrollen ----------------

    def wheelEvent(self, event):
        bar = self.verticalScrollBar()
        angle = event.angleDelta().y()
        if bar is None or angle == 0 or bar.maximum() == bar.minimum():
            super().wheelEvent(event)
            return

        notches = angle / 120.0
        delta_px = -notches * SCROLL_PIXELS_PER_NOTCH

        # Laeuft die Animation gerade noch, wird vom bisherigen Ziel aus
        # weitergerechnet (nicht vom aktuell angezeigten Zwischenwert) --
        # dadurch reihen sich mehrere schnelle Wheel-Ticks zu einer einzigen,
        # gleichmaessig gleitenden Bewegung statt vieler kleiner Ruckler.
        base = self._scroll_target if self._scroll_anim.state() == QPropertyAnimation.Running else bar.value()
        target = int(max(bar.minimum(), min(bar.maximum(), base + delta_px)))
        self._scroll_target = target

        self._scroll_anim.stop()
        self._scroll_anim.setDuration(SCROLL_ANIM_DURATION_MS)
        self._scroll_anim.setStartValue(bar.value())
        self._scroll_anim.setEndValue(target)
        self._scroll_anim.start()
        event.accept()

    # ---------------- Hover-Animation ----------------

    def hover_progress_for(self, row: int) -> float:
        """Liefert den aktuellen Animationsfortschritt (0..1) fuer eine Zeile:
        1.0 = voll gehovert, 0.0 = nicht gehovert, dazwischen waehrend der
        Animation."""
        if row < 0:
            return 0.0
        if row == self._hover_row:
            return self._hover_progress
        if row == self._leaving_row:
            t = min(1.0, self._elapsed.elapsed() / HOVER_DURATION_MS)
            eased = self._easing.valueForProgress(t)
            return self._leaving_start * (1.0 - eased)
        return 0.0

    def _start_transition(self, new_row: int):
        if new_row == self._hover_row:
            return
        if self._hover_row != -1:
            self._leaving_row = self._hover_row
            self._leaving_start = self._hover_progress
        else:
            self._leaving_row = -1
            self._leaving_start = 0.0

        self._hover_row = new_row
        self._hover_progress = 0.0
        self._elapsed.restart()
        if not self._anim_timer.isActive():
            self._anim_timer.start()

    def _on_tick(self):
        t = min(1.0, self._elapsed.elapsed() / HOVER_DURATION_MS)
        eased = self._easing.valueForProgress(t)
        self._hover_progress = eased if self._hover_row != -1 else 0.0
        self.viewport().update()
        if t >= 1.0:
            self._anim_timer.stop()
            self._leaving_row = -1

    def mouseMoveEvent(self, event):
        super().mouseMoveEvent(event)
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        index = self.indexAt(pos)
        row = index.row() if index.isValid() else -1
        if row != self._hover_row:
            self._start_transition(row)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self._hover_row != -1:
            self._start_transition(-1)
