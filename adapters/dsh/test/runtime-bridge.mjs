import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { RuntimeBridge, eventEpoch, runtimeInput } from '../src/runtime-bridge.js';

const fixture = JSON.parse(readFileSync(new URL('../../../tests/fixtures/runtime_host.json', import.meta.url), 'utf8'));
const input = fixture.input;
const request = { sessionId: input.session_id, value: input.text, speakerId: input.speaker_id,
  mentioned: true, eventTime: input.event_time, receivedAt: input.received_at };

function kernel({ version = 1, gate = false, receipt = fixture.receipt } = {}) {
  const calls = [];
  return {
    calls,
    async health() { return { ok: true, data: { ...(version === null ? {} : { runtime_contract: version }), runtime_gate_enabled: gate } }; },
    async runtimeEvent(body) { calls.push(body); return { ok: true, data: body.kind === 'accept_user' ? receipt : { accepted: true } }; },
    async runtimeContext(body) { calls.push(body); return { ok: true, data: fixture.context }; },
  };
}

test('the same event maps to the complete Python RuntimeInput shape', () => {
  assert.deepEqual(runtimeInput(request), input);
  assert.equal(eventEpoch(10_000), 10);
  assert.equal(eventEpoch('1970-01-01T08:00:10+08:00'), 10);
  assert.equal(eventEpoch('1970-01-01T00:00:10Z'), 10);
  for (const value of [undefined, '1970-01-01T00:00:10', 'bad', Infinity, -1,
    '2026-02-30T00:00:00Z', '2026-02-28T24:00:00+08:00', '2026-02-28T23:00:00+25:00']) {
    assert.equal(eventEpoch(value), 0);
  }
  assert.equal(eventEpoch('1970-01-01T08:00:10.123456+08:00'), 10.123456);
});

test('receipt and context preserve identities, times and cursor without host extras', async () => {
  const host = kernel();
  const bridge = new RuntimeBridge(host);
  const accepted = await bridge.event('accept_user', 'owner', { input: { ...input, host_object: {} }, event_id: 'event-1', ignored: 'secret' });
  assert.deepEqual(accepted.data, fixture.receipt);
  assert.deepEqual(host.calls[0], { kind: 'accept_user', subject_key: 'owner', input, event_id: 'event-1' });
  const context = await bridge.context('owner', { ...request, sourceId: accepted.data.source_id, now: 13 });
  assert.deepEqual(context.data, fixture.context);
  assert.deepEqual(host.calls[1], { subject_key: 'owner', ...fixture.context_request });
  bridge.stop();
});

test('legacy and mismatched services never receive runtime mutations', async () => {
  for (const [version, reason] of [[null, 'runtime_unsupported'], [2, 'runtime_contract_mismatch']]) {
    const host = kernel({ version });
    const result = await new RuntimeBridge(host).event('accept_user', 'owner', { input });
    assert.equal(result.reason, reason);
    assert.equal(result.attempted, false);
    assert.equal(host.calls.length, 0);
  }
});

test('invalid receipts are attempted writes and must not cause legacy capture', async () => {
  for (const read_through_seq of [-1, true, '7']) {
    const host = kernel({ receipt: { ...fixture.receipt, read_through_seq } });
    const result = await new RuntimeBridge(host).event('accept_user', 'owner', { input });
    assert.equal(result.reason, 'invalid_runtime_receipt');
    assert.equal(result.attempted, true);
  }
});

test('delivery cursor and content-free action result are mapped without inferring success', async () => {
  const host = kernel();
  const bridge = new RuntimeBridge(host);
  await bridge.event('record_delivery', 'owner', { session_id: input.session_id, read_through_seq: 7, text: 'must not travel' });
  assert.deepEqual(host.calls[0], { kind: 'record_delivery', subject_key: 'owner', session_id: input.session_id, read_through_seq: 7 });
  const bad = await bridge.event('record_delivery', 'owner', { session_id: input.session_id, read_through_seq: true });
  assert.equal(bad.reason, 'invalid_runtime_event');
  await bridge.event('action_result', 'owner', { action_id: 'action-1', session_id: input.session_id,
    result: { ...fixture.action_result, text: 'secret' }, arguments: { secret: true } });
  assert.deepEqual(host.calls[1].result, fixture.action_result);
  assert.equal(host.calls[1].arguments, undefined);
  const invalid = await bridge.event('record_reply', 'owner', { session_id: input.session_id, text: { host: true } });
  assert.equal(invalid.reason, 'invalid_runtime_event');
});

test('only the server opt-in gate maps a wait decision into host rejection', async () => {
  const receipt = { ...fixture.receipt, decision: { ...fixture.receipt.decision, action: 'wait', must_reply: false } };
  const decision = { kind: 'enter', messages: [], usage: { total: 2 } };
  for (const gate of [false, true]) {
    const bridge = new RuntimeBridge(kernel({ gate, receipt }));
    await bridge.event('accept_user', 'owner', { input });
    assert.deepEqual(bridge.applyDecision(decision, receipt), gate ? { ...decision, kind: 'reject' } : decision);
    assert.deepEqual(bridge.applyDecision(decision, fixture.receipt), decision);
  }
});

test('stopping a bridge prevents late responses and further writes', async () => {
  const host = kernel();
  let resolve;
  const entered = new Promise((done) => { resolve = done; });
  let release;
  host.runtimeEvent = async () => { resolve(); return new Promise((done) => { release = done; }); };
  const bridge = new RuntimeBridge(host);
  const result = bridge.event('accept_user', 'owner', { input });
  await entered;
  bridge.stop();
  release({ ok: true, data: fixture.receipt });
  assert.equal((await result).reason, 'runtime_stopped');
  assert.equal((await bridge.event('accept_user', 'owner', { input })).attempted, false);
});
