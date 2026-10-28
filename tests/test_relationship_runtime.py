"""Pure relationship policy, adapter integration, Recall isolation, and manual revision tests."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.relationship_policy import (
    RelationshipInteractionPolicy,
    RelationshipReader,
    interaction_prompt,
    settings_from_config,
)
from app.runtime import AttentionLevel, RunDecision, RuntimeInput, WakeAction
from core.artifact import Lineage, make, revise
from core.graph import Graph
from core.interaction_policy import (
    AffectionScope,
    InteractionContext,
    InteractionPolicySettings,
    ReplyStyle,
    decide_interaction,
    stable_sample,
)
from core.relationship import RelationshipBand, RelationshipSnapshot
from core.source import Source
from recall.pipeline import build_block
from services.management_service import ManagementService
from store import open_store
from store.cache import Cache


def relationship_payload(band: str, affinity: float, confidence: float = 0.8):
    return {
        "summary": f"关系状态：{band}",
        "affinity": affinity,
        "confidence": confidence,
        "evidence_count": 4,
        "relation_band": band,
        "policy": {
            "version": "relationship-v1",
            "private_weight": 1.0,
            "group_weight": 0.5,
            "learning_rate": 0.25,
            "max_revision_delta": 0.1,
        },
    }


class FixedReader:
    def __init__(self, snapshot: RelationshipSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def get(self, subject_id: str) -> RelationshipSnapshot:
        self.calls += 1
        return self.snapshot


class InteractionPolicyTest(unittest.TestCase):
    def test_stable_sampling_is_repeatable_exact_at_bounds_and_distributed(self) -> None:
        first = stable_sample("source-1", 0.8)
        self.assertEqual(first, stable_sample("source-1", 0.8))
        self.assertFalse(stable_sample("source-1", 0.0))
        self.assertTrue(stable_sample("source-1", 1.0))
        self.assertTrue(stable_sample("", 0.01))
        low = sum(stable_sample(str(i), 0.8) for i in range(1000))
        dislike = sum(stable_sample(str(i), 0.5) for i in range(1000))
        self.assertTrue(760 <= low <= 840, low)
        self.assertTrue(450 <= dislike <= 550, dislike)

    def test_low_and_dislike_private_casual_use_configured_probability(self) -> None:
        for band, expected in (
            (RelationshipBand.LOW, 0.8),
            (RelationshipBand.DISLIKE, 0.5),
        ):
            with self.subTest(band=band):
                snapshot = RelationshipSnapshot("u1", -0.5, 0.8, 4, band)
                gate = decide_interaction(
                    snapshot,
                    InteractionContext("source-1", "private", True, False),
                )
                self.assertEqual(gate.reply_probability, expected)
                required = decide_interaction(
                    snapshot,
                    InteractionContext("source-1", "private", True, True),
                )
                self.assertEqual(required.reply_probability, 1.0)
                self.assertTrue(required.allow_reply)

    def test_group_ambient_denies_only_low_and_dislike(self) -> None:
        for band in RelationshipBand:
            snapshot = RelationshipSnapshot("u1", 0.0, 0.8, 4, band)
            ambient = decide_interaction(
                snapshot,
                InteractionContext("source", "ambient", False, False),
            )
            direct = decide_interaction(
                snapshot,
                InteractionContext("source", "direct", False, True),
            )
            self.assertEqual(
                ambient.allow_reply,
                band not in (RelationshipBand.LOW, RelationshipBand.DISLIKE),
            )
            self.assertTrue(direct.allow_reply)
            self.assertEqual(direct.reply_probability, 1.0)

    def test_close_allows_public_affection_and_safe_fixed_directive(self) -> None:
        snapshot = RelationshipSnapshot(
            "private-user-id", 0.8, 0.9, 9, RelationshipBand.CLOSE
        )
        gate = decide_interaction(
            snapshot,
            InteractionContext("source", "ambient", False, False),
        )
        prompt = interaction_prompt(gate)
        self.assertEqual(gate.style, ReplyStyle.CUTE)
        self.assertEqual(gate.affection_scope, AffectionScope.PUBLIC_ALLOWED)
        self.assertTrue(gate.allow_care_checkin)
        self.assertTrue(gate.allow_light_teasing)
        self.assertEqual(
            gate.allowed_proactive_kinds,
            ("daily_checkin", "meal_reminder", "goodnight"),
        )
        self.assertIn("名字或昵称", prompt)
        self.assertIn("不得暴露私人记忆", prompt)
        self.assertIn("代码和操作步骤优先", prompt)
        self.assertNotIn("private-user-id", prompt)
        self.assertNotIn("0.8", prompt)

    def test_runtime_config_normalizes_invalid_mode_and_probabilities(self) -> None:
        warnings = []
        values = {
            "relationship_mode": "invalid",
            "relationship_low_private_reply_probability": 2.0,
            "relationship_dislike_private_reply_probability": float("nan"),
        }
        settings = settings_from_config(
            lambda key, default: values.get(key, default), warnings.append
        )
        self.assertEqual(settings.mode, "observe")
        self.assertEqual(settings.low_private_reply_probability, 1.0)
        self.assertEqual(settings.dislike_private_reply_probability, 0.5)
        self.assertEqual(
            warnings,
            [
                "relationship_mode",
                "relationship_low_private_reply_probability",
                "relationship_dislike_private_reply_probability",
            ],
        )


class RelationshipAdapterPolicyTest(unittest.TestCase):
    def _snapshot(self, band: RelationshipBand) -> RelationshipSnapshot:
        return RelationshipSnapshot("u1", -0.6, 0.8, 5, band)

    def test_modes_preserve_runtime_decision_and_expose_candidate_gate(self) -> None:
        blocked_source = next(
            str(i) for i in range(1000) if not stable_sample(str(i), 0.8)
        )
        event = RuntimeInput("private", "hello", "u1", private=True)
        decision = RunDecision(
            WakeAction.REPLY,
            "private_message",
            attention=AttentionLevel.PRIVATE,
            must_reply=True,
        )
        off_reader = FixedReader(self._snapshot(RelationshipBand.LOW))
        off_policy = RelationshipInteractionPolicy(
            off_reader, InteractionPolicySettings(mode="off")
        )
        off = off_policy.decide(event, decision, source_id=blocked_source)
        self.assertEqual(off_reader.calls, 0)
        self.assertFalse(off.enforced)

        observed = RelationshipInteractionPolicy(
            FixedReader(self._snapshot(RelationshipBand.LOW)),
            InteractionPolicySettings(mode="observe"),
        ).decide(event, decision, source_id=blocked_source)
        self.assertFalse(observed.allow_reply)
        self.assertFalse(observed.enforced)
        self.assertEqual(interaction_prompt(observed), "")

        enforced = RelationshipInteractionPolicy(
            FixedReader(self._snapshot(RelationshipBand.LOW)),
            InteractionPolicySettings(mode="enforce"),
        ).decide(event, decision, source_id=blocked_source)
        self.assertFalse(enforced.allow_reply)
        self.assertTrue(enforced.enforced)
        self.assertTrue(interaction_prompt(enforced))

    def test_private_required_is_derived_from_actual_host_signal_not_runtime_flag(self) -> None:
        policy = RelationshipInteractionPolicy(
            FixedReader(self._snapshot(RelationshipBand.DISLIKE)),
            InteractionPolicySettings(),
        )
        runtime_private = RunDecision(
            WakeAction.REPLY,
            "private_message",
            attention=AttentionLevel.PRIVATE,
            must_reply=True,
        )
        casual = policy.decide(
            RuntimeInput("p1", "hello", "u1", private=True),
            runtime_private,
            source_id="source-1",
        )
        question = policy.decide(
            RuntimeInput("p2", "why?", "u1", private=True, question=True),
            runtime_private,
            source_id="source-1",
        )
        direct = policy.decide(
            RuntimeInput("p3", "hello", "u1", private=True, addressed=True),
            runtime_private,
            source_id="source-1",
        )
        self.assertEqual(casual.reply_probability, 0.5)
        self.assertEqual(question.reply_probability, 1.0)
        self.assertEqual(direct.reply_probability, 1.0)

    def test_runtime_core_contains_no_relationship_semantics(self) -> None:
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(root, "app", "runtime", "runtime.py"), encoding="utf-8") as handle:
            source = handle.read()
        self.assertNotIn("relationship", source.lower())
        self.assertNotIn("InteractionGate", source)


class RelationshipRecallIsolationTest(unittest.TestCase):
    def test_low_and_close_snapshots_produce_identical_recall_result(self) -> None:
        db = open_store(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        graph = Graph(db.artifacts)
        source = Source(
            "s1", "t1", "bot:FriendMessage:u1", "u1", "user",
            "量化交易", "2026-10-26T12:00:00",
        )
        db.sources.append_sources([source])
        memory = make(
            "memory",
            {"text": "最近在复习量化交易", "level": "fact"},
            subject_id="u1",
            lineage=Lineage(sources=("s1",)),
        )
        db.artifacts.commit(
            memory, expected_revision=0, op="create", source_ids=("s1",)
        )
        cache.put(memory)
        relation = make(
            "relationship",
            relationship_payload("low", -0.3),
            subject_id="u1",
        )
        db.artifacts.commit(relation, expected_revision=0, op="create")
        cache.put(relation)
        args = (
            cache, graph, db.artifacts, db.sources, "bot:FriendMessage:u1",
            "还记得量化交易吗", True,
            {"bm25_enabled": False, "explore_rate": 0.0}.get,
            "bot:FriendMessage:u1", "u1",
        )
        low = build_block(*args, dry_run=True)
        cache.put(revise(relation, relationship_payload("close", 0.8)))
        close = build_block(*args, dry_run=True)
        self.assertEqual(low, close)


class RelationshipManualRevisionTest(unittest.TestCase):
    def test_generic_management_revision_changes_next_adapter_read_not_catalog(self) -> None:
        db = open_store(":memory:")
        self.addCleanup(db.close)
        cache = Cache(db.artifacts)
        relation = make(
            "relationship",
            relationship_payload("low", -0.3),
            subject_id="u1",
        )
        db.artifacts.commit(relation, expected_revision=0, op="create")
        cache.put(relation)
        service = ManagementService(
            artifacts=db.artifacts,
            sources=db.sources,
            ledger=db.ledger,
            cache=cache,
            recall_service=None,
        )
        self.assertEqual(service.catalog(), [])
        service.update({
            "id": relation.header.id,
            "expectedRevision": 1,
            "payload": relationship_payload("warm", 0.3),
            "scope": "private",
            "state": "active",
            "reason": "manual relationship correction",
            "confirmed": True,
        })
        got = RelationshipReader(cache).get("u1")
        self.assertEqual(got.revision, 2)
        self.assertEqual(got.band, RelationshipBand.WARM)
        self.assertEqual(service.catalog(), [])


if __name__ == "__main__":
    unittest.main()
