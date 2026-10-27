"""Deterministic runtime policy, worker and action-ledger load exercise.

Run with ``python benchmarks/runtime_load.py``. The benchmark uses fake clocks,
model and sender ports; it makes no network or model calls and prints a JSON
summary including p50/p95 decision latency and bounded queue/dispatch counts.
"""

from __future__ import annotations

import asyncio
import json
import os
import statistics
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.runtime import (  # noqa: E402
    ActionKind,
    ActionLedger,
    ActionStatus,
    AgentRuntime,
    DefaultProactivePolicy,
    InMemoryStateStore,
    RepoActionSink,
    RunContext,
    RunRecorder,
    RuntimeInput,
    RuntimeWorker,
    Scheduler,
    SessionState,
    plan_proactive_dispatch,
)
from store import open_store  # noqa: E402


SESSION_COUNT = 1000
EVENT_COUNT = 10000
TICK_CAP = 100
MAX_CONCURRENCY = 16
FAKE_NOW = 3_600_000.0


def _percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * fraction)))
    return ordered[index]


class _Model:
    def __init__(self, gate: asyncio.Event | None = None, start_at: int = 0) -> None:
        self.gate = gate
        self.start_at = start_at
        self.started = asyncio.Event()
        self.calls = 0
        self.active = 0
        self.max_active = 0

    async def complete(self, _session_id: str, *_args) -> str:
        self.calls += 1
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        if self.start_at and self.active >= self.start_at:
            self.started.set()
        try:
            if self.gate is not None:
                await self.gate.wait()
            else:
                await asyncio.sleep(0)
            return "synthetic reply"
        finally:
            self.active -= 1


class _Sender:
    def __init__(self) -> None:
        self.calls = 0

    async def send(self, _session_id: str, _text: str) -> bool:
        self.calls += 1
        await asyncio.sleep(0)
        return True


def _runtime(store, model: _Model, sender: _Sender) -> AgentRuntime:
    recorder = RunRecorder(
        sources=None,
        buffer=None,
        checkpoint=None,
        episodes=None,
        clock=lambda: FAKE_NOW,
    )
    return AgentRuntime(
        store,
        clock=lambda: FAKE_NOW,
        recorder=recorder,
        model_gateway=model,
        message_sender=sender,
    )


def _worker(
    runtime: AgentRuntime,
    store,
    session_ids,
    *,
    concurrency: int = MAX_CONCURRENCY,
) -> RuntimeWorker:
    return RuntimeWorker(
        runtime=runtime,
        scheduler=Scheduler(store),
        enabled=lambda: True,
        session_ids=session_ids,
        run_context=lambda session_id, _now: RunContext(
            session_id=session_id,
            text="synthetic input",
            source_id=f"source:{session_id}",
            run_id=f"run:{session_id}",
        ),
        interval_seconds=lambda: 1.0,
        max_attempts=lambda: 3,
        base_seconds=lambda: 2.0,
        max_concurrency=concurrency,
        clock=lambda: FAKE_NOW,
    )


