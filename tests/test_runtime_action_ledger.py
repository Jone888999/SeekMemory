"""Persisted action-ledger lifecycle and compatibility scenarios."""

from __future__ import annotations

from dataclasses import fields
import os
import sqlite3
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime.actions import ActionLedger, RepoActionSink, action_idempotency_key
from app.runtime.contracts import ActionKind, ActionStatus
from store import open_store
from store.runtime_episodes import RuntimeEpisodeRepository


class ActionLedgerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.path = os.path.join(tempfile.mkdtemp(prefix="seekmem_actions_"), "memory.db")
        self.db = open_store(self.path)
        self.addCleanup(self.db.close)
        self.repository = self.db.runtime_episodes
        self.ledger = ActionLedger(RepoActionSink(self.repository))

    def begin(self, callback_key: str, *, attempt: int = 1):
        return self.ledger.begin(
            session_id="session-1",
            run_id="run-1",
            callback_key=callback_key,
            kind=ActionKind.TOOL_CALL,
            at=100.0 + attempt,
            attempt=attempt,
        )

    def test_idempotency_key_is_stable_and_does_not_expose_callback_key(self) -> None:
        first = action_idempotency_key(
            "run-1", "tool-call-secret", ActionKind.TOOL_CALL,
            session_id="session-1",
        )
        duplicate = action_idempotency_key(
            "run-1", "tool-call-secret", ActionKind.TOOL_CALL,
            session_id="session-1",
        )
        different = action_idempotency_key(
            "run-1", "tool-call-2", ActionKind.TOOL_CALL,
            session_id="session-1",
        )
        different_session = action_idempotency_key(
            "run-1", "tool-call-secret", ActionKind.TOOL_CALL,
            session_id="session-2",
        )

        self.assertEqual(first, duplicate)
        self.assertNotEqual(first, different)
        self.assertNotEqual(first, different_session)
        self.assertNotIn("tool-call-secret", first)

    def test_duplicate_attempt_and_success_callback_persist_once_across_restart(self) -> None:
        attempted = self.begin("call-1")
        duplicate = self.begin("call-1")
        succeeded = self.ledger.finish(attempted, ActionStatus.SUCCEEDED, at=110.0)
        self.assertEqual(attempted.action_id, duplicate.action_id)

        self.db.close()
        self.db = open_store(self.path)
        self.addCleanup(self.db.close)
        self.repository = self.db.runtime_episodes
        self.ledger = ActionLedger(RepoActionSink(self.repository))
        self.ledger.finish(attempted, ActionStatus.SUCCEEDED, at=110.0)

        rows = self.repository.list_actions("session-1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["action_status"] == "succeeded" for row in rows), 1)
        self.assertEqual({row["action_id"] for row in rows}, {succeeded.action_id})
        self.assertTrue(all(row["run_id"] == "run-1" for row in rows))

    def test_only_one_terminal_outcome_is_kept_for_competing_callbacks(self) -> None:
        attempted = self.begin("call-2")
        self.ledger.finish(attempted, ActionStatus.FAILED, at=120.0, reason="TimeoutError")
        self.ledger.finish(attempted, ActionStatus.CANCELLED, at=121.0, reason="cancelled")

        rows = self.repository.list_actions("session-1")
        terminals = [row for row in rows if row["action_status"] in {
            "succeeded", "failed", "cancelled"
        }]
        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0]["action_status"], "failed")
        self.assertEqual(terminals[0]["reason"], "TimeoutError")

    def test_concurrent_terminal_callbacks_on_separate_connections_are_idempotent(self) -> None:
        attempted = self.begin("call-concurrent")
        barrier = threading.Barrier(2)
        errors: list[BaseException] = []
        connections = [
            sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            for _ in range(2)
        ]
        for connection in connections:
            connection.row_factory = sqlite3.Row
            self.addCleanup(connection.close)
        repositories = [
            RuntimeEpisodeRepository(SimpleNamespace(conn=connection))
            for connection in connections
        ]

        def finish(repository, status: ActionStatus) -> None:
            try:
                barrier.wait(timeout=5)
                ActionLedger(RepoActionSink(repository)).finish(
                    attempted,
                    status,
                    at=170.0,
                )
            except BaseException as exc:  # surface worker-thread failures to unittest
                errors.append(exc)

        threads = [
            threading.Thread(target=finish, args=(repositories[0], ActionStatus.FAILED)),
            threading.Thread(target=finish, args=(repositories[1], ActionStatus.CANCELLED)),
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=10)

        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        terminals = [
            row for row in self.repository.list_actions("session-1")
            if row["action_status"] in {"succeeded", "failed", "cancelled"}
        ]
        self.assertEqual(len(terminals), 1)

    def test_retry_attempts_share_action_id_and_have_one_terminal(self) -> None:
        first = self.begin("call-3", attempt=1)
        retry = self.begin("call-3", attempt=2)
        self.ledger.finish(retry, ActionStatus.SUCCEEDED, at=130.0)

        rows = self.repository.list_actions("session-1")
        self.assertEqual(len(rows), 3)
        self.assertEqual({row["action_id"] for row in rows}, {first.action_id})
        self.assertEqual(sorted(row["attempt"] for row in rows), [1, 2, 2])
        self.assertEqual(sum(row["action_status"] == "succeeded" for row in rows), 1)

    def test_only_successful_send_text_is_marked_delivered(self) -> None:
        records = []
        for index, kind in enumerate((
            ActionKind.SEND_TEXT,
            ActionKind.TOOL_CALL,
            ActionKind.HOST_ACTION,
        )):
            attempted = self.ledger.begin(
                session_id="session-1",
                run_id="run-1",
                callback_key=f"delivery-{index}",
                kind=kind,
                at=180.0 + index,
            )
            records.append(self.ledger.finish(
                attempted, ActionStatus.SUCCEEDED, at=190.0 + index
            ))

        rows = {
            row["action_id"]: row
            for row in self.repository.list_actions("session-1")
            if row["action_status"] == "succeeded"
        }

        self.assertEqual(rows[records[0].action_id]["delivered"], 1)
        self.assertEqual(rows[records[1].action_id]["delivered"], 0)
        self.assertEqual(rows[records[2].action_id]["delivered"], 0)

    def test_terminal_transition_requires_an_attempt(self) -> None:
        attempted = self.begin("call-4")
        terminal = self.ledger.finish(attempted, ActionStatus.CANCELLED, at=140.0)

        with self.assertRaises(ValueError):
            self.ledger.finish(terminal, ActionStatus.FAILED, at=141.0)

        self.begin("call-4", attempt=2)
        rows = self.repository.list_actions("session-1")
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(row["action_status"] == "attempted" for row in rows), 1)

    def test_records_have_no_message_or_tool_payload_fields(self) -> None:
        attempted = self.begin("call-5")
        self.ledger.finish(attempted, ActionStatus.FAILED, at=150.0, reason="error")
        self.repository.append_action({
            "action_id": "other-action",
            "action_kind": "host_action",
            "action_status": "attempted",
            "attempt": 1,
            "at": 151.0,
            "session_id": "session-1",
            "reason": "private message body must not persist",
        })

        fields_on_record = {field.name for field in fields(attempted)}
        self.assertFalse({"text", "prompt", "arguments", "result", "message"} & fields_on_record)
        rows = self.repository.list_actions("session-1")
        self.assertTrue(all(not ({"text", "prompt", "arguments", "result"} & row.keys())
                            for row in rows))
        unsafe_reason = next(row for row in rows if row["action_id"] == "other-action")
        self.assertEqual(unsafe_reason["reason"], "error")
        self.assertNotIn("private message body must not persist", {
            row["reason"] for row in rows
        })

    def test_episode_list_does_not_include_action_audit_rows(self) -> None:
        attempted = self.begin("call-list")
        self.ledger.finish(attempted, ActionStatus.SUCCEEDED, at=165.0)

        self.assertEqual(self.repository.list("session-1"), [])
        self.assertEqual(len(self.repository.list_actions("session-1")), 2)

    def test_pruning_bounds_action_history_with_existing_episode_retention(self) -> None:
        for index in range(4):
            attempted = self.begin(f"call-{index}")
            self.ledger.finish(attempted, ActionStatus.SUCCEEDED, at=160.0 + index)

        self.repository.prune(retention_days=0, max_rows=3)

        self.assertEqual(len(self.repository.list_actions()), 3)


if __name__ == "__main__":
    unittest.main()
