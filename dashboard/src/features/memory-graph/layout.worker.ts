import { layoutSphere } from "./scene"
import type { GraphSnapshot } from "../shell/model"

self.onmessage = (event: MessageEvent<GraphSnapshot>) => {
  const started = performance.now()
  const sphere = layoutSphere(event.data)
  self.postMessage({ sphere, layoutMs: performance.now() - started })
}
