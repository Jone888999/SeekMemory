"""开口策略的 AstrBot 胶水层（临时接线，等 #116 宿主适配落地后删除）。

职责只有三件：
1. 把宿主事件映射成 RuntimeInput；
2. 调 AttentionPolicy 得到 RunDecision；
3. 按结论放行 / stop_event，并注入场景提示。

额度状态复用运行时 SessionState（键为 ``umo#sender``），不新增表。
"""

from __future__ import annotations

import time

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter

from ..app.runtime.attention import (
    AttentionPolicy,
    quota_gate,
    thresholds_from_config,
)
from ..app.runtime.contracts import RunDecision, SessionState, WakeAction
from ..app.runtime.scene_hints import compose, time_window
from ..app.runtime.signals import Signals
from ..app.runtime.state import migrate_legacy_attention_quota
from .astrbot_event import to_runtime_input
from .astrbot_runtime import AstrBotRuntimeAdapter
from .astrbot_signals import AstrBotSignals

QUOTA_TTL = 900.0


class AttentionRuntimePolicy:
    """Expose AttentionPolicy through the AgentRuntime policy seam."""

    def __init__(self, policy: AttentionPolicy, signals_port: AstrBotSignals) -> None:
        self.policy = policy
        self.signals_port = signals_port

    def evaluate(self, event, state: SessionState, now: float) -> RunDecision:
        return self.policy.decide(
            event, state, self.signals_port.signals(event, state, now), now
        )


class AttentionHooks:
    """AstrBot 侧的策略胶水；不持有存储，全部走已有服务。"""

    # ---------------- 配置 ----------------
    def _attention_enabled(self) -> bool:
        try:
            return bool(self._c("attention_policy_enabled", True))
        except Exception:  # noqa: BLE001
            return False

    def _scene_hints_enabled(self) -> bool:
        try:
            return bool(self._c("scene_hints_enabled", True))
        except Exception:  # noqa: BLE001
            return False

    def _address_names(self) -> tuple[str, ...]:
        """可被叫的名字；配置逗号分隔，默认大肥鱼。"""
        try:
            raw = str(self._c("attention_address_names", "大肥鱼,肥鱼") or "")
        except Exception:  # noqa: BLE001
            raw = "大肥鱼,肥鱼"
        return tuple(part.strip() for part in raw.split(",") if part.strip())

    def _owner_id(self) -> str:
        try:
            umo = str(getattr(self, "owner_umo", "") or "")
            return umo.split(":")[-1] if umo else ""
        except Exception:  # noqa: BLE001
            return ""

    # ---------------- 信号 ----------------
    def _signals(self, mapped, state: SessionState) -> Signals:
        if getattr(self, "_signals_port", None) is None:
            self._signals_port = AstrBotSignals(self.cache, self.buffer)
        return self._signals_port.signals(mapped, state, time.time())

    # ---------------- 额度 ----------------
    def _quota_for(self, signals: Signals, policy: AttentionPolicy) -> int:
        """auto 模式按关系给额度；off/fixed 由配置覆盖。"""
        mode = str(self._c("stranger_quota_mode", "auto") or "auto")
        if mode == "off":
            return 0
        if mode.startswith("fixed:"):
            try:
                return max(0, int(mode.split(":", 1)[1]))
            except (TypeError, ValueError):
                return policy.stranger_quota(signals)
        return policy.stranger_quota(signals)

    def _gate_quota(
        self, mapped, event: AstrMessageEvent, decision, signals, policy
    ) -> bool:
        """返回是否放行；额度按 (会话, 说话人) 复用 SessionState。"""
        now = time.time()
        store = self.services.runtime.store
        key = self._quota_key(mapped)
        state = store.get(key)
        migrate_legacy_attention_quota(
            state, legacy_quota_record=("#" in key)
        )
        reset_at = float(state.attention_quota_reset_at or 0.0)
        if reset_at > 0.0 and reset_at <= now:
            state.attention_quota = 0
            state.attention_quota_reset_at = 0.0
        remaining = int(state.attention_quota or 0)
        result = quota_gate(
            action=decision.action,
            private=mapped.private,
            owner=mapped.is_owner,
            mentioned=mapped.mentioned,
            addressed=mapped.addressed,
            remaining=remaining,
            quota=self._quota_for(signals, policy),
        )
        if result.remaining != remaining or mapped.mentioned or mapped.addressed:
            state.attention_quota = max(0, int(result.remaining))
            if mapped.mentioned or mapped.addressed:
                state.attention_quota_reset_at = now + QUOTA_TTL
            state.last_seen_at = now
            store.put(state)
        return result.allow

    def _quota_key(self, mapped) -> str:
        return f"{mapped.session_id}#{mapped.speaker_id}"

    def _save_quota(self, mapped, remaining: int) -> None:
        try:
            store = self.services.runtime.store
            key = self._quota_key(mapped)
            state = store.get(key)
            state.attention_quota = max(0, int(remaining))
            state.last_seen_at = time.time()
            store.put(state)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[seekmemory] 额度记录失败：{type(exc).__name__}")

    def _runtime_decision(self, event, mapped, now: float):
        cached = AstrBotRuntimeAdapter.get_extra(
            event, "_seekmemory_attention_decision", None
        )
        if isinstance(cached, RunDecision):
            return cached
        decision = self.services.runtime.observe(mapped, now=now)
        AstrBotRuntimeAdapter.set_extra(
            event, "_seekmemory_attention_decision", decision
        )
        return decision

    # ---------------- 钩子 ----------------
    async def attention_gate(self, event: AstrMessageEvent) -> None:
        """在 AstrBot 唤醒之后、回复之前决定放行或停住。"""
        if not self.ready or not self._attention_enabled() or self.services is None:
            return
        if not self._may_observe(event):
            return
        try:
            mapped = to_runtime_input(
                event,
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                owner_id=self._owner_id(),
                names=self._address_names(),
            )
            if not mapped.text:
                return
            now = time.time()
            store = self.services.runtime.store
            decision = self._runtime_decision(event, mapped, now)
            state = store.get(mapped.session_id)
            signals = self._signals(mapped, state)
            policy = AttentionPolicy(thresholds_from_config(self._c))
            allowed = self._gate_quota(mapped, event, decision, signals, policy)
            state.last_action = decision.action.value
            state.last_reason = decision.reason
            store.put(state)
            self.journal.record(
                "attention",
                "reply" if allowed else "stop",
                decision.reason,
                context={
                    "scene": mapped.scene,
                    "role": mapped.role,
                    "relationship": round(signals.relationship, 2),
                    "relevance": round(signals.relevance, 2),
                },
            )
            if not allowed:
                event.stop_event()
        except Exception as exc:  # noqa: BLE001 - 策略失败不影响正常聊天
            logger.warning(f"[seekmemory] 开口策略失败（放行）：{type(exc).__name__}")

    async def inject_scene_hints(self, event: AstrMessageEvent, req) -> None:
        """把时间/身份/亲疏提示追加到系统提示，替代 persona_gate 的提示部分。"""
        if not self.ready or not self._scene_hints_enabled() or self.services is None:
            return
        try:
            mapped = to_runtime_input(
                event,
                session_id=str(getattr(event, "unified_msg_origin", "") or ""),
                owner_id=self._owner_id(),
                names=self._address_names(),
            )
            state = self.services.runtime.store.get(mapped.session_id)
            text = compose(mapped, self._signals(mapped, state), time.localtime().tm_hour)
            if text:
                req.system_prompt = (req.system_prompt or "") + "\n\n【场景】" + text + "\n"
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[seekmemory] 场景提示失败：{type(exc).__name__}")
