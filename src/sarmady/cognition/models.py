from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class CognitiveRequest:
    id: UUID
    agent_id: UUID
    context_projection_id: UUID
    operation: str
    created_at: datetime
    reasoning_policy_id: str | None = None

    def __post_init__(self) -> None:
        if not self.operation.strip():
            raise ValueError("operation is required")
        if self.reasoning_policy_id is not None and not self.reasoning_policy_id.strip():
            raise ValueError("reasoning_policy_id cannot be blank")
        _require_aware(self.created_at, "created_at")


@dataclass(frozen=True, slots=True)
class ModelInvocation:
    id: UUID
    cognitive_request_id: UUID
    model_binding: str
    started_at: datetime
    completed_at: datetime | None = None
    error_code: str | None = None

    def __post_init__(self) -> None:
        if not self.model_binding.strip():
            raise ValueError("model_binding is required")
        _require_aware(self.started_at, "started_at")
        if self.completed_at is not None:
            _require_aware(self.completed_at, "completed_at")
            if self.completed_at < self.started_at:
                raise ValueError("completed_at cannot precede started_at")


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    id: UUID
    invocation_id: UUID
    artifact_kind: str
    content: str
    created_at: datetime

    def __post_init__(self) -> None:
        if not self.artifact_kind.strip():
            raise ValueError("artifact_kind is required")
        _require_aware(self.created_at, "created_at")


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
    id: UUID
    decision_kind: str
    selected: str
    adopted_at: datetime
    source_artifact_refs: tuple[UUID, ...] = ()
