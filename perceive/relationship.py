"""Validate relationship observations proposed during extraction."""

from __future__ import annotations

from typing import Any, Mapping

try:
    from ..core.relationship_rules import (
        EVIDENCE_RULES,
        RelationshipReason,
        RelationshipStrength,
    )
except ImportError:
    from core.relationship_rules import (
        EVIDENCE_RULES,
        RelationshipReason,
        RelationshipStrength,
    )

SEPARATOR = "\x1d"


def reason_of(payload: Mapping[str, Any] | None) -> RelationshipReason | None:
    if not isinstance(payload, Mapping):
        return None
    try:
        return RelationshipReason(str(payload.get("relationship_reason") or "").strip())
    except ValueError:
        return None


def signal_of(payload: Mapping[str, Any] | None) -> str:
    """Return the program-derived signal for one validated reason."""
    reason = reason_of(payload)
    return EVIDENCE_RULES[reason].signal.value if reason is not None else ""


def is_relationship_observation(payload: Mapping[str, Any] | None) -> bool:
    return reason_of(payload) is not None


def validate_observation(payload: Mapping[str, Any] | None) -> None:
    """Reject partial, unknown, or model-scored relationship observations."""
    if not isinstance(payload, Mapping):
        raise ValueError("memory payload must be a mapping")
    if payload.get("relationship_signal") not in (None, ""):
        raise ValueError("relationship_signal is program-derived")
    raw_reason = payload.get("relationship_reason")
    raw_strength = payload.get("relationship_strength")
    if raw_reason in (None, "") and raw_strength in (None, ""):
        return
    try:
        RelationshipReason(str(raw_reason or "").strip())
    except ValueError as exc:
        raise ValueError(f"unknown relationship_reason: {raw_reason!r}") from exc
    try:
        RelationshipStrength(str(raw_strength or "").strip())
    except ValueError as exc:
        raise ValueError(f"unknown relationship_strength: {raw_strength!r}") from exc
    if str(payload.get("about") or "") != "relation":
        raise ValueError("relationship observation requires about=relation")


def observation_boundary(
    boundary: str,
    payload: Mapping[str, Any],
    evidence_ids: tuple[str, ...] | list[str],
) -> str:
    reason = reason_of(payload)
    evidence = "|".join(str(value) for value in evidence_ids if str(value))
    return f"{boundary}{SEPARATOR}{reason.value if reason else ''}{SEPARATOR}{evidence}"
