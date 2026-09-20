from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


class CoverageStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class ExactCoverageRequirement:
    """One exact semantic obligation for bounded context compilation."""

    key: str
    subject: str
    predicate: str
    role: str = "essential_now"

    def __post_init__(self) -> None:
        if not self.key.strip():
            raise ValueError("coverage requirement key is required")
        if not self.subject.strip():
            raise ValueError("coverage requirement subject is required")
        if not self.predicate.strip():
            raise ValueError("coverage requirement predicate is required")
        if not self.role.strip():
            raise ValueError("coverage requirement role is required")


@dataclass(frozen=True, slots=True)
class ContextRequest:
    id: UUID
    query: str
    token_budget: int
    latency_budget_ms: int | None = None
    goal_ref: UUID | None = None
    task_ref: UUID | None = None
    coverage_requirements: tuple[str, ...] = ()
    known_at: datetime | None = None
    valid_at: datetime | None = None
    exact_requirements: tuple[ExactCoverageRequirement, ...] = ()

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.latency_budget_ms is not None and self.latency_budget_ms <= 0:
            raise ValueError("latency_budget_ms must be positive when provided")
        requirement_keys = [item.key for item in self.exact_requirements]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("exact coverage requirement keys must be unique")
        if self.known_at is not None:
            _require_aware(self.known_at, "known_at")
        if self.valid_at is not None:
            _require_aware(self.valid_at, "valid_at")


@dataclass(frozen=True, slots=True)
class ContextItem:
    ref_type: str
    ref_id: UUID
    role: str
    provenance_refs: tuple[UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class ContextProjection:
    id: UUID
    request_id: UUID
    snapshot_id: str
    canonical_frontier: str
    items: tuple[ContextItem, ...]
    coverage_status: CoverageStatus
    manifest_digest: str
    compiler_version: str
    conflict_refs: tuple[UUID, ...] = ()
    unresolved_gaps: tuple[str, ...] = ()
    omitted_refs: tuple[UUID, ...] = ()

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("snapshot_id is required")
        if not self.manifest_digest:
            raise ValueError("manifest_digest is required")
        if not self.compiler_version:
            raise ValueError("compiler_version is required")
