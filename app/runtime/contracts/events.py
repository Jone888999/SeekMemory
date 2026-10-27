"""Event and decision DTOs shared by host adapters and runtime policies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
class AttentionLevel(str, Enum):
    AMBIENT = "ambient"
    ADDRESSED = "addressed"
    DIRECT = "direct"
    PRIVATE = "private"


class WakeAction(str, Enum):
    IGNORE = "ignore"
    OBSERVE = "observe"
    WAIT = "wait"
    REPLY = "reply"


@dataclass(frozen=True)
class RuntimeInput:
    """One inbound event reduced to host-neutral fields.

    ``event_time`` is when the platform says the event happened. ``received_at``
    is when this process observed it. Decision time is passed explicitly to the
    runtime methods and is never inferred from either field.
    """

    session_id: str
    text: str
    event_time: float = 0.0
    received_at: float = 0.0
    speaker_id: str = ""
    private: bool = False
    mentioned: bool = False
    question: bool = False
    unread_count: int = 0
    unread_seq: int = 0
    # 多平台语境；全部带默认值，旧调用方（#114 冻结契约）不需要改动。
    # scene 取值 private/group/channel/thread/comment；thread_id 承载评论嵌套或楼中楼；
    # role 取值 owner/admin/member/bot/system；
    # kind 预留给编辑、撤回、表情回应等非消息事件，当前只处理 message。
    scene: str = ""
    conversation_id: str = ""
    thread_id: str = ""
    self_id: str = ""
    role: str = ""
    addressed: bool = False
    reply_to_me: bool = False
    event_id: str = ""
    kind: str = "message"

    @property
    def is_owner(self) -> bool:
        """说话人是否为主人；只读派生，不参与序列化契约。"""
        return self.role == "owner"


@dataclass(frozen=True)
class RunContext:
    """One runtime unit before it becomes a durable result."""

    session_id: str
    text: str
    source_id: str = ""
    bot_id: str = ""
    event_time: float = 0.0
    received_at: float = 0.0
    run_id: str = ""


@dataclass(frozen=True)
class UserRunReceipt:
    """Identity and acknowledgement cursor for one accepted user turn."""

    decision: RunDecision
    source_id: str = ""
    turn_id: str = ""
    read_through_seq: int | None = None


@dataclass(frozen=True)
class RunResult:
    """Observed outcome of one runtime run."""

    run_id: str
    session_id: str
    delivered: bool
    assistant_source_id: str = ""
    response_chars: int = 0
    error: str = ""

@dataclass(frozen=True)
class RunDecision:
    action: WakeAction
    reason: str
    attention: AttentionLevel = AttentionLevel.AMBIENT
    must_reply: bool = False

