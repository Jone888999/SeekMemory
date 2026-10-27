import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as pause } from 'node:timers/promises';
import test from 'node:test';
import { normalize } from '../src/config.js';
import { KernelClient } from '../src/kernel-client.js';
import { RuntimeBridge } from '../src/runtime-bridge.js';

const fixture = JSON.parse(readFileSync(new URL('../../../tests/fixtures/runtime_host.json', import.meta.url), 'utf8'));

test('authenticated loopback smoke against the executable mock contract', { timeout: 15_000 }, async (t) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'seekmemory-runtime-smoke-'));
  const child = spawn(process.execPath, [fileURLToPath(new URL('../mock/kernel.mjs', import.meta.url)), '--data-dir', dir],
    { env: { ...process.env, MOCK_RUNTIME: '1' }, stdio: 'ignore', windowsHide: true });
  const exited = new Promise((resolve) => child.once('exit', resolve));
  t.after(async () => { child.kill(); await exited; rmSync(dir, { recursive: true, force: true }); });
  const runtimePath = path.join(dir, 'runtime.json');
  let endpoint;
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try { endpoint = JSON.parse(readFileSync(runtimePath, 'utf8')); break; } catch { await pause(10); }
  }
  assert.ok(endpoint, 'mock must create its runtime file');
  const { config } = normalize({ runtimePath, recallTimeoutMs: 1000, captureTimeoutMs: 1000 });
  const client = new KernelClient({ config });
  const bridge = new RuntimeBridge(client);
  t.after(() => bridge.stop());
  assert.equal((await client.health()).data.runtime_contract, 1);
  const accepted = await bridge.event('accept_user', 'owner', { input: fixture.input, event_id: 'event-1' });
  assert.deepEqual(accepted.data, fixture.receipt);
  const reply = await bridge.event('record_reply', 'owner', {
    session_id: fixture.input.session_id, text: '你好', turn_id: fixture.receipt.turn_id,
    reply_to: fixture.receipt.source_id, run_id: 'run-1',
  });
  assert.deepEqual(reply.data, fixture.reply);
  for (const [kind, data] of [
    ['record_delivery', { read_through_seq: 7, assistant_source_id: 'assistant-source-1' }],
    ['record_error', { error: 'host_error' }],
    ['action_result', { action_id: 'action-1', result: fixture.action_result }],
  ]) assert.equal((await bridge.event(kind, 'owner', { session_id: fixture.input.session_id, ...data })).ok, true);
  const context = await bridge.context('owner', { sessionId: fixture.input.session_id, value: fixture.input.text });
  assert.deepEqual(context.data, fixture.context);
  const denied = await fetch(`http://127.0.0.1:${endpoint.port}/runtime/events`, {
    method: 'POST', body: '{}', signal: AbortSignal.timeout(1000),
  });
  assert.equal(denied.status, 401);
});
