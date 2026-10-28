import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { createPlatformAdapter, platformEventToRuntimeInput } from '../src/platform-contract.js';
const qq = JSON.parse(readFileSync(new URL('./fixtures/platform-qq.json', import.meta.url), 'utf8'));
const bili = JSON.parse(readFileSync(new URL('./fixtures/platform-bilibili.json', import.meta.url), 'utf8'));

test('QQ and Bilibili events map to the same RuntimeInput shape', () => {
  const qqInput = platformEventToRuntimeInput(qq.session, qq.event, { receivedAt: qq.received_at });
  const biliInput = platformEventToRuntimeInput(bili.session, bili.event, { receivedAt: bili.received_at });
  assert.equal(qqInput.session_id, 'qq:group:12345');
  assert.equal(qqInput.scene, 'group');
  assert.equal(qqInput.addressed, true);
  assert.equal(qqInput.event_time, 1000);
  assert.equal(qqInput.received_at, 1001);
  assert.equal(biliInput.session_id, 'bilibili:video:BV1:comment:root1');
  assert.equal(biliInput.scene, 'comment');
  assert.equal(biliInput.conversation_id, 'BV1');
  assert.equal(biliInput.thread_id, 'root1');
  assert.equal(biliInput.reply_to_me, true);
  assert.equal(biliInput.received_at, 2001);
});

test('platform adapter freezes capabilities and keeps subject key host-owned', () => {
  const adapter = createPlatformAdapter({
    platform: 'qq', capabilities: { private: true, forward: true },
    toRuntimeInput: () => ({}), executeAction: async () => ({ ok: true, reason: '' }),
  });
  assert.equal(adapter.platform, 'qq');
  assert.equal(adapter.capabilities.private, true);
  assert.equal(adapter.capabilities.mention, false);
  assert.equal(adapter.subjectKey(qq.session), 'user:alice');
});
test('platform adapter rejects incomplete definitions', () => {
  assert.throws(() => createPlatformAdapter({ platform: 'qq' }), TypeError);
  assert.throws(() => createPlatformAdapter({ platform: 'qq', toRuntimeInput: () => ({}) }), TypeError);
});
