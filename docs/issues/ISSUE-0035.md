# ISSUE-0035 — Persona console and local seed catalogue

UI scope clarification (2026-10-27, revised): the user authorized a freely
rotatable 3D memory sphere, spatial category grouping, brighter breathing/ripple/flow
animation and expandable annotations, replacing the earlier layered constellations.
Rendering remains Canvas with perspective projection; no new runtime dependency.
The read-only lifecycle-log console stays in scope. Independent WebUI hosting,
authentication and multi-platform adapters remain outside this change.

本轮范围更新：按用户最新反馈，将分层星群替换为可绕轴旋转的立体记忆球，支持同类分组、
呼吸/波纹/流光及可展开信息框。使用 Canvas 三维投影，不新增运行依赖。只读日志控制台
保留；独立 WebUI、认证和多平台接入仍不在本轮范围内。

Latest visual revision: display the most recently updated 80 memories by default,
with 40/80/120 choices; filtering operates before this display cap. Grow the default
radius with density, illuminate facets only during a ripple/assembly, and assemble
a single-node left-to-right surface sweep on entry/refresh. The camera trails the
frontier, completes exactly one turn in 6.6 seconds and pulls back/recenters throughout
the same motion, with no final lateral correction. Explicit selection loads the
existing detail API; protected previews remain masked.

最新视觉调整：默认最近更新 80 条，可选 40/80/120 条；先筛选、后限制显示数量，默认
半径随数量增加。平时不铺色块，波纹/入场时短暂亮面；进入或刷新时依次构建点、线、
面与体；镜头略滞后于扩散前沿，在 6.6 秒内转完一整圈，同步拉远居中，末尾不再补横移；常态单路脉冲沿节点接力。点击展开时复用现有详情接口，受保护预览继续遮蔽。

Status: in progress; local implementation awaiting UI review and host acceptance.
Priority: P2. GitHub: [#82](https://github.com/NeverENG/SeekMemory/issues/82), [#83](https://github.com/NeverENG/SeekMemory/issues/83).

## Background

The current management tabs expose debugging tools but do not provide a persona-first overview or a safe way to browse and install the persona files introduced by #84/#85. Administrators must inspect raw data to understand persona changes, memory relationships and Dream results.

## Scope

A typed hash-routed console with home, persona timeline/studio, canvas memory map, impression cards, local persona catalogue, Dream journal and the existing trace/system tools. Seed browsing/import/update/remove uses a filesystem port; explicit installation delegates to `ManagementService.bootstrap_persona`. No Source admission, model call or second persona write path is introduced.

## Acceptance

- Authenticated, bounded projections and generated OpenAPI/Zod contracts.
- Private graph content masked; source inspection remains an explicit detail action.
- Seed install preserves the persona revision chain and rejects stale revisions.
- Local blueprint writes are atomic; replaced/removed packs retain recoverable copies.
- Two licensed bundled seeds, packaging validation and original local fish artwork.
- Hash deep links/back/forward, mobile layout, empty/loading/error states, 1,000-node/2,000-edge rendering evidence.
- Python layers, frontend checks/build and backend/frontend contract exchange pass.

## Boundaries and dependencies

#76 owns chat import; #77 owns favorability; #86 owns Dream synthesis/rollback services; this console consumes its existing rollback API with explicit comparison and confirmation. Chat import and favorability remain unavailable. No production deployment. The 2026-10-25 issue decision selects 2D canvas; the current implementation uses deterministic sphere geometry and perspective projection, not a force simulation. A development-only d3/Canvas versus WebGL comparison and the production choice are documented in PR-0035.

## 中文翻译

状态：实现中，等待界面审阅与真实宿主验收。关联 GitHub #82、#83，本地编号与 GitHub 编号不同。

现有管理面板偏向调试，缺少以人格为中心的概览，也没有安全浏览、安装人格文件的入口。本次增加首页、人格时间线/工作室、Canvas 星图、人物印象、人格商店、Dream 日志，保留轨迹和系统工具。

验收重点为接口认证与有界返回、隐私遮蔽、人格版本冲突保护、人格包原子写入与可恢复移除、素材许可与打包、移动布局与千节点性能、前后端契约和测试。聊天导入、好感度由其他 Issue 负责；回滚页面已接入上游接口，支持差异、原因、确认和刷新。本次不部署生产；渲染器原型对比和选择依据记录于 PR-0035。
