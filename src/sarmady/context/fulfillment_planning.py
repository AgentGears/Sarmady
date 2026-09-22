from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Callable
from uuid import UUID, uuid4

from sarmady.cognition import ContextNeedDecisionKind

from .candidates import LexicalCandidateGenerator
from .planning import ControlledRequirementPlanner
from .planning_receipt import ContextNeedPlanningReceipt, ContextNeedPlanningResult


class ContextNeedPlanningCoordinator:
    """Plan one accepted context need without compiling or continuing cognition.

    The coordinator performs snapshot-bound candidate discovery followed by the
    conservative controlled requirement planner. The durable store revalidates
    the accepted-decision lineage, source request semantics, planning frontier,
    and any derived exact request under its write lock before persistence.
    """

    def __init__(
        self,
        store: Any,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self.clock = clock or (lambda: datetime.now(UTC))

    def plan_accepted(
        self,
        *,
        context_need_decision_id: UUID,
        candidate_limit: int = 20,
        receipt_id: UUID | None = None,
        derived_context_request_id: UUID | None = None,
    ) -> ContextNeedPlanningResult:
        if not isinstance(context_need_decision_id, UUID):
            raise TypeError("context_need_decision_id must be UUID")

        decision = self.store.context_need_decision(context_need_decision_id)
        if decision is None:
            raise ValueError(f"unknown context need decision {context_need_decision_id}")
        if decision.decision is not ContextNeedDecisionKind.ACCEPTED:
            raise ValueError("only an accepted context need can be planned")
        if decision.child_context_request_id is None:
            raise RuntimeError("accepted context need is missing its child request")

        source = self.store.context_request(decision.child_context_request_id)
        if source is None:
            raise RuntimeError("accepted context need references a missing child request")

        candidates = LexicalCandidateGenerator(self.store).generate(
            source,
            limit=candidate_limit,
        )
        planner = ControlledRequirementPlanner()
        plan = planner.plan(source, candidates)

        derived_request = None
        if plan.status.value == "RESOLVED":
            derived_request = planner.derive_request(
                source,
                plan,
                new_request_id=derived_context_request_id or uuid4(),
            )
        elif derived_context_request_id is not None:
            raise ValueError(
                "derived_context_request_id is valid only when planning resolves"
            )

        receipt = ContextNeedPlanningReceipt(
            id=receipt_id or uuid4(),
            context_need_decision_id=context_need_decision_id,
            planned_at=self.clock(),
            plan=plan,
            derived_context_request_id=(
                derived_request.id if derived_request is not None else None
            ),
        )
        self.store.register_context_need_planning_receipt(
            receipt,
            derived_request=derived_request,
        )
        return ContextNeedPlanningResult(receipt, derived_request)
