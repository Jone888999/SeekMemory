import assert from 'node:assert/strict';
import test from 'node:test';
import { createHostBridge } from '../src/host-bridge.js';
import { createPlatformAdapter } from '../src/platform-contract.js';

function fixture() {
  const calls = [];
  const kernel = {
    async health() { return { ok: true, data: { runtime_contract: 1, runtime_gate_enabled: false } }; },
    async runtimeEvent(payload) { calls.push(['event', payload]); return { ok: true, data: { accepted: true } }; },
    async runtimeContext(payload) { calls.push(['context', payload]); return { ok: true, data: { text: 'memory', info: {} } }; },
  };
  const adapter = createPlatformAdapter({
    platform: 'qq',
    toRuntimeInput: (session, event) => ({ session_id: session.id, text: event.data.text, event_id: event.data.id }),
    executeAction: async (request) => ({ ok: request.text === 'ok', reason: request.text === 'ok' ? '' : 'rejected' }),
  });
  return { calls, kernel, adapter };
}

test('host bridge routes one adapter into runtime events and context', async () => {
  const { calls, kernel, adapter } = fixture();
  const bridge = createHostBridge({ kernel, adapter });
  const session = { id: 'qq:group:1', meta: { subject_key: 'user:1' } };
  const event = { data: { id: 'msg-1', text: 'hello' } };
  await bridge.acceptUser(session, event);
  assert.equal(calls[0][1].kind, 'accept_user');
  assert.equal(calls[0][1].subject_key, 'user:1');
  assert.equal(calls[0][1].event_id, 'msg-1');
  const context = await bridge.context(session, { value: 'query' }, event);
  assert.equal(context.data.text, 'memory');
  assert.equal(calls[1][1].session_id, 'qq:group:1');
  await bridge.recordDelivery(session, event, { run_id: 'run-1', response_chars: 2 });
  assert.equal(calls[2][1].kind, 'record_delivery');
  assert.equal(calls[2][1].response_chars, 2);
  assert.deepEqual(await bridge.executeAction({ kind: 'send_text', text: 'ok' }), { ok: true, reason: '' });
  assert.deepEqual(await bridge.executeAction({ kind: 'send_text', text: 'no' }), { ok: false, reason: 'rejected' });
  bridge.stop();
});
