/** DSH host-side functions shared by platform plugins. */
import { RuntimeBridge } from './runtime-bridge.js';

function value(v, fallback = "") {
  return typeof v === 'string' ? v : fallback;
}

export function createHostBridge({ kernel, adapter, logger } = {}) {
  if (kernel == null || typeof kernel.runtimeEvent !== "function") {
    throw new TypeError("kernel runtime client is required");
  }
  if (adapter == null || typeof adapter.toRuntimeInput !== "function") {
    throw new TypeError("platform adapter is required");
  }
  const runtime = new RuntimeBridge(kernel);
  const subjectKey = (session, event) => {
    try {
      return String(adapter.subjectKey?.(session, event) ?? session?.meta?.subject_key ?? "");
    } catch {
      return "";
    }
  };
  async function acceptUser(session, event, options = {}) {
    try {
      const input = adapter.toRuntimeInput(session, event, options);
      return await runtime.event("accept_user", subjectKey(session, event), {
        input, event_id: value(input?.event_id),
      });
    } catch (error) {
      logger?.warn?.(`dsh-seekmemory acceptUser failed: ${error?.name ?? "Error"}`);
      return { ok: false, reason: "exception", attempted: false };
    }
  }

  async function context(session, request = {}, event = {}) {
    try {
      return await runtime.context(subjectKey(session, event), {
        ...request, sessionId: value(request.sessionId, String(session?.id ?? "")),
      });
    } catch (error) {
      return { ok: false, reason: "exception" };
    }
  }
  function record(kind, session, event, data = {}) {
    const p = data && typeof data === "object" ? data : {};
    return runtime.event(kind, subjectKey(session, event), {
      run_id: value(p.run_id), session_id: value(p.session_id, String(session?.id ?? "")),
      text: value(p.text), speaker_id: value(p.speaker_id), turn_id: value(p.turn_id),
      reply_to: value(p.reply_to), decision: value(p.decision), reason: value(p.reason),
      response_chars: Number(p.response_chars ?? 0), tool_calls: Array.isArray(p.tool_calls) ? p.tool_calls : [],
      user_source_id: value(p.user_source_id), assistant_source_id: value(p.assistant_source_id),
      read_through_seq: Number.isSafeInteger(p.read_through_seq) ? p.read_through_seq : undefined,
      error: value(p.error), recall_ids: Array.isArray(p.recall_ids) ? p.recall_ids : [],
    });
  }
  async function executeAction(request) {
    try {
      return await adapter.executeAction(request);
    } catch (error) {
      return { ok: false, reason: "host_action_failed" };
    }
  }
  return {
    acceptUser,
    applyDecision: runtime.applyDecision.bind(runtime),
    context,
    recordReply: (s, e, d) => record("record_reply", s, e, d),
    recordDelivery: (s, e, d) => record("record_delivery", s, e, d),
    recordError: (s, e, d) => record("record_error", s, e, d),
    executeAction,
    stop: () => runtime.stop(),
  };
}
