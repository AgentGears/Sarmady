from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID

from sarmady.values import freeze_value


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class ClaimRelationKind(str, Enum):
    SUPPORTS = "SUPPORTS"
    CORRECTS = "CORRECTS"
    SUPERSEDES = "SUPERSEDES"
    CONTRADICTS = "CONTRADICTS"
    REFINES = "REFINES"


class ResolutionStatus(str, Enum):
    MISSING = "MISSING"
    RESOLVED = "RESOLVED"
    CONTESTED = "CONTESTED"


@dataclass(frozen=True, slots=True)
class Event:
    id: UUID
    kind: str
    occurred_at: datetime
    recorded_at: datetime
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not self.kind:
            raise ValueError("kind is required")
        _require_aware(self.occurred_at, "occurred_at")
        _require_aware(self.recorded_at, "recorded_at")
        if self.recorded_at < self.occurred_at:
            raise ValueError("recorded_at cannot precede occurred_at")
        object.__setattr__(self, "payload", freeze_value(self.payload))


@dataclass(frozen=True, slots=True)
class Evidence:
    id: UUID
    event_id: UUID
    source_ref: str
    captured_at: datetime
    digest: str | None = None

    def __post_init__(self) -> None:
        if not self.source_ref:
            raise ValueError("source_ref is required")
        _require_aware(self.captured_at, "captured_at")


@dataclass(frozen=True, slots=True)
class Claim:
    id: UUID
    subject: str
    predicate: str
    value: Any
    recorded_at: datetime
    evidence_refs: tuple[UUID, ...] = ()
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    derivation_ref: UUID | None = None

    def __post_init__(self) -> None:
        if not self.subject:
            raise ValueError("subject is required")
        if not self.predicate:
            raise ValueError("predicate is required")
        _require_aware(self.recorded_at, "recorded_at")
        if self.valid_from is not None:
            _require_aware(self.valid_from, "valid_from")
        if self.valid_to is not None:
            _require_aware(self.valid_to, "valid_to")
        if self.valid_from is not None and self.valid_to is not None and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        object.__setattr__(self, "value", freeze_value(self.value))


@dataclass(frozen=True, slots=True)
class ClaimRelation:
    id: UUID
    source_claim_id: UUID
    target_claim_id: UUID
    kind: ClaimRelationKind
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.source_claim_id == self.target_claim_id:
            raise ValueError("claim relation cannot point a claim to itself")
        _require_aware(self.recorded_at, "recorded_at")


@dataclass(frozen=True, slots=True)
class ResolvedState:
    """Rebuildable materialized interpretation over canonical claims and relations."""

    subject: str
    predicate: str
    status: ResolutionStatus
    operative_claim_id: UUID | None
    competing_claim_ids: tuple[UUID, ...]
    conflict_relation_ids: tuple[UUID, ...]
    value: Any
    snapshot_id: str
    computed_at: datetime
