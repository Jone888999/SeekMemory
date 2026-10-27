"""Explicit attention quota state and legacy payload migration."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime import (
    JsonStateStore,
    SessionState,
    migrate_legacy_attention_quota,
)


class AttentionQuotaStateTest(unittest.TestCase):
    def test_new_quota_fields_preserve_existing_positional_constructor(self) -> None:
        state = SessionState(
            "session-1", 1, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0,
            8, 9, 10, 11,
        )

        self.assertEqual(state.unread_count, 8)
        self.assertEqual(state.last_unread_seq, 9)
        self.assertEqual(state.read_through_seq, 10)
        self.assertEqual(state.ignored_streak, 11)
        self.assertEqual(state.attention_quota, 0)

    def test_legacy_quota_moves_only_when_caller_identifies_quota_row(self) -> None:
        legacy = SessionState("session-1#speaker-1", unread_count=3)

        self.assertFalse(migrate_legacy_attention_quota(
            legacy, legacy_quota_record=False
        ))
        self.assertEqual(legacy.unread_count, 3)
        self.assertEqual(legacy.attention_quota, 0)

        self.assertTrue(migrate_legacy_attention_quota(
            legacy, legacy_quota_record=True
        ))
        self.assertEqual(legacy.unread_count, 0)
        self.assertEqual(legacy.attention_quota, 3)
        self.assertEqual(legacy.attention_quota_reset_at, 0.0)
        self.assertFalse(migrate_legacy_attention_quota(
            legacy, legacy_quota_record=True
        ))

    def test_explicit_quota_fields_round_trip_without_changing_unread_state(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_quota_state_"), "state.json")
        store = JsonStateStore(path)
        state = SessionState(
            "session-1#speaker-1",
            unread_count=0,
            attention_quota=2,
            attention_quota_reset_at=1200.0,
        )
        store.put(state)

        loaded = JsonStateStore(path).get(state.session_id)

        self.assertEqual(loaded.unread_count, 0)
        self.assertEqual(loaded.attention_quota, 2)
        self.assertEqual(loaded.attention_quota_reset_at, 1200.0)

    def test_normal_session_unread_count_remains_unread_count(self) -> None:
        state = SessionState("session-1", unread_count=4)

        migrated = migrate_legacy_attention_quota(
            state, legacy_quota_record=False
        )

        self.assertFalse(migrated)
        self.assertEqual(state.unread_count, 4)
        self.assertEqual(state.attention_quota, 0)


if __name__ == "__main__":
    unittest.main()
