/** Stable DSH platform-adapter contract helpers. */
import { runtimeInput } from './runtime-bridge.js';

export const PLATFORM_CONTRACT_VERSION = 1;
function textOf(content) {
  if (typeof content === 'string') return content;
  if (!Array.isArray(content)) return '';
  return content.filter((b) => b && b.type === 'text' && typeof b.text === 'string')
    .map((b) => b.text).join('\n').trim();
}

export function platformEventToRuntimeInput(session, event, options = {}) {
  const meta = session?.meta ?? {};
  const data = event?.data ?? {};
  const receivedAt = options.receivedAt ?? (options.clock ? options.clock() : undefined);
  return runtimeInput({
    sessionId: String(session?.id ?? ''),
    value: textOf(data.content) || String(data.text ?? ''),
    speakerId: String(options.speakerId ?? data.speakerId ?? meta.speakerId ?? ''),
    privateChat: meta.private === true,
    mentioned: data.mentioned === true,
    addressed: data.addressed === true,
    replyToMe: data.reply_to_me === true || data.replyToMe === true,
    eventTime: event?.time ?? 0,
    receivedAt,
    scene: meta.scene,
    conversationId: meta.conversation_id ?? meta.conversationId,
    threadId: meta.thread_id ?? meta.threadId,
    selfId: meta.self_id ?? meta.selfId,
    role: String(options.role ?? data.role ?? meta.role ?? 'member'),
    eventId: String(data.id ?? ''),
  });
}

export function createPlatformAdapter(input) {
  const platform = String(input?.platform ?? "").trim();
  if (!platform) throw new TypeError('platform is required');
  if (typeof input?.toRuntimeInput !== 'function') throw new TypeError('toRuntimeInput must be a function');
  if (typeof input?.executeAction !== 'function') throw new TypeError('executeAction must be a function');
  const capabilities = {};
  for (const key of ["private", "mention", "replyTo", "forward", "hostAction"]) {
    capabilities[key] = input?.capabilities?.[key] === true;
  }
  return Object.freeze({
    platform,
    capabilities: Object.freeze(capabilities),
    toRuntimeInput: input.toRuntimeInput,
    executeAction: input.executeAction,
    subjectKey: typeof input.subjectKey === "function" ? input.subjectKey :
      (session) => String(session?.meta?.subject_key ?? session?.meta?.subjectKey ?? ""),
  });
}
