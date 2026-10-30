"""Bounded, read-only tree expansion after flat recall; never disclose or write here.

平面召回后的有界只读树扩展；不在此披露正文或写入。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

try:
    from ..core.domain.memory.artifact import Artifact
    from ..app.ports import ArtifactStore, SourceStore
except ImportError:
    from core.domain.memory.artifact import Artifact
    from app.ports import ArtifactStore, SourceStore


class TreeLookup(Protocol):
    """Existing TreeService read methods / 既有 TreeService 只读能力。"""

    def parent_id(self, node_id: str) -> str | None: ...
    def children(self, node_id: str) -> list[Artifact]: ...


@dataclass(frozen=True)
class TreeQueryResult:
    """Only IDs and counts leave this stage; content stays in the guarded pool / 仅返回编号和计数。"""

    ids: tuple[str, ...] = ()
    parents: int = 0
    children: int = 0
    siblings: int = 0
    rejected: dict[str, int] = field(default_factory=dict)

    def info(self) -> dict:
        """Return content-free diagnostics / 返回无正文诊断。"""
        return {"expanded": len(self.ids), "parents": self.parents,
                "children": self.children, "siblings": self.siblings,
                "rejected": dict(self.rejected)}


@dataclass(frozen=True)
class TreeQueryLimits:
    """Internal rollout limits; no user-facing configuration / 内部验证上限，非用户配置。"""

    anchors: int = 2
    depth: int = 3
    children: int = 6
    siblings: int = 2
    total: int = 8


def expand_tree(anchors: list[Artifact], eligible: list[Artifact], tree: TreeLookup,
                artifacts: ArtifactStore, sources: SourceStore,
                limits: TreeQueryLimits = TreeQueryLimits()) -> TreeQueryResult:
    """Expand valid, same-identity current memories in structural-priority order.

    在结构优先顺序下扩展仍有效且同身份的当前记忆。异常由调用方回退原召回。
    """
    pool = {art.header.id: art for art in eligible if art.header.family == "memory"}
    selected = {art.header.id for art in anchors}
    results: list[str] = []
    rejects: dict[str, int] = {}
    counts = {"parents": 0, "children": 0, "siblings": 0}
    bounded = anchors[:max(0, limits.anchors)]

    def reject(reason: str) -> None:
        rejects[reason] = rejects.get(reason, 0) + 1

    def accept(node_id: str, anchor: Artifact, role: str) -> bool:
        if not node_id or len(results) >= limits.total:
            return False
        art = pool.get(node_id)
        if art is None:
            reject("not_eligible")
            return False
        if (art.header.subject_id, art.header.scope) != (anchor.header.subject_id, anchor.header.scope):
            reject("identity")
            return False
        current = artifacts.get(node_id)
        if (current is None or current.header.revision != art.header.revision
                or current.header.state != "active"
                or (current.header.subject_id, current.header.scope) != (anchor.header.subject_id, anchor.header.scope)):
            reject("stale")
            return False
        evidence = tuple(current.header.lineage.sources)
        if not evidence or len(sources.sources_by_ids(list(evidence))) != len(set(evidence)):
            reject("evidence")
            return False
        if node_id not in selected:
            selected.add(node_id)
            results.append(node_id)
            counts[role] += 1
        return True

    first_parents: dict[str, str] = {}
    # Global phase order gives every anchor a chance at ancestors before details.
    # 全局阶段排序：先为每个锚点找祖先，再考虑细节及兄弟。
    for anchor in bounded:
        if len(results) >= limits.total or anchor.header.family != "memory":
            continue
        node_id = anchor.header.id
        seen = {node_id}
        for level in range(max(0, limits.depth)):
            parent = tree.parent_id(node_id)
            if not parent or parent in seen:
                if parent in seen:
                    reject("cycle")
                break
            seen.add(parent)
            if not accept(parent, anchor, "parents"):
                break  # Never traverse past an ineligible or ambiguous parent.
            if level == 0:
                first_parents[anchor.header.id] = parent
            node_id = parent
            if len(results) >= limits.total:
                break

    for anchor in bounded:
        if len(results) >= limits.total or anchor.header.family != "memory":
            continue
        queue = [(anchor.header.id, 0)]
        visited = {anchor.header.id}
        child_seen = 0
        while queue and child_seen < limits.children and len(results) < limits.total:
            current_id, level = queue.pop(0)
            if level >= limits.depth:
                continue
            for child in tree.children(current_id):
                if child_seen >= limits.children or len(results) >= limits.total:
                    break
                cid = child.header.id
                if cid in visited:
                    reject("cycle")
                    continue
                visited.add(cid)
                child_seen += 1
                if accept(cid, anchor, "children"):
                    queue.append((cid, level + 1))

    for anchor in bounded:
        first_parent = first_parents.get(anchor.header.id)
        if not first_parent or limits.siblings <= 0 or len(results) >= limits.total:
            continue
        sibling_seen = 0
        for sibling in tree.children(first_parent):
            if sibling_seen >= limits.siblings or len(results) >= limits.total:
                break
            if sibling.header.id == anchor.header.id:
                continue
            sibling_seen += 1
            accept(sibling.header.id, anchor, "siblings")

    return TreeQueryResult(tuple(results), counts["parents"], counts["children"],
                           counts["siblings"], rejects)
