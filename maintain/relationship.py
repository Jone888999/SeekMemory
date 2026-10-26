"""Dream-side relationship evidence validation and Artifact revisions."""

from __future__ import annotations

import math

try:
    from ..app.ports import ArtifactCache, ArtifactStore, SourceStore
    from ..core.artifact import Artifact, Lineage, make, revise, validate
    from ..core.relationship import (
        RELATIONSHIP_POLICY_VERSION,
        RelationshipSnapshot,
        relationship_id,
        snapshot_from_payload,
        summary_for,
    )
    from ..core.relationship_rules import (
        ConversationScope,
        RelationshipObservation,
        RelationshipReason,
        RelationshipScoringPolicy,
        RelationshipStrength,
        plan_relationship_revision,
    )
except ImportError:
    from app.ports import ArtifactCache, ArtifactStore, SourceStore
    from core.artifact import Artifact, Lineage, make, revise, validate
    from core.relationship import (
        RELATIONSHIP_POLICY_VERSION,
        RelationshipSnapshot,
        relationship_id,
        snapshot_from_payload,
        summary_for,
    )
    from core.relationship_rules import (
        ConversationScope,
        RelationshipObservation,
        RelationshipReason,
        RelationshipScoringPolicy,
        RelationshipStrength,
        plan_relationship_revision,
    )

_RESERVED_SUBJECTS = {"", "self", "relation", "world"}


def consolidate_relationships(
    artifacts: ArtifactStore,
    sources: SourceStore,
    cache: ArtifactCache,
    policy: RelationshipScoringPolicy = RelationshipScoringPolicy(),
) -> int:
    """Commit one bounded relationship revision per subject with fresh evidence."""
    current = _current_relationships(cache)
    candidates = _validated_observations(cache, sources, policy)
    made = 0
    for subject_id in sorted(candidates):
        existing = current.get(subject_id)
        if existing is False:
            continue
        snapshot = (
            snapshot_from_payload(
                existing.payload,
                subject_id=subject_id,
                artifact_id=existing.header.id,
                revision=existing.header.revision,
            )
            if isinstance(existing, Artifact)
            else RelationshipSnapshot(subject_id=subject_id)
        )
        previously_reviewed = (
            existing.header.lineage.derived_from
            if isinstance(existing, Artifact)
            else ()
        )
        observations = candidates[subject_id]
        created = {
            observation.artifact_id: artifact.header.time.created
            for observation, artifact in observations
        }
        plan = plan_relationship_revision(
            snapshot,
            (observation for observation, _artifact in observations),
            policy,
            previously_reviewed_artifact_ids=previously_reviewed,
            created_by_artifact_id=created,
        )
        if plan is None:
            continue
        replacement = _replacement(
            existing if isinstance(existing, Artifact) else None,
            subject_id,
            plan,
            policy,
        )
        validate(replacement)
        artifacts.commit(
            replacement,
            expected_revision=existing.header.revision if isinstance(existing, Artifact) else 0,
            op="revise" if isinstance(existing, Artifact) else "create",
            reason="relationship evidence consolidation",
            source_ids=plan.counted_source_ids,
        )
        cache.put(replacement)
        current[subject_id] = replacement
        made += 1
    return made


def _current_relationships(cache: ArtifactCache) -> dict[str, Artifact | bool]:
    grouped: dict[str, list[Artifact]] = {}
    for art in cache.active("relationship"):
        grouped.setdefault(str(art.header.subject_id or ""), []).append(art)
    out: dict[str, Artifact | bool] = {}
    for subject, rows in grouped.items():
        if subject in _RESERVED_SUBJECTS or len(rows) != 1:
            out[subject] = False
            continue
        art = rows[0]
        try:
            validate(art)
            snapshot_from_payload(
                art.payload,
                subject_id=subject,
                artifact_id=art.header.id,
                revision=art.header.revision,
            )
        except ValueError:
            out[subject] = False
            continue
        out[subject] = art
    return out


