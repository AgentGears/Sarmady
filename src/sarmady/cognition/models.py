from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True, slots=True)
class CognitiveRequest:
    id: UUID
    context_projection_id: UUID
    operation: str
    reasoning_policy_id: str | None = None


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    id: UUID
    cognitive_request_id: UUID
    model_binding: str
    started_at: datetime
    completed_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    """Non-authoritative output from cognitive compute."""

    id: UUID
    invocation_id: UUID
    artifact_kind: str
    content: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class ChoiceCandidate:
    key: str
    probability: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.probability <= 1.0:
            raise ValueError("probability must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class ChoiceResult:
    id: UUID
    cognitive_request_id: UUID
    candidates: tuple[ChoiceCandidate, ...]
    calibration_ref: str | None = None


@dataclass(frozen=True, slots=True)
class DecisionRecord:
    """A durable adopted decision, distinct from any model-produced artifact."""

    id: UUID
    decision_kind: str
    selected: str
    adopted_at: datetime
    source_artifact_refs: tuple[UUID, ...] = ()
