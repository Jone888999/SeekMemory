"""Memory-derived candidates for proactive turns.

This module only answers "what could the bot bring up"; it never decides
whether to speak or sends anything.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class TopicCandidate:
    """One read-only proactive topic candidate."""

    text: str
    kind: str = ""
    score: float = 0.0
    memory_ids: tuple[str, ...] = ()
    reason: str = ""


class TopicSource(Protocol):
    """Host-provided read-only source of candidates for one session."""

    def candidates(
        self, session_id: str, *, now: float, limit: int = 1
    ) -> list[TopicCandidate]: ...


def rank(candidates: list[TopicCandidate], limit: int = 1) -> list[TopicCandidate]:
    if limit <= 0:
        return []
    return sorted(candidates, key=lambda item: (-float(item.score), item.text))[:limit]
