"""Shared nonempty Node/Python wire examples checked against authoritative DTOs."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from adapters.astrbot_runtime import AstrBotRuntimeAdapter  # noqa: E402
from app.runtime import (  # noqa: E402
    ActionRequest, ActionResult, MemoryContext, MemoryContextRequest, RunDecision,
    RunResult, RuntimeInput, UserRunReceipt,
)
from app.runtime.recorder import RecordedReply  # noqa: E402

FIXTURE = json.loads((ROOT / "tests/fixtures/runtime_host.json").read_text(encoding="utf-8"))


class RuntimeHostContractTest(unittest.TestCase):
    def test_shared_examples_match_complete_public_dto_shapes(self):
        for key, dto in (
            ("input", RuntimeInput), ("context_request", MemoryContextRequest),
            ("context", MemoryContext), ("action_request", ActionRequest),
            ("action_result", ActionResult), ("reply", RecordedReply), ("run_result", RunResult),
        ):
            with self.subTest(key=key):
                self.assertEqual(asdict(dto(**FIXTURE[key])), FIXTURE[key])
        receipt = dict(FIXTURE["receipt"])
        receipt["decision"] = RunDecision(**receipt["decision"])
        self.assertEqual(asdict(UserRunReceipt(**receipt)), FIXTURE["receipt"])

    def test_astrbot_maps_the_same_event_as_the_node_example(self):
        data = FIXTURE["input"]
        event = SimpleNamespace(created_at=data["event_time"], is_private_chat=lambda: False,
                                is_at_or_wake_command=True)
        mapped = AstrBotRuntimeAdapter.from_event(
            event, data["text"], data["session_id"], data["speaker_id"],
            received_at=data["received_at"],
        )
        self.assertEqual(asdict(mapped), data)

    def test_malformed_host_times_and_counts_do_not_poison_runtime_state(self):
        for value in ("not-a-time", float("nan"), float("inf"), -1):
            event = SimpleNamespace(created_at=value, is_private_chat=lambda: False)
            mapped = AstrBotRuntimeAdapter.from_event(
                event, "hello", "session", "speaker", unread_count="bad", unread_seq=True,
            )
            self.assertEqual(mapped.event_time, 0)
            self.assertEqual((mapped.unread_count, mapped.unread_seq), (0, 0))


if __name__ == "__main__":
    unittest.main()
