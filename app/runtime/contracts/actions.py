"""Host action requests, results, audit records and ports."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol


class ActionKind(str, Enum):
    SEND_TEXT = "send_text"
    TOOL_CALL = "tool_call"
    HOST_ACTION = "host_action"


class ActionStatus(str, Enum):
    ATTEMPTED = "attempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class ActionRequest:
    """Transient host execution input; its text must never enter action audit."""

    session_id: str
    kind: ActionKind = ActionKind.SEND_TEXT
    text: str = ""


@dataclass(frozen=True)
class ActionResult:
    """Observed host execution result, without audit transition policy."""

    ok: bool
    reason: str = ""
@dataclass(frozen=True)
class ActionRecord:
    """Content-free action/handoff audit metadata.

    Message bodies, prompts, tool arguments and tool results must never be
    added here. ``action_id`` is the stable idempotency key for one action.
    """

    action_id: str
    session_id: str
    run_id: str = ""
    kind: ActionKind = ActionKind.HOST_ACTION
    status: ActionStatus = ActionStatus.ATTEMPTED
    reason: str = ""
    attempt: int = 1
    at: float = 0.0

    @property
    def terminal(self) -> bool:
        return self.status in (
            ActionStatus.SUCCEEDED,
            ActionStatus.FAILED,
            ActionStatus.CANCELLED,
        )
class ActionPort(Protocol):
    async def execute(self, request: ActionRequest) -> ActionResult: ...


class ActionSink(Protocol):
    def append(self, record: ActionRecord) -> None: ...
