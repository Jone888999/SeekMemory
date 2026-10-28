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
const python = process.env.PYTHON || (process.platform === 'win32' ? 'python' : 'python3');
const service = fileURLToPath(new URL('../../../scripts/runtime_http.py', import.meta.url));

test('real Python AgentRuntime serves the DSH runtime contract', { timeout: 15_000 }, async (t) => {
  const dir = mkdtempSync(path.join(tmpdir(), 'seekmemory-python-runtime-'));
  const child = spawn(python, [service, '--data-dir', dir, '--token', 'test-token'], {
    stdio: 'ignore', windowsHide: true,
  });
  const exited = new Promise((resolve) => child.once('exit', resolve));
  t.after(async () => { child.kill(); await exited; rmSync(dir, { recursive: true, force: true }); });
  const runtimePath = path.join(dir, 'runtime.json');
  let endpoint;
  for (let attempt = 0; attempt < 150; attempt += 1) {
    try { endpoint = JSON.parse(readFileSync(runtimePath, 'utf8')); break; } catch { await pause(20); }
  }
  assert.ok(endpoint, 'python service must create runtime.json');
  const { config } = normalize({ runtimePath, recallTimeoutMs: 2000, captureTimeoutMs: 2000 });
  const client = new KernelClient({ config });
  const bridge = new RuntimeBridge(client);
  t.after(() => bridge.stop());
  assert.equal((await client.health()).data.runtime_contract, 1);
  const accepted = await bridge.event('accept_user', 'owner', { input: fixture.input, event_id: 'event-1' });
  assert.equal(accepted.ok, true);
  assert.equal(accepted.data.decision.action, 'reply');
  assert.equal(accepted.data.decision.reason, 'direct_attention');
  assert.ok(accepted.data.source_id);
  const context = await bridge.context('owner', {
    sessionId: fixture.input.session_id, value: fixture.input.text,
  });
  assert.equal(context.ok, true);
  assert.equal(typeof context.data.text, 'string');
  assert.equal(typeof context.data.info, 'object');
});
