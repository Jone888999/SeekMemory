"""Caller-visible model and action ports against fake external hosts."""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from adapters.astrbot.actions import AstrBotActionPort  # noqa: E402
from adapters.astrbot.model import AstrBotModelGateway  # noqa: E402
from app.runtime import ActionKind, ActionRequest, ActionResult  # noqa: E402


class HostPortsTest(unittest.IsolatedAsyncioTestCase):
    async def test_send_and_execute_share_the_host_send_path(self):
        sent = []

        async def send(session, message):
            sent.append((session, message))

        port = AstrBotActionPort(SimpleNamespace(send_message=send), str)
        self.assertEqual(await port.execute(ActionRequest("s1", text="hello")), ActionResult(True))
        self.assertTrue(await port.send("s2", "world"))
        self.assertEqual(sent, [("s1", "hello"), ("s2", "world")])

    async def test_invalid_and_unsupported_requests_do_not_touch_host(self):
        async def send(*args):
            self.fail("invalid action reached host")

        port = AstrBotActionPort(SimpleNamespace(send_message=send), str)
        for request, reason in (
            (ActionRequest("s1", ActionKind.TOOL_CALL), "unsupported_action"),
            (ActionRequest("s1", ActionKind.HOST_ACTION), "unsupported_action"),
            (ActionRequest("", text="hello"), "missing_session"),
            (ActionRequest("s1", text="  "), "empty_message"),
        ):
            self.assertEqual(await port.execute(request), ActionResult(False, reason))

    async def test_host_false_exception_and_missing_api_have_safe_reasons(self):
        async def rejected(*args):
            return False

        async def broken(*args):
            raise RuntimeError("private body and credential")

        for context, reason in (
            (SimpleNamespace(send_message=rejected), "host_send_failed"),
            (SimpleNamespace(send_message=broken), "host_action_failed"),
            (SimpleNamespace(), "host_unavailable"),
        ):
            port = AstrBotActionPort(context, str)
            self.assertEqual(await port.execute(ActionRequest("s1", text="hello")),
                             ActionResult(False, reason))
            self.assertFalse(await port.send("s1", "hello"))

    async def test_cancellation_propagates_to_runtime_recovery(self):
        async def cancelled(*args):
            raise asyncio.CancelledError()

        port = AstrBotActionPort(SimpleNamespace(send_message=cancelled), str)
        with self.assertRaises(asyncio.CancelledError):
            await port.send("s1", "hello")

    async def test_model_gateway_uses_the_hosts_session_provider(self):
        calls = []

        async def text_chat(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(completion_text=" reply ")

        async def resolve(session):
            self.assertEqual(session, "s1")
            return SimpleNamespace(text_chat=text_chat)

        gateway = AstrBotModelGateway(SimpleNamespace(get_using_provider_async=resolve))
        self.assertEqual(await gateway.complete("s1", "question", "memory"), "reply")
        self.assertEqual(calls, [{"prompt": "question", "system_prompt": "memory"}])

    async def test_missing_model_provider_is_an_explicit_failure(self):
        async def resolve(session):
            return None

        gateway = AstrBotModelGateway(SimpleNamespace(get_using_provider_async=resolve))
        with self.assertRaisesRegex(RuntimeError, "^no_provider$"):
            await gateway.complete("s1", "question")


if __name__ == "__main__":
    unittest.main()
