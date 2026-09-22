from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from .models import ContextRequest, RequirementPlan, RequirementPlanStatus


def _require_uuid(value: UUID, field_name: str) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be UUID")


def _require_aware(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{field_name} must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ContextNeedPlanningReceipt:
    """Durable operational receipt for planning one accepted context need.

    The embedded ``RequirementPlan`` remains derived context computation. The
    receipt records which accepted child request was planned, against which
    candidate snapshot/frontier and candidate limit, and whether planning
    produced a new exact request. It is not epistemic truth and does not
    authorize projection compilation or model continuation.
    """

    id: UUID
    context_need_decision_id: UUID
    planned_at: datetime
    plan: RequirementPlan
    candidate_limit: int = 20
    derived_context_request_id: UUID | None = None

    def __post_init__(self) -> None:
        _require_uuid(self.id, "context need planning receipt id")
        _require_uuid(
            self.context_need_decision_id,
            "context need planning receipt decision id",
        )
        _require_aware(self.planned_at, "planned_at")
        if not isinstance(self.plan, RequirementPlan):
            raise TypeError("context need planning receipt requires RequirementPlan")
        _require_uuid(
            self.plan.source_request_id,
            "context need planning receipt source request id",
        )
        if isinstance(self.candidate_limit, bool) or not isinstance(
            self.candidate_limit, int
        ):
            raise TypeError("context need planning receipt candidate_limit must be an integer")
        if self.candidate_limit <= 0:
            raise ValueError("context need planning receipt candidate_limit must be positive")
        if self.derived_context_request_id is not None:
            _require_uuid(
                self.derived_context_request_id,
                "context need planning receipt derived request id",
            )

        if self.plan.status is RequirementPlanStatus.RESOLVED:
            if self.derived_context_request_id is None:
                raise ValueError(
                    "resolved context need planning receipt requires a derived request"
                )
            if self.derived_context_request_id == self.plan.source_request_id:
                raise ValueError(
                    "resolved context need planning receipt must create a new request id"
                )
        elif self.derived_context_request_id is not None:
            raise ValueError(
                "non-resolved context need planning receipt cannot carry a derived request"
            )


@dataclass(frozen=True, slots=True)
class ContextNeedPlanningResult:
    receipt: ContextNeedPlanningReceipt
    derived_request: ContextRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.receipt, ContextNeedPlanningReceipt):
            raise TypeError("planning result requires ContextNeedPlanningReceipt")
        if self.receipt.plan.status is RequirementPlanStatus.RESOLVED:
            if not isinstance(self.derived_request, ContextRequest):
                raise TypeError("resolved planning result requires derived ContextRequest")
            if self.derived_request.id != self.receipt.derived_context_request_id:
                raise ValueError("derived request id does not match planning receipt")
        elif self.derived_request is not None:
            raise ValueError("non-resolved planning result cannot carry a derived request")
