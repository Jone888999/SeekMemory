"""Content-free action audit lifecycle for tool and host actions."""

from __future__ import annotations

import hashlib
import math
from dataclasses import replace

from .contracts import ActionKind, ActionRecord, ActionSink, ActionStatus
from .episode import safe_error_code


def action_idempotency_key(
    run_id: str,
    callback_key: str,
    kind: ActionKind,
    *,
    session_id: str = "",
) -> str:
    """Derive a stable opaque key without persisting a host callback identifier."""
    callback = str(callback_key or "").strip()
    if not callback:
        raise ValueError("callback_key is required for action idempotency")
    action_kind = ActionKind(kind)
    material = "\0".join((
        str(session_id or ""),
        str(run_id or ""),
        action_kind.value,
        callback,
    ))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _moment(value: float) -> float:
    moment = float(value)
    if not math.isfinite(moment) or moment < 0.0:
        raise ValueError("action time must be finite and non-negative")
    return moment


class ActionLedger:
    """Record idempotent attempts and one terminal outcome through an ActionSink."""

    def __init__(self, sink: ActionSink) -> None:
        self.sink = sink

    def begin(
        self,
        *,
        session_id: str,
        run_id: str,
        callback_key: str,
        kind: ActionKind,
        at: float,
        attempt: int = 1,
        reason: str = "",
    ) -> ActionRecord:
        """Append one content-free attempt with a stable callback identity."""
        session = str(session_id or "").strip()
        if not session:
            raise ValueError("session_id is required for action audit")
        action_kind = ActionKind(kind)
        count = int(attempt)
        if count < 1:
            raise ValueError("attempt must be positive")
        record = ActionRecord(
            action_id=action_idempotency_key(
                run_id,
                callback_key,
                action_kind,
                session_id=session,
            ),
            session_id=session,
            run_id=str(run_id or ""),
            kind=action_kind,
            status=ActionStatus.ATTEMPTED,
            reason=safe_error_code(reason),
            attempt=count,
            at=_moment(at),
        )
        self.sink.append(record)
        return record

    def finish(
        self,
        attempted: ActionRecord,
        status: ActionStatus,
        *,
        at: float,
        reason: str = "",
    ) -> ActionRecord:
        """Append a success, failure, or cancellation for an attempted action."""
        if attempted.status is not ActionStatus.ATTEMPTED:
            raise ValueError("only an attempted action can transition to terminal")
        terminal_status = ActionStatus(status)
        if terminal_status is ActionStatus.ATTEMPTED:
            raise ValueError("terminal status must be succeeded, failed, or cancelled")
        record = replace(
            attempted,
            status=terminal_status,
            reason=safe_error_code(reason),
            at=_moment(at),
        )
        self.sink.append(record)
        return record


class RepoActionSink:
    """Adapt the SQL-owned runtime episode repository to the ActionSink port."""

    def __init__(self, repository) -> None:
        self.repository = repository

    def append(self, record: ActionRecord) -> None:
        self.repository.append_action({
            "action_id": record.action_id,
            "action_kind": record.kind.value,
            "action_status": record.status.value,
            "attempt": record.attempt,
            "at": record.at,
            "session_id": record.session_id,
            "run_id": record.run_id,
            "reason": record.reason,
        })
