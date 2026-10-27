"""AstrBot implementation of runtime host actions."""

from __future__ import annotations

try:
    from ..app.runtime.contracts import ActionKind, ActionRequest, ActionResult
except ImportError:  # standalone adapter tests
    from app.runtime.contracts import ActionKind, ActionRequest, ActionResult


class AstrBotActionPort:
    """Send actions backed by the AstrBot host context."""

    def __init__(self, context, message_factory=None) -> None:
        self.context = context
        self.message_factory = message_factory

    def _chain(self, text: str):
        if self.message_factory is not None:
            return self.message_factory(text)
        from astrbot.core.message.message_event_result import MessageChain
        return MessageChain().message(text)

    async def execute(self, request: ActionRequest) -> ActionResult:
        if request.kind != ActionKind.SEND_TEXT:
            return ActionResult(False, "unsupported_action")
        if not request.session_id:
            return ActionResult(False, "missing_session")
        if not str(request.text or "").strip():
            return ActionResult(False, "empty_message")
        sender = getattr(self.context, "send_message", None)
        if not callable(sender):
            return ActionResult(False, "host_unavailable")
        try:
            result = await sender(request.session_id, self._chain(request.text))
        except Exception:  # host errors must not leak message bodies or credentials
            return ActionResult(False, "host_action_failed")
        return ActionResult(result is not False, "" if result is not False else "host_send_failed")

    async def send(self, session_id: str, text: str) -> bool:
        return (await self.execute(ActionRequest(session_id, text=text))).ok
