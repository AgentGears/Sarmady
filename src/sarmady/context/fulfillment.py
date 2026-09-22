from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID, uuid4

from sarmady.cognition import (
    CONTEXT_NEED_ARTIFACT_KIND,
    ContextNeedDecision,
    ContextNeedDecisionKind,
    ContextNeedProposal,
    deserialize_context_need_proposal,
)

from .models import ContextRequest


@dataclass(frozen=True, slots=True)
class ContextNeedDecisionResult:
    decision: ContextNeedDecision
    child_request: ContextRequest | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.decision, ContextNeedDecision):
            raise TypeError("decision result requires ContextNeedDecision")
        if self.decision.decision is ContextNeedDecisionKind.ACCEPTED:
            if not isinstance(self.child_request, ContextRequest):
                raise TypeError("accepted decision result requires child ContextRequest")
            if self.child_request.id != self.decision.child_context_request_id:
                raise ValueError("child request id does not match accepted decision")
        elif self.child_request is not None:
            raise ValueError("rejected decision result cannot carry a child request")


@dataclass(frozen=True, slots=True)
class _ContextNeedLineage:
    proposal: ContextNeedProposal
    invocation_id: UUID
    cognitive_request_id: UUID
    projection_id: UUID
    parent_request: ContextRequest


class ContextNeedCoordinator:
    """Turn a persisted model proposal into an explicit host decision.

    Acceptance creates exactly one durable child ``ContextRequest`` with a
    bounded budget transfer. It does not retrieve candidates, plan exact
    requirements, compile a projection, mutate memory, or continue cognition.
    """

    def __init__(
        self,
        store: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def accept(
        self,
        *,
        context_need_artifact_id: UUID,
        reason: str,
        decision_source: str,
        token_budget: int | None = None,
        latency_budget_ms: int | None = None,
        decision_id: UUID | None = None,
        child_context_request_id: UUID | None = None,
    ) -> ContextNeedDecisionResult:
        lineage = self._load_lineage(context_need_artifact_id)
        parent = lineage.parent_request

        allocated_tokens = parent.token_budget if token_budget is None else token_budget
        if isinstance(allocated_tokens, bool) or not isinstance(allocated_tokens, int):
            raise TypeError("child token_budget must be an integer")
        if allocated_tokens <= 0:
            raise ValueError("child token_budget must be positive")
        if allocated_tokens > parent.token_budget:
            raise ValueError("child token_budget cannot exceed parent token budget")

        parent_latency = (
            parent.latency_budget_ms
            if parent.latency_budget_ms is not None and parent.latency_budget_ms > 0
            else None
        )
        allocated_latency = parent_latency if latency_budget_ms is None else latency_budget_ms
        if allocated_latency is not None:
            if isinstance(allocated_latency, bool) or not isinstance(allocated_latency, int):
                raise TypeError("child latency_budget_ms must be an integer")
            if allocated_latency <= 0:
                raise ValueError("child latency_budget_ms must be positive")
        if (
            parent_latency is not None
            and allocated_latency is not None
            and allocated_latency > parent_latency
        ):
            raise ValueError("child latency_budget_ms cannot exceed parent latency budget")
        if parent_latency is not None and allocated_latency is None:
            raise ValueError("bounded parent latency cannot be removed from child request")

        child_request = ContextRequest(
            id=child_context_request_id or uuid4(),
            query=lineage.proposal.query,
            token_budget=allocated_tokens,
            latency_budget_ms=allocated_latency,
            goal_ref=parent.goal_ref,
            task_ref=parent.task_ref,
            coverage_requirements=lineage.proposal.coverage_requirements,
            exact_requirements=(),
            known_at=parent.known_at,
            valid_at=parent.valid_at,
        )
        decision = ContextNeedDecision(
            id=decision_id or uuid4(),
            context_need_artifact_id=context_need_artifact_id,
            decision=ContextNeedDecisionKind.ACCEPTED,
            decided_at=self.clock(),
            reason=reason,
            decision_source=decision_source,
            parent_invocation_id=lineage.invocation_id,
            parent_cognitive_request_id=lineage.cognitive_request_id,
            parent_context_projection_id=lineage.projection_id,
            parent_context_request_id=parent.id,
            child_context_request_id=child_request.id,
        )
        self.store.register_context_need_decision(
            decision,
            child_request=child_request,
        )
        return ContextNeedDecisionResult(decision, child_request)

    def reject(
        self,
        *,
        context_need_artifact_id: UUID,
        reason: str,
        decision_source: str,
        decision_id: UUID | None = None,
    ) -> ContextNeedDecisionResult:
        lineage = self._load_lineage(context_need_artifact_id)
        decision = ContextNeedDecision(
            id=decision_id or uuid4(),
            context_need_artifact_id=context_need_artifact_id,
            decision=ContextNeedDecisionKind.REJECTED,
            decided_at=self.clock(),
            reason=reason,
            decision_source=decision_source,
            parent_invocation_id=lineage.invocation_id,
            parent_cognitive_request_id=lineage.cognitive_request_id,
            parent_context_projection_id=lineage.projection_id,
            parent_context_request_id=lineage.parent_request.id,
        )
        self.store.register_context_need_decision(decision)
        return ContextNeedDecisionResult(decision)

    def _load_lineage(self, artifact_id: UUID) -> _ContextNeedLineage:
        if not isinstance(artifact_id, UUID):
            raise TypeError("context_need_artifact_id must be UUID")
        artifact = self.store.artifact(artifact_id)
        if artifact is None:
            raise ValueError(f"unknown context need artifact {artifact_id}")
        if artifact.artifact_kind != CONTEXT_NEED_ARTIFACT_KIND:
            raise ValueError("artifact is not a context-need proposal")
        proposal = deserialize_context_need_proposal(artifact.content)

        invocation = self.store.invocation(artifact.invocation_id)
        if invocation is None:
            raise RuntimeError("context-need artifact references missing invocation")
        if invocation.completed_at is None or invocation.error_code is not None:
            raise ValueError("context-need artifact does not come from a successful invocation")
        cognitive_request = self.store.cognitive_request(invocation.cognitive_request_id)
        if cognitive_request is None:
            raise RuntimeError("context-need invocation references missing cognitive request")
        projection = self.store.context_projection(cognitive_request.context_projection_id)
        if projection is None:
            raise RuntimeError("context-need cognitive request references missing projection")
        parent_request = self.store.context_request(projection.request_id)
        if parent_request is None:
            raise RuntimeError("context-need projection references missing context request")

        return _ContextNeedLineage(
            proposal=proposal,
            invocation_id=invocation.id,
            cognitive_request_id=cognitive_request.id,
            projection_id=projection.id,
            parent_request=parent_request,
        )