def _validated_observations(
    cache: ArtifactCache,
    sources: SourceStore,
    policy: RelationshipScoringPolicy,
) -> dict[str, list[tuple[RelationshipObservation, Artifact]]]:
    raw: list[tuple[Artifact, RelationshipReason, RelationshipStrength, float]] = []
    source_ids: list[str] = []
    for art in cache.active("memory"):
        subject = str(art.header.subject_id or "")
        if subject in _RESERVED_SUBJECTS or art.header.lineage.derived_from:
            continue
        if art.payload.get("relationship_policy_version") != RELATIONSHIP_POLICY_VERSION:
            continue
        try:
            reason = RelationshipReason(str(art.payload.get("relationship_reason") or ""))
            strength = RelationshipStrength(str(art.payload.get("relationship_strength") or ""))
        except ValueError:
            continue
        confidence = _confidence(art)
        if confidence < policy.minimum_evidence_confidence:
            continue
        ids = tuple(str(value) for value in art.header.lineage.sources if str(value))
        if not ids:
            continue
        raw.append((art, reason, strength, confidence))
        source_ids.extend(ids)

    originals = sources.sources_by_ids(list(dict.fromkeys(source_ids))) if source_ids else {}
    out: dict[str, list[tuple[RelationshipObservation, Artifact]]] = {}
    for art, reason, strength, confidence in raw:
        subject = str(art.header.subject_id or "")
        ids = tuple(str(value) for value in art.header.lineage.sources if str(value))
        rows = [originals.get(source_id) for source_id in ids]
        if any(row is None for row in rows):
            continue
        user_rows = [row for row in rows if row is not None and row.role == "user"]
        if not user_rows or any(row.speaker_id != subject for row in user_rows):
            continue
        scopes = {_scope_of(row.session_id) for row in rows if row is not None}
        if len(scopes) != 1:
            continue
        observation = RelationshipObservation(
            artifact_id=art.header.id,
            subject_id=subject,
            reason=reason,
            strength=strength,
            confidence=confidence,
            source_ids=ids,
            scope=next(iter(scopes)),
        )
        out.setdefault(subject, []).append((observation, art))
    return out


def _replacement(
    existing: Artifact | None,
    subject_id: str,
    plan,
    policy: RelationshipScoringPolicy,
) -> Artifact:
    payload = {
        "summary": summary_for(plan.band),
        "affinity": round(plan.affinity, 6),
        "confidence": round(plan.confidence, 6),
        "evidence_count": plan.evidence_count,
        "relation_band": plan.band.value,
        "policy": {
            "version": policy.version,
            "private_weight": policy.private_weight,
            "group_weight": policy.group_weight,
            "learning_rate": policy.learning_rate,
            "max_revision_delta": policy.max_revision_delta,
        },
    }
    old_sources = existing.header.lineage.sources if existing else ()
    old_derived = existing.header.lineage.derived_from if existing else ()
    lineage = Lineage(
        sources=tuple(dict.fromkeys((*old_sources, *plan.counted_source_ids))),
        derived_from=tuple(dict.fromkeys((
            *old_derived, *plan.reviewed_artifact_ids,
        ))),
    )
    if existing is not None:
        return revise(existing, payload=payload, lineage=lineage)
    return make(
        "relationship",
        payload,
        id=relationship_id(subject_id),
        subject_id=subject_id,
        scope="private",
        said_by="inferred",
        shareable="private_only",
        lineage=lineage,
    )


def _scope_of(session_id: str) -> ConversationScope:
    value = str(session_id or "")
    if ":FriendMessage:" in value:
        return ConversationScope.PRIVATE
    if ":GroupMessage:" in value:
        return ConversationScope.GROUP
    return ConversationScope.UNKNOWN


def _confidence(art: Artifact) -> float:
    value = art.header.strength.confidence
    if isinstance(value, bool):
        return 0.0
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return confidence if math.isfinite(confidence) and 0.0 <= confidence <= 1.0 else 0.0
