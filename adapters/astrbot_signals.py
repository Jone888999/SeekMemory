"""Read-only AstrBot signal adapter for the host-neutral runtime policies."""

from __future__ import annotations

import time

from ..app.runtime.scene_hints import time_window
from ..app.runtime.signals import Signals

MAX_MEMORY_SCAN = 150


def _bigrams(text: str) -> set[str]:
    raw = "".join(ch for ch in str(text or "") if ch.isalnum())
    return {raw[i : i + 2] for i in range(len(raw) - 1)}


class AstrBotSignals:
    """Compute relationship, relevance and heat without mutating memory."""

    def __init__(self, cache, buffer) -> None:
        self.cache = cache
        self.buffer = buffer

    def _relationship(self, speaker: str) -> float:
        try:
            count = 0
            for art in self.cache.active("memory"):
                if str(art.payload.get("level") or "") != "impression":
                    continue
                if speaker in (
                    str(art.header.said_by or ""),
                    str(art.header.subject_id or ""),
                ):
                    count += 1
            return min(1.0, count / 6.0)
        except Exception:  # noqa: BLE001 - read-only signals are fail-open
            return 0.0

    def _relevance(self, text: str) -> float:
        query = _bigrams(text)
        if not query:
            return 0.0
        best = 0.0
        try:
            arts = self.cache.active("memory")[:MAX_MEMORY_SCAN]
        except Exception:  # noqa: BLE001
            return 0.0
        for art in arts:
            body = str(art.payload.get("text") or "")
            if not body:
                continue
            overlap = len(query & _bigrams(body)) / len(query)
            best = max(best, overlap)
            if best >= 1.0:
                break
        return min(1.0, best)

    def _heat(self, session_id: str, now: float) -> float:
        try:
            cutoff = float(now) - 300
            recent = 0
            for turn in self.buffer.items:
                if str(turn.session_id) != session_id:
                    continue
                stamp = getattr(turn, "at", "")
                try:
                    recent += 1 if not stamp or float(stamp) >= cutoff else 0
                except (TypeError, ValueError):
                    recent += 1
            return min(1.0, recent / 10.0)
        except Exception:  # noqa: BLE001
            return 0.0

    def signals(self, event, state, now: float) -> Signals:
        moment = float(now)
        return Signals(
            relationship=self._relationship(event.speaker_id),
            relevance=self._relevance(event.text),
            heat=self._heat(event.session_id, moment),
            recency=max(0.0, moment - float(state.last_seen_at or 0.0)),
            window=time_window(time.localtime(moment).tm_hour),
        )
