"""Pure proactive policy result and protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .sessions import SessionState
@dataclass(frozen=True)
class ProactiveDecision:
    """Pure policy result: whether this session should be considered due."""

    should_speak: bool
    reason: str
    due_at: float = 0.0


class ProactivePolicy(Protocol):
    def evaluate(self, state: SessionState, *, now: float) -> ProactiveDecision: ...
