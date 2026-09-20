from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from uuid import UUID


class CoverageStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT"


@dataclass(frozen=True, slots=True)
class ContextRequest:
    id: UUID
    query: str
    token_budget: int
    latency_budget_ms: int | None = None
    goal_ref: UUID | None = None
    task_ref: UUID | None = None
    coverage_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")


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
