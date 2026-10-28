"""Read-only relationship lookup and fixed interaction prompt projection."""

from __future__ import annotations

import math
from collections.abc import Callable
from typing import Any

try:
    from ..core.artifact import validate
    from ..core.interaction_policy import (
        INTERACTION_POLICY_VERSION,
        InteractionContext,
        InteractionGate,
        InteractionPolicySettings,
        ReplyStyle,
        decide_interaction,
    )
    from ..core.relationship import RelationshipSnapshot, snapshot_from_payload
    from ..app.ports import ArtifactCache
    from ..app.runtime.contracts import RunDecision, RuntimeInput
except ImportError:
    from core.artifact import validate
    from core.interaction_policy import (
        INTERACTION_POLICY_VERSION,
        InteractionContext,
        InteractionGate,
        InteractionPolicySettings,
        ReplyStyle,
        decide_interaction,
    )
    from core.relationship import RelationshipSnapshot, snapshot_from_payload
    from app.ports import ArtifactCache
    from app.runtime.contracts import RunDecision, RuntimeInput


class RelationshipReader:
    """Resolve one validated active relationship from the derived Artifact cache."""

    def __init__(self, cache: ArtifactCache | None) -> None:
        self.cache = cache

    def get(self, subject_id: str) -> RelationshipSnapshot:
        subject = str(subject_id or "").strip()
        if not subject or self.cache is None:
            return RelationshipSnapshot(subject_id=subject)
        try:
            rows = [
                art
                for art in self.cache.by_subject(subject)
                if art.header.family == "relationship"
                and art.header.state == "active"
            ]
            if len(rows) != 1:
                return RelationshipSnapshot(subject_id=subject)
            art = rows[0]
            validate(art)
            return snapshot_from_payload(
                art.payload,
                subject_id=subject,
                artifact_id=art.header.id,
                revision=art.header.revision,
            )
        except Exception:  # noqa: BLE001 - corrupt relationship data is neutral
            return RelationshipSnapshot(subject_id=subject)

class RelationshipInteractionPolicy:
    """Adapt relationship snapshots to Runtime's generic interaction port."""

    version = INTERACTION_POLICY_VERSION

    def __init__(
        self,
        reader: RelationshipReader,
        settings: InteractionPolicySettings,
    ) -> None:
        self.reader = reader
        self.settings = settings

    def decide(
        self,
        event: RuntimeInput,
        decision: RunDecision,
        *,
        source_id: str = "",
    ) -> InteractionGate:
        if self.settings.mode == "off":
            return InteractionGate(reason="relationship_off")
        snapshot = self.reader.get(event.speaker_id)
        must_reply = decision.must_reply
        if event.private:
            # A private message is not automatically a direct question.
            must_reply = bool(event.question or event.addressed or event.reply_to_me)
        elif event.question or event.addressed or event.reply_to_me:
            # Explicit questions and host direct signals must not be muted by
            # relationship state, including in group conversations.
            must_reply = True
        return decide_interaction(
            snapshot,
            InteractionContext(
                source_id=source_id,
                attention=decision.attention.value,
                private=event.private,
                must_reply=must_reply,
            ),
            self.settings,
        )

    @staticmethod
    def directive(gate: InteractionGate) -> str:
        return interaction_prompt(gate)


def settings_from_config(
    config: Callable[[str, Any], Any],
    warn: Callable[[str], None] = lambda _key: None,
) -> InteractionPolicySettings:
    """Normalize backend relationship mode and probabilities without user data."""
    mode = str(config("relationship_mode", "enforce") or "").strip().lower()
    if mode not in ("off", "observe", "enforce"):
        warn("relationship_mode")
        mode = "observe"

    def probability(key: str, default: float) -> float:
        invalid = False
        try:
            value = float(config(key, default))
        except (TypeError, ValueError):
            value = default
            invalid = True
        if not math.isfinite(value):
            value = default
            invalid = True
        clamped = max(0.0, min(1.0, value))
        if invalid or clamped != value:
            warn(key)
        return clamped

    return InteractionPolicySettings(
        mode=mode,
        low_private_reply_probability=probability(
            "relationship_low_private_reply_probability", 0.8
        ),
        dislike_private_reply_probability=probability(
            "relationship_dislike_private_reply_probability", 0.5
        ),
    )


_STYLE_DIRECTIVES = {
    ReplyStyle.CUTE: (
        "保持原有人格；语气亲近、活泼、适度可爱。可以公开表达自然关心和轻微玩笑。"
        "只有当前上下文或已注入内容明确提供名字或昵称时，才能使用亲昵称呼；不得编造称呼。"
        "不得暴露私人记忆、关系分数或内部判断，不得制造占有或排他暗示、虚构浪漫标签或敏感玩笑。"
    ),
    ReplyStyle.WARM: (
        "保持原有人格；语气友好、温暖、适度活泼，可以自然关心和延展话题。"
        "不要使用亲昵称呼，不要提及任何内部关系状态。"
    ),
    ReplyStyle.NEUTRAL: (
        "保持自然、平衡的默认语气；最多追加一个必要问题，不要提及任何内部关系状态。"
    ),
    ReplyStyle.COOL: (
        "使用冷静、简短、直接的语气；不主动延展、不追加社交性反问、不使用亲昵称呼。"
        "保持基本礼貌，不讽刺或羞辱对方。"
    ),
    ReplyStyle.MINIMAL: (
        "仅提供当前场景必须回答的内容；语气克制、礼貌、简短，不主动延展、不示好、不反问。"
    ),
}


def interaction_prompt(gate: InteractionGate) -> str:
    """Project an enforced gate into a fixed directive without relationship data."""
    if not gate.enforced:
        return ""
    directive = _STYLE_DIRECTIVES[gate.style]
    if gate.max_reply_chars is not None:
        directive += f" 社交性回复原则上不超过 {gate.max_reply_chars} 个中文字符。"
    directive += " 必要的安全信息、代码和操作步骤优先于社交性长度提示。"
    return "\n\n【当前交互方式】\n" + directive + "\n"
