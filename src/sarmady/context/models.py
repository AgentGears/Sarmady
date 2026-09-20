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
    exact_requirements: tuple[ExactCoverageRequirement, ...] = ()
    known_at: datetime | None = None
    valid_at: datetime | None = None

    def __post_init__(self) -> None:
        # v5 inserted exact_requirements before the temporal fields. Pre-v5
        # positional callers therefore place known_at into this slot. Preserve
        # both public layouts by recognizing only the legacy datetime/None
        # shape and shifting it back into the temporal fields. This also
        # preserves the valid legacy mixed form where known_at was positional
        # and valid_at was supplied by keyword.
        raw_exact = self.exact_requirements
        if isinstance(raw_exact, datetime) or raw_exact is None:
            if self.known_at is not None and self.valid_at is not None:
                raise TypeError(
                    "ambiguous ContextRequest temporal arguments; use keywords"
                )
            legacy_known_at = raw_exact
            legacy_valid_at = (
                self.valid_at if self.valid_at is not None else self.known_at
            )
            object.__setattr__(self, "exact_requirements", ())
            object.__setattr__(self, "known_at", legacy_known_at)
            object.__setattr__(self, "valid_at", legacy_valid_at)

        if self.token_budget <= 0:
            raise ValueError("token_budget must be positive")
        if self.latency_budget_ms is not None and self.latency_budget_ms <= 0:
            raise ValueError("latency_budget_ms must be positive when provided")
        if not isinstance(self.exact_requirements, tuple) or any(
            not isinstance(item, ExactCoverageRequirement)
            for item in self.exact_requirements
        ):
            raise TypeError(
                "exact_requirements must be a tuple of ExactCoverageRequirement"
            )
        requirement_keys = [item.key for item in self.exact_requirements]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("exact coverage requirement keys must be unique")
        if self.known_at is not None:
            _require_aware(self.known_at, "known_at")
        if self.valid_at is not None:
            _require_aware(self.valid_at, "valid_at")


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """One derived semantic-key candidate for a context request.

    A candidate is relevance evidence only. It does not imply that a context
    requirement is satisfied, that the referenced claim should be adopted, or
    that the candidate should be written back into canonical memory.
    """

    subject: str
    predicate: str
    operative_claim_id: UUID
    score: int
    matched_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("candidate subject is required")
        if not self.predicate.strip():
            raise ValueError("candidate predicate is required")
        if self.score <= 0:
            raise ValueError("candidate score must be positive")
        if not self.matched_terms:
            raise ValueError("candidate matched_terms cannot be empty")
        if len(self.matched_terms) != len(set(self.matched_terms)):
            raise ValueError("candidate matched_terms must be unique")


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """Immutable snapshot-bound output from a candidate generator."""

    request_id: UUID
    snapshot_id: str
    canonical_frontier: str
    query_terms: tuple[str, ...]
    candidates: tuple[ContextCandidate, ...]
    generator_version: str

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("candidate snapshot_id is required")
        if not self.canonical_frontier:
            raise ValueError("candidate canonical_frontier is required")
        if not self.generator_version:
            raise ValueError("candidate generator_version is required")
        if len(self.query_terms) != len(set(self.query_terms)):
            raise ValueError("candidate query_terms must be unique")


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
