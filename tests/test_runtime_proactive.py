"""Deterministic proactive scheduling policy scenarios."""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.runtime.contracts import SessionState
from app.runtime.proactive import DefaultProactivePolicy, plan_proactive_dispatch


class DefaultProactivePolicyTest(unittest.TestCase):
    def test_proactive_is_closed_by_default_even_when_due(self) -> None:
        state = SessionState("s1", proactive_due_at=100.0)

        decision = DefaultProactivePolicy().evaluate(state, now=100.0)

        self.assertFalse(decision.should_speak)
        self.assertEqual(decision.reason, "disabled")
        self.assertEqual(decision.due_at, 100.0)

    def test_waits_for_scheduled_due_time(self) -> None:
        policy = DefaultProactivePolicy(enabled=True)
        state = SessionState("s1", proactive_due_at=100.0)

        decision = policy.evaluate(state, now=99.0)

        self.assertFalse(decision.should_speak)
        self.assertEqual(decision.reason, "not_due")
        self.assertEqual(decision.due_at, 100.0)

    def test_quiet_window_moves_the_next_eligible_time(self) -> None:
        policy = DefaultProactivePolicy(enabled=True)
        state = SessionState("s1", proactive_due_at=100.0, quiet_until=130.0)

        decision = policy.evaluate(state, now=120.0)

        self.assertFalse(decision.should_speak)
        self.assertEqual(decision.reason, "quiet_window")
        self.assertEqual(decision.due_at, 130.0)

    def test_cooldown_blocks_until_after_the_last_proactive_action(self) -> None:
        policy = DefaultProactivePolicy(enabled=True, cooldown_seconds=60.0)
        state = SessionState(
            "s1", proactive_due_at=100.0, last_proactive_at=90.0
        )

        decision = policy.evaluate(state, now=120.0)

        self.assertFalse(decision.should_speak)
        self.assertEqual(decision.reason, "cooldown")
        self.assertEqual(decision.due_at, 150.0)

    def test_retry_delay_and_attempt_limit_are_deterministic(self) -> None:
        policy = DefaultProactivePolicy(
            enabled=True,
            retry_seconds=30.0,
            cooldown_seconds=0.0,
            max_attempts=2,
        )
        retry = SessionState(
            "s1", proactive_due_at=100.0, proactive_attempts=1,
            last_proactive_at=100.0,
        )

        waiting = policy.evaluate(retry, now=129.0)
        ready = policy.evaluate(retry, now=130.0)

        self.assertFalse(waiting.should_speak)
        self.assertEqual(waiting.reason, "retry_wait")
        self.assertEqual(waiting.due_at, 130.0)
        self.assertTrue(ready.should_speak)
        self.assertEqual(ready.reason, "retry_due")

        exhausted = SessionState(
            "s1", proactive_due_at=100.0, proactive_attempts=2,
            last_proactive_at=100.0,
        )
        capped = policy.evaluate(exhausted, now=1000.0)
        self.assertFalse(capped.should_speak)
        self.assertEqual(capped.reason, "max_attempts")
        self.assertEqual(capped.due_at, 0.0)

    def test_ignored_streak_applies_stable_exponential_backoff(self) -> None:
        policy = DefaultProactivePolicy(
            enabled=True,
            cooldown_seconds=0.0,
            ignored_streak_limit=2,
            ignored_backoff_seconds=10.0,
        )
        state = SessionState(
            "s1", proactive_due_at=100.0, last_seen_at=100.0,
            ignored_streak=3,
        )

        waiting = policy.evaluate(state, now=119.0)
        ready = policy.evaluate(state, now=120.0)

        self.assertFalse(waiting.should_speak)
        self.assertEqual(waiting.reason, "ignored_backoff")
        self.assertEqual(waiting.due_at, 120.0)
        self.assertTrue(ready.should_speak)
        self.assertEqual(ready.reason, "due")

    def test_policy_does_not_mutate_runtime_state(self) -> None:
        policy = DefaultProactivePolicy(enabled=True)
        state = SessionState(
            "s1", proactive_due_at=100.0, last_seen_at=90.0,
            last_proactive_at=80.0, proactive_attempts=1, ignored_streak=2,
        )
        before = vars(state).copy()

        policy.evaluate(state, now=200.0)

        self.assertEqual(vars(state), before)

    def test_invalid_time_fails_closed(self) -> None:
        policy = DefaultProactivePolicy(enabled=True)
        state = SessionState("s1", proactive_due_at=100.0)

        decision = policy.evaluate(state, now=float("nan"))

        self.assertFalse(decision.should_speak)
        self.assertEqual(decision.reason, "invalid_time")

    def test_fanout_cap_selects_oldest_due_and_leaves_queue_pending(self) -> None:
        policy = DefaultProactivePolicy(enabled=True, cooldown_seconds=0.0)
        states = [
            SessionState(f"s{index:04d}", proactive_due_at=1000.0 - index)
            for index in range(1000)
        ]

        plan = plan_proactive_dispatch(
            states,
            policy,
            now=2000.0,
            max_fanout=25,
        )

        self.assertEqual(plan.eligible_count, 1000)
        self.assertEqual(len(plan.selected), 25)
        self.assertEqual(len(plan.deferred), 975)
        self.assertEqual(
            [candidate.session_id for candidate in plan.selected[:3]],
            ["s0999", "s0998", "s0997"],
        )
        self.assertTrue(all(
            candidate.decision.should_speak
            for candidate in plan.selected + plan.deferred
        ))

    def test_fanout_plan_is_stable_for_same_candidates(self) -> None:
        policy = DefaultProactivePolicy(enabled=True, cooldown_seconds=0.0)
        states = [
            SessionState("later", proactive_due_at=150.0),
            SessionState("earlier", proactive_due_at=100.0),
            SessionState("later", proactive_due_at=120.0),
        ]

        first = plan_proactive_dispatch(
            states, policy, now=200.0, max_fanout=1
        )
        second = plan_proactive_dispatch(
            states, policy, now=200.0, max_fanout=1
        )

        self.assertEqual(first, second)
        self.assertEqual(first.selected[0].session_id, "earlier")
        self.assertEqual(len(first.deferred), 1)

    def test_fanout_cap_rejects_negative_values(self) -> None:
        with self.assertRaises(ValueError):
            plan_proactive_dispatch(
                [], DefaultProactivePolicy(enabled=True), now=0.0, max_fanout=-1
            )


if __name__ == "__main__":
    unittest.main()
