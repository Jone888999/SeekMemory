"""Per-session runtime state and its persistence port."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol
@dataclass
class SessionState:
    """Per-session timing and attention state. This is not memory."""

    session_id: str
    revision: int = 0
    last_event_at: float = 0.0
    last_seen_at: float = 0.0
    last_spoke_at: float = 0.0
    quiet_until: float = 0.0
    wait_until: float = 0.0
    unread_count: int = 0
    last_unread_seq: int = 0
    read_through_seq: int = 0
    ignored_streak: int = 0
    dispatch_attempts: int = 0
    next_retry_at: float = 0.0
    last_dispatched_source_id: str = ""
    last_action: str = ""
    last_reason: str = ""
    last_proactive_at: float = 0.0
    proactive_due_at: float = 0.0
    proactive_attempts: int = 0
    followup_by_speaker: dict[str, int] = field(default_factory=dict)


class SessionStateStore(Protocol):
    def get(self, session_id: str) -> SessionState: ...
    def put(self, state: SessionState) -> None: ...
