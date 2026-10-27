"""Production composition path for the AstrBot runtime worker."""

from __future__ import annotations

import logging
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
    f"{ROOT.name}.adapters.astrbot_plugin"
).AstrBotPlugin


class _Sources:
    def __init__(self, row):
        self.row = row
        self.calls = []

    def latest_user_source(self, session_id):
        self.calls.append(session_id)
        return self.row


class RuntimePluginContextTest(unittest.TestCase):
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


class _HostStar:
    def __init__(self, context, config):
        pass


class _HostedPlugin(AstrBotPlugin, _HostStar):
    """Supply the Star base that the production Main inherits from AstrBot."""


class ConsoleLifecycleTest(unittest.IsolatedAsyncioTestCase):
    """Exercise production composition against a minimal host boundary."""

    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.context = SimpleNamespace(registered_web_apis=[])

        async def provider(umo=None):
            return None

        def register(*route):
            self.context.registered_web_apis.append(route)

        self.context.get_using_provider_async = provider
        self.context.register_web_api = register
        self.web_module = patch.dict(sys.modules, {
            "astrbot.api.web": types.ModuleType("astrbot.api.web"),
        })
        self.web_module.start()
        self.addCleanup(self.web_module.stop)
        self.plugin = _HostedPlugin(self.context, {
            "db_path": str(Path(self.temp.name) / "memory.db"),
        })
        self.addAsyncCleanup(self.plugin.stop)

    async def test_restart_preserves_console_packs_and_dream_history(self):
        await self.plugin.start()
        self.assertTrue(self.plugin.ready)
        self.assertEqual(len(self.context.registered_web_apis), 1)
        before = self.plugin.services.management_service.pack_catalog()
        self.assertGreater(len(before["items"]), 0)
        self.plugin.store.dreams.begin("2026-10-28")
        self.plugin.store.dreams.finish("2026-10-28", status="done", summary={})
        history = self.plugin.services.management_service.dream_journal()
        self.assertEqual(len(history["items"]), 1)

        await self.plugin.stop()
        self.assertFalse(self.plugin.ready)
        self.assertEqual(self.context.registered_web_apis, [])
        await self.plugin.start()
        self.assertTrue(self.plugin.ready)
        self.assertEqual(len(self.context.registered_web_apis), 1)
        management = self.plugin.services.management_service
        self.assertEqual(management.pack_catalog(), before)
        self.assertEqual(management.dream_journal(), history)

    async def test_registration_failure_allows_retry_with_console_services(self):
        with patch.object(self.context, "register_web_api", side_effect=RuntimeError("host unavailable")):
            with self.assertRaises(RuntimeError):
                await self.plugin.start()
        self.assertFalse(self.plugin.ready)
        self.assertIsNone(self.plugin.store)
        self.assertEqual(self.context.registered_web_apis, [])

        await self.plugin.start()
        self.assertTrue(self.plugin.ready)
        management = self.plugin.services.management_service
        self.assertGreater(len(management.pack_catalog()["items"]), 0)
        self.assertEqual(management.dream_journal()["items"], [])
        self.assertEqual(len(self.context.registered_web_apis), 1)


if __name__ == "__main__":
    unittest.main()
