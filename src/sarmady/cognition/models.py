from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


CONTEXT_NEED_ARTIFACT_KIND = "context-need:v1"
_CONTEXT_NEED_CONTRACT = "ContextNeedProposal:v1"


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
class ContextNeedProposal:
    """Non-authoritative model proposal for additional semantic context.

    The proposal deliberately carries only the information need. It does not
    allocate compute, select exact semantic addresses, create a ContextRequest,
    or authorize retrieval/memory mutation.
    """

    query: str
    reason: str
    coverage_requirements: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.query, str) or not self.query.strip():
            raise ValueError("context need query is required")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("context need reason is required")
        if isinstance(self.coverage_requirements, str):
            raise TypeError("context need coverage_requirements must be an iterable of strings")
        try:
            requirements = tuple(self.coverage_requirements)
        except TypeError as exc:
            raise TypeError(
                "context need coverage_requirements must be an iterable of strings"
            ) from exc
        if any(not isinstance(item, str) or not item.strip() for item in requirements):
            raise TypeError(
                "context need coverage_requirements must contain non-empty strings"
            )
        if len(requirements) != len(set(requirements)):
            raise ValueError("context need coverage_requirements must be unique")
        object.__setattr__(self, "coverage_requirements", requirements)


def serialize_context_need_proposal(proposal: ContextNeedProposal) -> str:
    """Serialize a context-need proposal into the durable v1 artifact payload."""

    if not isinstance(proposal, ContextNeedProposal):
        raise TypeError("proposal must be ContextNeedProposal")
    return json.dumps(
        {
            "contract": _CONTEXT_NEED_CONTRACT,
            "query": proposal.query,
            "reason": proposal.reason,
            "coverage_requirements": list(proposal.coverage_requirements),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def deserialize_context_need_proposal(content: str) -> ContextNeedProposal:
    """Strictly rehydrate a durable v1 context-need artifact payload."""

    if not isinstance(content, str):
        raise TypeError("context need artifact content must be a string")
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("context need artifact content is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("context need artifact payload must be an object")
    expected_keys = {
        "contract",
        "query",
        "reason",
        "coverage_requirements",
    }
    if set(payload) != expected_keys:
        raise ValueError("context need artifact payload has unexpected fields")
    if payload["contract"] != _CONTEXT_NEED_CONTRACT:
        raise ValueError("unsupported context need artifact contract")
    requirements = payload["coverage_requirements"]
    if not isinstance(requirements, list):
        raise TypeError("context need coverage_requirements must be a JSON array")
    return ContextNeedProposal(
        query=payload["query"],
        reason=payload["reason"],
        coverage_requirements=tuple(requirements),
    )


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
