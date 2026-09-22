from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID


def _require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


class ContextNeedDecisionKind(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


@dataclass(frozen=True, slots=True)
class ContextNeedDecision:
    """Durable host decision over one persisted context-need artifact.

    ``decision_source`` is an audit label identifying the trusted host boundary
    that supplied the decision. It is not itself an authentication, permission,
    or capability primitive.
    """

    id: UUID
    context_need_artifact_id: UUID
    decision: ContextNeedDecisionKind
    decided_at: datetime
    reason: str
    decision_source: str
    parent_invocation_id: UUID
    parent_cognitive_request_id: UUID
    parent_context_projection_id: UUID
    parent_context_request_id: UUID
    child_context_request_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "context need decision id")
        _require_uuid(
            self.context_need_artifact_id,
            "context need decision artifact id",
        )
        _require_uuid(
            self.parent_invocation_id,
            "context need decision parent invocation id",
        )
        _require_uuid(
            self.parent_cognitive_request_id,
            "context need decision parent cognitive request id",
        )
        _require_uuid(
            self.parent_context_projection_id,
            "context need decision parent context projection id",
        )
        _require_uuid(
            self.parent_context_request_id,
            "context need decision parent context request id",
        )
        if self.child_context_request_id is not None:
            _require_uuid(
                self.child_context_request_id,
                "context need decision child context request id",
            )
        if not isinstance(self.decision, ContextNeedDecisionKind):
            raise TypeError("context need decision must be ContextNeedDecisionKind")
        _require_aware(self.decided_at, "decided_at")
        if not isinstance(self.reason, str) or not self.reason.strip():
            raise ValueError("context need decision reason is required")
        if not isinstance(self.decision_source, str) or not self.decision_source.strip():
            raise ValueError("context need decision source is required")
        if self.decision is ContextNeedDecisionKind.ACCEPTED:
            if self.child_context_request_id is None:
                raise ValueError("accepted context need requires a child context request")
            if self.child_context_request_id == self.parent_context_request_id:
                raise ValueError("accepted context need must create a new child request id")
        elif self.child_context_request_id is not None:
            raise ValueError("rejected context need cannot create a child context request")
