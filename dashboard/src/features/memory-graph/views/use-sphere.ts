import { useEffect, useMemo, useState } from "react"
import type { GraphSnapshot } from "../../shell/model.ts"
import { layoutSphere, type Sphere } from "../scene.ts"

const empty = layoutSphere({ nodes: [], edges: [], total: 0, limit: 1000 })
/** Large hulls run off the UI thread; a new filter cancels the previous job. */
export function useSphere(graph: GraphSnapshot, createWorker: () => Worker) {
  const small = useMemo(
    () => (graph.nodes.length <= 120 ? layoutSphere(graph) : null),
    [graph]
  )
  const [result, setResult] = useState<{
    graph: GraphSnapshot
    sphere: Sphere
    layoutMs: number
    error: string
  } | null>(null)
  useEffect(() => {
    if (graph.nodes.length <= 120) return
    let active = true
    let worker: Worker | undefined
    const fail = () => {
      if (active)
        setResult({
          graph,
          sphere: empty,
          layoutMs: 0,
          error: "星图布局失败，请切换数量重试；仍可通过寻找记忆查看列表。",
        })
    }
    try {
      worker = createWorker()
      worker.onmessage = (
        event: MessageEvent<{ sphere: Sphere; layoutMs: number }>
      ) => {
        if (active) setResult({ graph, ...event.data, error: "" })
      }
      worker.onerror = fail
      worker.postMessage(graph)
    } catch {
      // Restricted hosts can reject Worker construction before onerror is wired.
      fail()
    }
    return () => {
      active = false
      worker?.terminate()
    }
  }, [graph, createWorker])
  const current = result?.graph === graph ? result : null
  return {
    sphere: small ?? current?.sphere ?? empty,
    pending: !small && !current,
    error: small ? "" : (current?.error ?? ""),
    layoutMs: small ? 0 : (current?.layoutMs ?? 0),
  }
}
