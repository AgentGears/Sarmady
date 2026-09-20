from __future__ import annotations

import hashlib
import json
import math
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


class RequirementPlanStatus(str, Enum):
    RESOLVED = "RESOLVED"
    AMBIGUOUS = "AMBIGUOUS"
    ABSTAINED = "ABSTAINED"


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


def context_request_fingerprint(request: ContextRequest) -> str:
    """Bind a derived artifact to the complete ContextRequest semantics."""

    if not isinstance(request.query, str):
        raise TypeError("context request query must be a string")
    payload = {
        "contract": "ContextRequest:v1",
        "id": str(request.id),
        "query": request.query,
        "token_budget": request.token_budget,
        "latency_budget_ms": request.latency_budget_ms,
        "goal_ref": str(request.goal_ref) if request.goal_ref else None,
        "task_ref": str(request.task_ref) if request.task_ref else None,
        "coverage_requirements": list(request.coverage_requirements),
        "exact_requirements": [
            {
                "key": item.key,
                "subject": item.subject,
                "predicate": item.predicate,
                "role": item.role,
            }
            for item in request.exact_requirements
        ],
        "known_at": request.known_at.isoformat() if request.known_at else None,
        "valid_at": request.valid_at.isoformat() if request.valid_at else None,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ContextCandidate:
    """One derived semantic-key candidate for a context request.

    `rank_score` is generator-local and is not a calibrated probability or a
    value that may be compared across different generator versions. `signals`
    are optional diagnostic labels whose meaning is likewise generator-local.
    A candidate is relevance evidence only; it does not imply coverage,
    adoption, or memory admission.
    """

    subject: str
    predicate: str
    operative_claim_id: UUID
    rank_score: float
    signals: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.subject.strip():
            raise ValueError("candidate subject is required")
        if not self.predicate.strip():
            raise ValueError("candidate predicate is required")
        if (
            isinstance(self.rank_score, bool)
            or not isinstance(self.rank_score, (int, float))
            or not math.isfinite(float(self.rank_score))
        ):
            raise ValueError("candidate rank_score must be a finite number")

        if isinstance(self.signals, str):
            raise TypeError("candidate signals must be an iterable of strings")
        try:
            signals = tuple(self.signals)
        except TypeError as exc:
            raise TypeError("candidate signals must be an iterable of strings") from exc
        if any(not isinstance(signal, str) or not signal for signal in signals):
            raise TypeError("candidate signals must contain non-empty strings")
        if len(signals) != len(set(signals)):
            raise ValueError("candidate signals must be unique")
        object.__setattr__(self, "signals", signals)


@dataclass(frozen=True, slots=True)
class CandidateSet:
    """Immutable snapshot-bound output from a candidate generator.

    `is_exhaustive` means the generator knows that no additional candidate
    satisfying its own matching rule was dropped from this snapshot result.
    It does not mean the retrieval rule itself has perfect recall.
    """

    request_id: UUID
    snapshot_id: str
    canonical_frontier: str
    candidates: tuple[ContextCandidate, ...]
    generator_version: str
    request_fingerprint: str = ""
    is_exhaustive: bool = False

    def __post_init__(self) -> None:
        if not self.snapshot_id:
            raise ValueError("candidate snapshot_id is required")
        if not self.canonical_frontier:
            raise ValueError("candidate canonical_frontier is required")
        if not self.generator_version:
            raise ValueError("candidate generator_version is required")
        if self.request_fingerprint and not self.request_fingerprint.startswith("sha256:"):
            raise ValueError("candidate request_fingerprint must be a sha256 fingerprint")
        if not isinstance(self.is_exhaustive, bool):
            raise TypeError("candidate is_exhaustive must be bool")

        if isinstance(self.candidates, (str, bytes)):
            raise TypeError("candidates must be an iterable of ContextCandidate")
        try:
            candidates = tuple(self.candidates)
        except TypeError as exc:
            raise TypeError(
                "candidates must be an iterable of ContextCandidate"
            ) from exc
        if any(not isinstance(candidate, ContextCandidate) for candidate in candidates):
            raise TypeError("candidates must contain only ContextCandidate values")
        semantic_keys = [(candidate.subject, candidate.predicate) for candidate in candidates]
        if len(semantic_keys) != len(set(semantic_keys)):
            raise ValueError("candidate semantic keys must be unique")
        object.__setattr__(self, "candidates", candidates)


@dataclass(frozen=True, slots=True)
class RequirementPlan:
    """Derived, snapshot-bound proposal for exact information obligations."""

    source_request_id: UUID
    source_request_fingerprint: str
    candidate_snapshot_id: str
    canonical_frontier: str
    candidate_generator_version: str
    planner_version: str
    status: RequirementPlanStatus
    exact_requirements: tuple[ExactCoverageRequirement, ...] = ()
    selected_candidate_claim_ids: tuple[UUID, ...] = ()
    ambiguous_candidate_claim_ids: tuple[UUID, ...] = ()
    reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.source_request_fingerprint.startswith("sha256:"):
            raise ValueError("plan source_request_fingerprint is required")
        if not self.candidate_snapshot_id:
            raise ValueError("plan candidate_snapshot_id is required")
        if not self.canonical_frontier:
            raise ValueError("plan canonical_frontier is required")
        if not self.candidate_generator_version:
            raise ValueError("plan candidate_generator_version is required")
        if not self.planner_version:
            raise ValueError("plan planner_version is required")
        if not isinstance(self.status, RequirementPlanStatus):
            raise TypeError("plan status must be RequirementPlanStatus")

        requirements = tuple(self.exact_requirements)
        selected = tuple(self.selected_candidate_claim_ids)
        ambiguous = tuple(self.ambiguous_candidate_claim_ids)
        reasons = tuple(self.reasons)
        if any(not isinstance(item, ExactCoverageRequirement) for item in requirements):
            raise TypeError("plan exact_requirements must contain ExactCoverageRequirement")
        if any(not isinstance(item, UUID) for item in selected + ambiguous):
            raise TypeError("plan candidate claim ids must be UUID values")
        if any(not isinstance(reason, str) or not reason for reason in reasons):
            raise TypeError("plan reasons must contain non-empty strings")
        if len(reasons) != len(set(reasons)):
            raise ValueError("plan reasons must be unique")
        requirement_keys = [item.key for item in requirements]
        if len(requirement_keys) != len(set(requirement_keys)):
            raise ValueError("plan requirement keys must be unique")

        if self.status is RequirementPlanStatus.RESOLVED:
            if not requirements or len(requirements) != len(selected):
                raise ValueError(
                    "resolved plan requires one selected candidate for each exact requirement"
                )
            if ambiguous:
                raise ValueError("resolved plan cannot contain ambiguous candidates")
        else:
            if requirements or selected:
                raise ValueError(
                    "non-resolved plan cannot emit hard exact requirements"
                )
            if not reasons:
                raise ValueError("non-resolved plan requires an abstention reason")
            if self.status is RequirementPlanStatus.AMBIGUOUS and not ambiguous:
                raise ValueError("ambiguous plan requires ambiguous candidate references")

        object.__setattr__(self, "exact_requirements", requirements)
        object.__setattr__(self, "selected_candidate_claim_ids", selected)
        object.__setattr__(self, "ambiguous_candidate_claim_ids", ambiguous)
        object.__setattr__(self, "reasons", reasons)


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
