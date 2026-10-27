"""AstrBot memory-backed proactive topic source."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.astrbot.topics import AstrBotTopicSource  # noqa: E402


class AstrBotTopicSourceTest(unittest.TestCase):
    def test_candidates_use_pending_source_backed_topic(self) -> None:
        rows = [
            SimpleNamespace(role="user", text="昨天聊到一半的事", source_id="u1"),
            SimpleNamespace(role="assistant", text="嗯", source_id="a1"),
        ]
        buffer = SimpleNamespace(topics=lambda: [
            ("s1", "t1", rows),
            ("other", "t2", rows),
        ])
        source = AstrBotTopicSource(buffer)

        candidates = source.candidates("s1", now=100.0, limit=1)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].text, "昨天聊到一半的事")
        self.assertEqual(candidates[0].memory_ids, ("u1", "a1"))
        self.assertEqual(candidates[0].kind, "unfinished_topic")

    def test_missing_or_broken_buffer_fails_closed(self) -> None:
        self.assertEqual(AstrBotTopicSource(None).candidates("s1", now=100.0), [])
        broken = SimpleNamespace(topics=lambda: (_ for _ in ()).throw(RuntimeError()))
        self.assertEqual(AstrBotTopicSource(broken).candidates("s1", now=100.0), [])


if __name__ == "__main__":
    unittest.main()