async def _worker_load(session_ids: list[str]) -> dict[str, int]:
    # Hold the first 16 due sessions in flight, then overlap a second tick.
    # All duplicate dispatches must be rejected before any second model call.
    overlap_ids = session_ids[:MAX_CONCURRENCY]
    overlap_store = InMemoryStateStore()
    for session_id in overlap_ids:
        overlap_store.put(SessionState(session_id, wait_until=FAKE_NOW))
    gate = asyncio.Event()
    gated_model = _Model(gate, start_at=MAX_CONCURRENCY)
    gated_sender = _Sender()
    gated_runtime = _runtime(overlap_store, gated_model, gated_sender)
    overlap_worker = _worker(
        gated_runtime,
        overlap_store,
        lambda _limit: overlap_ids,
        concurrency=MAX_CONCURRENCY,
    )
    first_tick = asyncio.create_task(overlap_worker.tick(now=FAKE_NOW))
    await asyncio.wait_for(gated_model.started.wait(), timeout=5)
    duplicate_tick = await asyncio.wait_for(
        overlap_worker.tick(now=FAKE_NOW), timeout=5
    )
    gate.set()
    first_tick_dispatches = await asyncio.wait_for(first_tick, timeout=10)

    # Exercise a 100-session per-tick scan cap across all 1,000 sessions.
    batch_store = InMemoryStateStore()
    for session_id in session_ids:
        batch_store.put(SessionState(session_id, wait_until=FAKE_NOW))
    batch_model = _Model()
    batch_sender = _Sender()
    batch_runtime = _runtime(batch_store, batch_model, batch_sender)
    cursor = 0

    def next_sessions(limit: int) -> list[str]:
        nonlocal cursor
        batch = session_ids[cursor:cursor + limit]
        cursor += len(batch)
        return batch

    batch_worker = _worker(batch_runtime, batch_store, next_sessions)
    tick_dispatches = []
    for _ in range((len(session_ids) + TICK_CAP - 1) // TICK_CAP):
        tick_dispatches.append(await batch_worker.tick(now=FAKE_NOW))

    return {
        "overlap_first_tick_dispatches": first_tick_dispatches,
        "overlap_second_tick_dispatches": duplicate_tick,
        "overlap_duplicate_dispatches_suppressed": len(overlap_ids) - duplicate_tick,
        "overlap_model_calls": gated_model.calls,
        "overlap_max_concurrency": gated_model.max_active,
        "tick_cap": TICK_CAP,
        "tick_count": len(tick_dispatches),
        "tick_dispatches": sum(tick_dispatches),
        "tick_queue_depth_after_first": max(0, len(session_ids) - tick_dispatches[0]),
        "tick_max_concurrency": batch_model.max_active,
    }


def _action_load(path: str, action_count: int) -> dict[str, int]:
    db = open_store(path)
    repository = db.runtime_episodes
    ledger = ActionLedger(RepoActionSink(repository))
    restarts = 0
    duplicate_callbacks = 0
    last_attempted = None
    for index in range(action_count):
        session_id = f"session-{index % SESSION_COUNT:04d}"
        run_id = f"run-{index:05d}"
        callback_key = f"callback-{index:05d}"
        at = FAKE_NOW + index * (3600.0 / max(1, action_count - 1))
        attempted = ledger.begin(
            session_id=session_id,
            run_id=run_id,
            callback_key=callback_key,
            kind=ActionKind.TOOL_CALL,
            at=at,
        )
        duplicate_attempt = ledger.begin(
            session_id=session_id,
            run_id=run_id,
            callback_key=callback_key,
            kind=ActionKind.TOOL_CALL,
            at=at,
        )
        ledger.finish(attempted, ActionStatus.SUCCEEDED, at=at + 0.05)
        ledger.finish(attempted, ActionStatus.SUCCEEDED, at=at + 0.05)
        if duplicate_attempt.action_id == attempted.action_id:
            duplicate_callbacks += 2
        last_attempted = attempted
        if index + 1 == action_count // 2:
            db.close()
            db = open_store(path)
            repository = db.runtime_episodes
            ledger = ActionLedger(RepoActionSink(repository))
            restarts += 1
            # Replay one callback after restart; unique rows must remain stable.
            ledger.begin(
                session_id=session_id,
                run_id=run_id,
                callback_key=callback_key,
                kind=ActionKind.TOOL_CALL,
                at=at,
            )
            ledger.finish(last_attempted, ActionStatus.SUCCEEDED, at=at + 0.05)
            duplicate_callbacks += 2

    before_prune = int(repository.conn.execute(
        "SELECT COUNT(*) FROM runtime_episodes WHERE action_id IS NOT NULL"
    ).fetchone()[0])
    terminal_count = int(repository.conn.execute(
        "SELECT COUNT(*) FROM runtime_episodes WHERE action_id IS NOT NULL "
        "AND action_status IN ('succeeded', 'failed', 'cancelled')"
    ).fetchone()[0])
    repository.prune(retention_days=0, max_rows=5000)
    after_prune = int(repository.conn.execute(
        "SELECT COUNT(*) FROM runtime_episodes"
    ).fetchone()[0])
    db.close()
    return {
        "actions": action_count,
        "restart_count": restarts,
        "persisted_action_rows_before_prune": before_prune,
        "terminal_count_before_prune": terminal_count,
        "duplicate_callbacks": duplicate_callbacks,
        "rows_after_prune": after_prune,
        "retention_limit": 5000,
    }


def main() -> None:
    tracemalloc.start()
    session_ids = [f"session-{index:04d}" for index in range(SESSION_COUNT)]
    now = FAKE_NOW
    policy = DefaultProactivePolicy(
        enabled=True,
        cooldown_seconds=60.0,
        retry_seconds=10.0,
        max_attempts=3,
        ignored_streak_limit=3,
        ignored_backoff_seconds=30.0,
    )
    states = [
        SessionState(
            session_id,
            proactive_due_at=now - index % 120,
            last_seen_at=now - 100,
        )
        for index, session_id in enumerate(session_ids)
    ]

    inbound_runtime = AgentRuntime(InMemoryStateStore(), clock=lambda: now)
    inbound_latency_ms: list[float] = []
    proactive_latency_ms: list[float] = []
    for index in range(EVENT_COUNT):
        session_id = session_ids[index % SESSION_COUNT]
        event_now = now + index * (3600.0 / max(1, EVENT_COUNT - 1))
        event = RuntimeInput(
            session_id=session_id,
            text=f"synthetic event {index}",
            event_time=event_now,
            received_at=event_now,
        )
        started = time.perf_counter_ns()
        inbound_runtime.observe(event, now=event_now)
        inbound_latency_ms.append((time.perf_counter_ns() - started) / 1_000_000)

        state = states[index % SESSION_COUNT]
        started = time.perf_counter_ns()
        policy.evaluate(state, now=event_now)
        proactive_latency_ms.append((time.perf_counter_ns() - started) / 1_000_000)

    plan = plan_proactive_dispatch(
        states,
        policy,
        now=now,
        max_fanout=TICK_CAP,
    )
    if plan.eligible_count != SESSION_COUNT:
        raise AssertionError("proactive candidate count changed")
    if len(plan.selected) != TICK_CAP or len(plan.deferred) != SESSION_COUNT - TICK_CAP:
        raise AssertionError("proactive fan-out cap did not preserve queued sessions")
    worker_metrics = asyncio.run(_worker_load(session_ids))
    if worker_metrics["overlap_first_tick_dispatches"] != MAX_CONCURRENCY:
        raise AssertionError("overlapping tick did not dispatch its initial sessions")
    if worker_metrics["overlap_second_tick_dispatches"] != 0:
        raise AssertionError("overlapping tick dispatched an in-flight session twice")
    if worker_metrics["tick_dispatches"] != SESSION_COUNT:
        raise AssertionError("worker did not drain all capped batches")
    if worker_metrics["tick_max_concurrency"] > MAX_CONCURRENCY:
        raise AssertionError("worker exceeded its concurrency bound")

    with tempfile.TemporaryDirectory(prefix="seekmem_runtime_load_") as directory:
        action_metrics = _action_load(
            os.path.join(directory, "runtime.db"), EVENT_COUNT
        )
    if action_metrics["persisted_action_rows_before_prune"] != EVENT_COUNT * 2:
        raise AssertionError("duplicate action callbacks created unexpected rows")
    if action_metrics["terminal_count_before_prune"] != EVENT_COUNT:
        raise AssertionError("action ledger did not retain one terminal per action")
    if action_metrics["rows_after_prune"] > action_metrics["retention_limit"]:
        raise AssertionError("runtime action retention exceeded its row limit")

    _, peak_bytes = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    result = {
        "fake_clock_seconds": now,
        "fake_clock_soak_hours": 1,
        "sessions": SESSION_COUNT,
        "synthetic_events": EVENT_COUNT,
        "inbound_decision_latency_ms": {
            "p50": round(statistics.median(inbound_latency_ms), 4),
            "p95": round(_percentile(inbound_latency_ms, 0.95), 4),
        },
        "proactive_policy_latency_ms": {
            "p50": round(statistics.median(proactive_latency_ms), 4),
            "p95": round(_percentile(proactive_latency_ms, 0.95), 4),
        },
        "proactive_fanout": {
            "eligible": plan.eligible_count,
            "selected": len(plan.selected),
            "queue_depth_after_cap": len(plan.deferred),
            "cap": TICK_CAP,
        },
        "worker": worker_metrics,
        "action_ledger": action_metrics,
        "tracemalloc_peak_bytes": peak_bytes,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
