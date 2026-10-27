# Renderer spike — development only

This standalone Vite page compares `d3-force@3.0.0 + Canvas 2D` with a minimal
WebGL geometry renderer using the **same settled d3 positions**. It is not an
application entry, production dependency or plugin asset. WebGL is a geometry
prototype, not a full graph library; it does not implement picking or touch.

To reproduce, install `d3-force@3.0.0` into an isolated temporary project (disable
install scripts), then copy the four minified UMD files from the installed
`d3-force`, `d3-quadtree`, `d3-dispatch`, and `d3-timer` packages into
`dashboard/node_modules/.tmp/renderer-spike-vendor/`. Each package uses ISC;
keep their notices when copying. Start `pnpm --dir dashboard dev`, open
`/tools/renderer-spike/index.html`, and click **Run 60 samples**.

The warm-up runs 10 frames. Sixty further frames measure CPU command submission
only, at 800×560 / DPR 1. Timings do not include GPU completion, React, data
fetching or pointer-event latency. Browser timing precision can report zero for
WebGL; zero does not mean free rendering. Canvas backing bytes and WebGL vertex
bytes describe different resources and are **not** total process/GPU memory.

## Result and decision (2026-10-26)

See `result-2026-10-26.json` for raw output. On the local Mac / in-app Chromium 156:

| Work                   |  Median |    P95 |     Max |
| ---------------------- | ------: | -----: | ------: |
| d3 force tick          |  2.7 ms | 3.4 ms | 14.5 ms |
| Canvas draw submission |  0.7 ms | 0.8 ms |  1.0 ms |
| WebGL draw submission  | <0.1 ms | 0.1 ms |  0.2 ms |

The four d3 UMD bundles total 17,427 raw / 6,972 separately-gzipped bytes.
Neither d3 nor a WebGL dependency is added to production. The selected canvas
uses deterministic category clusters and redraws only on input/data/resize;
there is no ongoing force simulation. It remains well within an 8 ms drawing
budget for the issue's 1k/2k target, supports the existing pointer hit testing,
and keeps keyboard access in a 30-row paginated DOM list. WebGL's lower CPU
submission cost does not presently justify shaders, context-loss handling,
picking buffers and separate label support. Revisit if measured draw time
exceeds the budget on supported hardware or the payload cap grows.

The production component in development mode was separately sampled over ten
zoom changes: 1.0–1.4 ms, bitmap allocation 3,325,440 bytes in that viewport.
Its instrumentation is guarded by `import.meta.env.DEV` and removed by Vite.
A 390×844 layout check had document scroll width 390px; desktop 1280px was also
inspected. Physical multi-touch and real-host performance remain acceptance
checks; these measurements are not advertised as end-to-end FPS.
