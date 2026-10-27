"""Production composition path for the AstrBot runtime worker."""

from __future__ import annotations

import asyncio
import logging
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent))

# Importing the composition module must not require a live AstrBot install.
astrbot = types.ModuleType("astrbot")
api = types.ModuleType("astrbot.api")
api.logger = logging.getLogger("seekmemory-test")
api.star = SimpleNamespace(Context=object, Star=object)
event = types.ModuleType("astrbot.api.event")
event.AstrMessageEvent = object
event.filter = SimpleNamespace(
    EventMessageType=SimpleNamespace(ALL="all")
)
core = types.ModuleType("astrbot.core")
utils = types.ModuleType("astrbot.core.utils")
utils_path = types.ModuleType("astrbot.core.utils.astrbot_path")
utils_path.get_astrbot_plugin_data_path = lambda: str(ROOT / "data")
sys.modules.update({
    "astrbot": astrbot,
    "astrbot.api": api,
    "astrbot.api.event": event,
    "astrbot.core": core,
    "astrbot.core.utils": utils,
    "astrbot.core.utils.astrbot_path": utils_path,
})

import importlib  # noqa: E402
AstrBotPlugin = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot.plugin"
).AstrBotPlugin
AstrBotHooks = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot.hooks"
).AstrBotHooks
AttentionHooks = importlib.import_module(
    f"{ROOT.name}.adapters.astrbot.attention"
).AttentionHooks
ToolPolicy = importlib.import_module(f"{ROOT.name}.app.runtime").ToolPolicy


class _Sources:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def latest_user_source(self, session_id):
        self.calls.append(session_id)
        return self.row


class RuntimePluginContextTest(unittest.TestCase):
    def test_plugin_uses_explicit_host_composition(self):
        self.assertNotIn(AstrBotHooks, AstrBotPlugin.__mro__)
        self.assertNotIn(AttentionHooks, AstrBotPlugin.__mro__)

    def test_make_run_context_maps_source_event_and_receipt_time(self):
        plugin = object.__new__(AstrBotPlugin)
        plugin._self_id = "bot-1"
        plugin.store = SimpleNamespace(
            sources=_Sources({
                "id": "s1",
                "text": "hello",
                "at": "1970-01-01T00:00:10+00:00",
            })
        )

        context = plugin._make_run_context("umo:1", 123.5)

        self.assertEqual(context.session_id, "umo:1")
        self.assertEqual(context.text, "hello")
        self.assertEqual(context.source_id, "s1")
        self.assertEqual(context.bot_id, "bot-1")
        self.assertEqual(context.event_time, 10.0)
        self.assertEqual(context.received_at, 123.5)


class HostHookActionTest(unittest.TestCase):
    def test_tool_hooks_use_action_ledger_without_payload(self):
        class Ledger:
            def __init__(self):
                self.started = []
                self.finished = []

            def begin(self, **kwargs):
                self.started.append(kwargs)
                return SimpleNamespace(action_id="action-1")

            def finish(self, record, status, **kwargs):
                self.finished.append((record.action_id, status, kwargs))

        class Tracer:
            def run_id(self, event):
                return "run-1"

            def tool_begin(self, event, tool):
                pass

            def tool_end(self, event, tool):
                pass

        class Trace:
            def record(self, *args, **kwargs):
                pass

        class Event:
            unified_msg_origin = "umo:1"
            extras = {}

            def get_sender_id(self):
                return "sender-1"

            def get_extra(self, key, default=None):
                return self.extras.get(key, default)

            def set_extra(self, key, value):
                self.extras[key] = value

        hook = AstrBotHooks()
        hook.ready = True
        hook.services = SimpleNamespace(
            access_service=SimpleNamespace(
                may_observe=lambda session, sender: True,
                may_recall=lambda session, sender: True,
            )
        )
        hook.run_tracer = Tracer()
        hook.trace = Trace()
        hook.tool_policy = ToolPolicy(("memory_",))
        hook.action_ledger = Ledger()
        event = Event()
        tool = SimpleNamespace(name="memory_search", id="call-1")
        asyncio.run(hook.observe_tool(event, tool, {"query": "private"}))
        self.assertEqual(len(hook.action_ledger.started), 1)
        self.assertNotIn("private", str(hook.action_ledger.started[0]))
        asyncio.run(
            hook.observe_tool_result(
                event, tool, {}, SimpleNamespace(status="ok")
            )
        )
        self.assertEqual(len(hook.action_ledger.finished), 1)
        self.assertEqual(hook.action_ledger.finished[0][1].value, "succeeded")


if __name__ == "__main__":
    unittest.main()
