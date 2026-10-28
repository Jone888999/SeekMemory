# DSH Platform Adapter Contract

Platform plugins own their session/event objects and platform APIs.
SeekMemory owns the canonical RuntimeInput and action contract.

## Adapter interface

```js
createPlatformAdapter({
  platform: 'qq',
  capabilities: { private: true, mention: true, replyTo: true, forward: false },
  toRuntimeInput(session, event, options) { ... },
  executeAction(request) { ... },
})
```

## Host bridge

```js
const bridge = createHostBridge({ kernel, adapter, logger })
bridge.acceptUser(session, event)
bridge.context(session, request, event)
bridge.recordReply(session, event, data)
bridge.recordDelivery(session, event, data)
bridge.recordError(session, event, data)
bridge.executeAction(request)
```

## Rules

- DSH Session/Event stay opaque to SeekMemory.
- Platform plugins do not implement attention, proactive, memory, or action-terminal policy.
- HostBridge does not register DSH hooks; platform plugins own hook registration and disposal.
- ActionRequest text is transient execution input and never enters ActionRecord audit.
- `session_id` is the conversation lane; `subject_key` is the shared memory identity.
- Contract versions: `platform_contract=1`, `runtime_contract=1`.

See issue #150 and `test/platform-contract.mjs` / `test/host-bridge.mjs`.

## 中文摘要

平台插件只实现 `toRuntimeInput` 和 `executeAction`；`host-bridge` 负责 Runtime HTTP 调用、记忆上下文和稳定错误映射，不注册 DSH hook。`session_id` 是会话 lane，`subject_key` 是共享记忆主体。
