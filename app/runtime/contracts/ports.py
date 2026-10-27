"""Host-neutral runtime ports and memory-context DTOs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
class Clock(Protocol):
    """Wall-clock source used by the runtime; returns UTC epoch seconds."""

    def __call__(self) -> float: ...

class TraceSink(Protocol):
    def record(self, kind: str, status: str, context: dict[str, Any] | None = None) -> None: ...


@dataclass(frozen=True)
class MemoryContextRequest:
    """Host-neutral request for read-only memory context."""

    session_id: str
    query: str = ""
    source_id: str = ""
    speaker_id: str = ""
    private: bool = False
    event_time: float = 0.0
    received_at: float = 0.0
    now: float = 0.0
    reason: str = ""


@dataclass(frozen=True)
class MemoryContext:
    text: str = ""
    info: dict[str, Any] = field(default_factory=dict)


class MemoryContextPort(Protocol):
    def build_context(self, request: MemoryContextRequest) -> MemoryContext: ...


class ModelGateway(Protocol):
    async def complete(
        self, session_id: str, prompt: str, system_prompt: str | None = None
    ) -> str: ...


class MessageSender(Protocol):
    async def send(self, session_id: str, text: str) -> bool: ...

