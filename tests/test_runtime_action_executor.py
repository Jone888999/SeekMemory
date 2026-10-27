"""Single action execution and audit coordinator."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime.actions import ActionExecutor, ActionLedger, ActionMessageSender
from app.runtime.contracts import ActionKind, ActionRequest, ActionResult, ActionStatus


class _Sink:
    def __init__(self):
        self.records = []

    def append(self, record):
        self.records.append(record)


class _Port:
    def __init__(self, result):
        self.result = result
        self.requests = []

    async def execute(self, request):
        self.requests.append(request)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class ActionExecutorTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_records_attempt_and_terminal(self):
        sink = _Sink()
        port = _Port(ActionResult(True))
        executor = ActionExecutor(port, ActionLedger(sink), clock=lambda: 10.0)

        result = await executor.execute(
            ActionRequest("s1", ActionKind.SEND_TEXT, text="secret"),
            run_id="run-1",
            callback_key="send-1",
        )

        self.assertTrue(result.ok)
        self.assertEqual([row.status for row in sink.records], [
            ActionStatus.ATTEMPTED, ActionStatus.SUCCEEDED,
        ])
        self.assertEqual([row.action_id for row in sink.records][0],
                         sink.records[1].action_id)
        self.assertNotIn("secret", str([row.__dict__ for row in sink.records]))

    async def test_failure_and_exception_have_content_free_terminals(self):
        for result, reason in (
            (ActionResult(False, "host_send_failed"), "host_send_failed"),
            (RuntimeError("private body"), "host_action_failed"),
        ):
            sink = _Sink()
            executor = ActionExecutor(
                _Port(result), ActionLedger(sink), clock=lambda: 10.0
            )
            action = await executor.execute(
                ActionRequest("s1", ActionKind.SEND_TEXT, text="private"),
                run_id="run-1",
                callback_key="send-2",
            )
            self.assertFalse(action.ok)
            self.assertEqual(action.reason, reason)
            self.assertEqual(sink.records[-1].status, ActionStatus.FAILED)
            self.assertNotIn("private", str([row.__dict__ for row in sink.records]))

    async def test_runtime_prefers_action_executor_for_text_send(self):
        from app.runtime import AgentRuntime, InMemoryStateStore

        class Executor:
            def __init__(self):
                self.calls = []

            async def execute(self, request, **kwargs):
                self.calls.append((request, kwargs))
                return ActionResult(True)

        executor = Executor()
        runtime = AgentRuntime(
            InMemoryStateStore(), action_executor=executor, clock=lambda: 10.0
        )
        self.assertTrue(await runtime._send_text(
            "s1", "hello", run_id="run-1", callback_key="send-1"
        ))
        self.assertEqual(executor.calls[0][0].kind, ActionKind.SEND_TEXT)
        self.assertEqual(executor.calls[0][1]["run_id"], "run-1")

    async def test_message_sender_is_a_send_text_view(self):
        port = _Port(ActionResult(True))
        sender = ActionMessageSender(port)
        self.assertTrue(await sender.send("s1", "hello"))
        self.assertEqual(port.requests[0].kind, ActionKind.SEND_TEXT)
        self.assertEqual(port.requests[0].text, "hello")


if __name__ == "__main__":
    unittest.main()
