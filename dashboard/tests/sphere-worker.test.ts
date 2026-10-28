import assert from "node:assert/strict"
import { test } from "node:test"
import { Window } from "happy-dom"
import { act, createElement, useEffect } from "react"
import { createRoot } from "react-dom/client"
import type { GraphSnapshot } from "../src/features/shell/model.ts"
import { loadGraph } from "../src/dev/load-fixtures.ts"
import { layoutSphere } from "../src/features/memory-graph/scene.ts"
import { useSphere } from "../src/features/memory-graph/views/use-sphere.ts"

void test("large layouts remain pending without blocking React, cancel on filters and recover from worker errors", async () => {
  const dom = new Window()
  const workers: BoundaryWorker[] = []
  let rejectWorker = false
  class BoundaryWorker {
    onmessage?: (event: {
      data: { sphere: ReturnType<typeof layoutSphere>; layoutMs: number }
    }) => void
    onerror?: () => void
    terminated = false
    graph?: GraphSnapshot
    constructor() {
      if (rejectWorker) throw new Error("Host blocked Worker")
      workers.push(this)
    }
    postMessage(graph: GraphSnapshot) {
      this.graph = graph
    }
    terminate() {
      this.terminated = true
    }
  }
  const globals = {
    window: dom,
    document: dom.document,
    Worker: BoundaryWorker,
    IS_REACT_ACT_ENVIRONMENT: true,
  }
  const previous = Object.getOwnPropertyDescriptors(globalThis)
  for (const [key, value] of Object.entries(globals))
    Object.defineProperty(globalThis, key, {
      configurable: true,
      writable: true,
      value,
    })
  let state: ReturnType<typeof useSphere> | undefined
  const createWorker = () => new Worker("test-layout")
  function Probe({ graph }: { graph: GraphSnapshot }) {
    const value = useSphere(graph, createWorker)
    useEffect(() => {
      state = value
    }, [value])
    return null
  }
  const root = createRoot(document.createElement("div")),
    graph = loadGraph()
  try {
    await act(async () => {
      root.render(createElement(Probe, { graph }))
    })
    assert.equal(state?.pending, true)
    assert.equal(state?.sphere.stars.length, 0)
    const first = workers[0]
    assert.ok(first)
    const changed = { ...graph, nodes: graph.nodes.slice(0, 200) }
    await act(async () => {
      root.render(createElement(Probe, { graph: changed }))
    })
    assert.equal(first.terminated, true)
    await act(async () => {
      first.onmessage?.({ data: { sphere: layoutSphere(graph), layoutMs: 20 } })
    })
    assert.equal(state?.pending, true)
    const second = workers[1]
    assert.ok(second)
    await act(async () => {
      second.onerror?.()
    })
    assert.equal(state?.pending, false)
    assert.match(state?.error ?? "", /列表/)
    await act(async () => {
      root.render(
        createElement(Probe, {
          graph: { ...graph, nodes: graph.nodes.slice(0, 40) },
        })
      )
    })
    assert.equal(state?.error, "")
    assert.equal(state?.sphere.stars.length, 40)
    assert.equal(second.terminated, true)
    rejectWorker = true
    await act(async () => {
      root.render(createElement(Probe, { graph }))
    })
    assert.equal(state?.pending, false)
    assert.match(state?.error ?? "", /列表/)
  } finally {
    await act(async () => root.unmount())
    await dom.happyDOM.close()
    for (const key of Object.keys(globals)) {
      const descriptor = previous[key]
      if (descriptor) Object.defineProperty(globalThis, key, descriptor)
      else Reflect.deleteProperty(globalThis, key)
    }
  }
})
