from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Mapping
from uuid import UUID


class ClaimRelationKind(str, Enum):
    SUPPORTS = "SUPPORTS"
    CORRECTS = "CORRECTS"
    SUPERSEDES = "SUPERSEDES"
    CONTRADICTS = "CONTRADICTS"
    REFINES = "REFINES"


@dataclass(frozen=True, slots=True)
class Event:
    id: UUID
    kind: str
    occurred_at: datetime
    recorded_at: datetime
    payload: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Evidence:
    id: UUID
    event_id: UUID
    source_ref: str
    captured_at: datetime
    digest: str | None = None


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


@dataclass(frozen=True, slots=True)
class ClaimRelation:
    id: UUID
    source_claim_id: UUID
    target_claim_id: UUID
    kind: ClaimRelationKind
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class ResolvedState:
    """Rebuildable materialized state; never the sole source of epistemic history."""

    subject: str
    predicate: str
    operative_claim_id: UUID | None
    value: Any
    snapshot_id: str
    computed_at: datetime
