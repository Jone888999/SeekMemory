"""Compatibility checks for the action extension to runtime_episodes."""

from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
import unittest

sys_path = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if sys_path not in sys.path:
    sys.path.insert(0, sys_path)

from store import open_store


class RuntimeActionMigrationTest(unittest.TestCase):
    def test_legacy_episode_rows_survive_action_metadata_migration(self) -> None:
        path = os.path.join(tempfile.mkdtemp(prefix="seekmem_migration_"), "memory.db")
        connection = sqlite3.connect(path)
        connection.execute(
            "CREATE TABLE runtime_episodes ("
            "id TEXT PRIMARY KEY, at TEXT NOT NULL, session_id TEXT NOT NULL, "
            "decision TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '', "
            "action TEXT NOT NULL DEFAULT '', delivered INTEGER NOT NULL DEFAULT 0, "
            "response_chars INTEGER NOT NULL DEFAULT 0, tool_calls TEXT NOT NULL DEFAULT '[]', "
            "outcome TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', "
            "user_source_id TEXT NOT NULL DEFAULT '', assistant_source_id TEXT NOT NULL DEFAULT '', "
            "run_id TEXT NOT NULL DEFAULT '')"
        )
        connection.execute(
            "INSERT INTO runtime_episodes(id, at, session_id, decision, reason, "
            "action, delivered, outcome, run_id) "
            "VALUES('old-episode', '2026-10-01T00:00:00+00:00', 's1', "
            "'reply', 'mention', 'reply', 1, 'ok', 'run-old')"
        )
        connection.commit()
        connection.close()

        db = open_store(path)
        try:
            columns = {
                row[1] for row in db.database.conn.execute(
                    "PRAGMA table_info(runtime_episodes)"
                )
            }
            self.assertTrue({"action_id", "action_kind", "action_status", "attempt"} <= columns)
            row = db.runtime_episodes.list("s1")[0]
            self.assertEqual(row["id"], "old-episode")
            self.assertEqual(row["run_id"], "run-old")
            self.assertIsNone(row["action_id"])
            self.assertEqual(row["action_status"], "")
            self.assertEqual(row["attempt"], 1)
            indexes = {
                item["name"] for item in db.database.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'index'"
                )
            }
            self.assertIn("idx_runtime_episodes_action_terminal", indexes)
            triggers = {
                item["name"] for item in db.database.conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }
            self.assertIn("trg_runtime_action_no_attempt_after_terminal", triggers)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
