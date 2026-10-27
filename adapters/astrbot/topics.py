"""Memory-backed proactive topic candidates for AstrBot."""

from __future__ import annotations

try:
    from ...app.runtime.topics import TopicCandidate
except ImportError:  # standalone adapter imports
    from app.runtime.topics import TopicCandidate


class AstrBotTopicSource:
    """Use the existing Source-backed buffer projection as topic evidence."""

    def __init__(self, buffer) -> None:
        self.buffer = buffer

    def candidates(
        self, session_id: str, *, now: float, limit: int = 1
    ) -> list[TopicCandidate]:
        if limit <= 0 or self.buffer is None:
            return []
        try:
            groups = [
                rows
                for session, _topic_id, rows in self.buffer.topics()
                if str(session) == str(session_id)
            ]
        except Exception:  # noqa: BLE001 - source failure means no proactive
            return []
        candidates: list[TopicCandidate] = []
        for rows in reversed(groups):
            users = [
                row for row in rows
                if str(getattr(row, "role", "")) == "user"
                and str(getattr(row, "text", "") or "").strip()
            ]
            if not users:
                continue
            last = users[-1]
            memory_ids = tuple(
                str(getattr(row, "source_id", "") or "")
                for row in rows
                if str(getattr(row, "source_id", "") or "")
            )
            candidates.append(TopicCandidate(
                text=str(last.text).strip(),
                kind="unfinished_topic",
                score=0.0,
                memory_ids=memory_ids,
                reason="source_backed_pending_topic",
            ))
            if len(candidates) >= limit:
                break
        return candidates
