from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import ContextNeedProposal
from sarmady.context import (
    ContextNeedCoordinator,
    ContextNeedPlanningCoordinator,
    ContextNeedPlanningReceipt,
    ContextRequest,
    ExactContextCompiler,
    ExactCoverageRequirement,
    RequirementPlan,
    RequirementPlanStatus,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 20, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    binding_id: str = "fake:planning-store-invariants"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return ContextNeedProposal(
            "Which operating system is installed on system primary?",
            "Need an exact operating-system obligation.",
            ("current operating system",),
        )


def _seed_resolved_plan(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    service = EpistemicMemoryService(store)
    service.observe_claim(
        subject="system:primary",
        predicate="memory_gb",
        value=64,
        source_ref="test:memory",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    service.observe_claim(
        subject="system:primary",
        predicate="operating_system",
        value="RHEL 9",
        source_ref="test:os",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    parent = ContextRequest(uuid4(), "memory_gb system primary", 800)
    projection = ExactContextCompiler(store).compile(
        parent,
        subject="system:primary",
        predicate="memory_gb",
    )
    step = CognitiveRuntime(
        store,
        clock=lambda: T0 + timedelta(minutes=1),
    ).invoke_step(
        agent_id=agent.id,
        context_projection_id=projection.id,
        operation="answer-system-question",
        adapter=NeedAdapter(),
    )
    accepted = ContextNeedCoordinator(
        store,
        clock=lambda: T0 + timedelta(minutes=2),
    ).accept(
        context_need_artifact_id=step.artifact.id,
        reason="allow planning",
        decision_source="test:host-policy",
    )
    planned = ContextNeedPlanningCoordinator(
        store,
        clock=lambda: T0 + timedelta(minutes=3),
    ).plan_accepted(context_need_decision_id=accepted.decision.id)
    assert planned.receipt.plan.status is RequirementPlanStatus.RESOLVED
    assert planned.receipt.candidate_limit == 20
    assert planned.derived_request is not None
    return accepted, planned


def test_store_rejects_noncanonical_candidate_frontier_spelling(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        accepted, planned = _seed_resolved_plan(store)
        valid = planned.receipt.plan
        forged_plan = RequirementPlan(
            source_request_id=valid.source_request_id,
            source_request_fingerprint=valid.source_request_fingerprint,
            candidate_snapshot_id=valid.candidate_snapshot_id,
            canonical_frontier="0" + valid.canonical_frontier,
            candidate_generator_version=valid.candidate_generator_version,
            planner_version=valid.planner_version,
            status=valid.status,
            exact_requirements=valid.exact_requirements,
            selected_candidate_claim_ids=valid.selected_candidate_claim_ids,
        )
        forged_request = ContextRequest(
            id=uuid4(),
            query=planned.derived_request.query,
            token_budget=planned.derived_request.token_budget,
            latency_budget_ms=planned.derived_request.latency_budget_ms,
            goal_ref=planned.derived_request.goal_ref,
            task_ref=planned.derived_request.task_ref,
            coverage_requirements=planned.derived_request.coverage_requirements,
            exact_requirements=forged_plan.exact_requirements,
            known_at=planned.derived_request.known_at,
            valid_at=planned.derived_request.valid_at,
        )
        receipt = ContextNeedPlanningReceipt(
            id=uuid4(),
            context_need_decision_id=accepted.decision.id,
            planned_at=T0 + timedelta(minutes=4),
            plan=forged_plan,
            derived_context_request_id=forged_request.id,
        )

        with pytest.raises(ValueError, match="canonical integer spelling"):
            store.register_context_need_planning_receipt(
                receipt,
                derived_request=forged_request,
            )
        assert store.context_request(forged_request.id) is None


def test_store_rejects_resolved_shape_impossible_for_controlled_planner_v01(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        accepted, planned = _seed_resolved_plan(store)
        valid = planned.receipt.plan
        second_requirement = ExactCoverageRequirement(
            key="planned:system:primary:serial_number",
            subject="system:primary",
            predicate="serial_number",
        )
        forged_plan = RequirementPlan(
            source_request_id=valid.source_request_id,
            source_request_fingerprint=valid.source_request_fingerprint,
            candidate_snapshot_id=valid.candidate_snapshot_id,
            canonical_frontier=valid.canonical_frontier,
            candidate_generator_version=valid.candidate_generator_version,
            planner_version=valid.planner_version,
            status=RequirementPlanStatus.RESOLVED,
            exact_requirements=(valid.exact_requirements[0], second_requirement),
            selected_candidate_claim_ids=(
                valid.selected_candidate_claim_ids[0],
                valid.selected_candidate_claim_ids[0],
            ),
        )
        forged_request = ContextRequest(
            id=uuid4(),
            query=planned.derived_request.query,
            token_budget=planned.derived_request.token_budget,
            latency_budget_ms=planned.derived_request.latency_budget_ms,
            goal_ref=planned.derived_request.goal_ref,
            task_ref=planned.derived_request.task_ref,
            coverage_requirements=planned.derived_request.coverage_requirements,
            exact_requirements=forged_plan.exact_requirements,
            known_at=planned.derived_request.known_at,
            valid_at=planned.derived_request.valid_at,
        )
        receipt = ContextNeedPlanningReceipt(
            id=uuid4(),
            context_need_decision_id=accepted.decision.id,
            planned_at=T0 + timedelta(minutes=4),
            plan=forged_plan,
            derived_context_request_id=forged_request.id,
        )

        with pytest.raises(ValueError, match="exactly one obligation"):
            store.register_context_need_planning_receipt(
                receipt,
                derived_request=forged_request,
            )
        assert store.context_request(forged_request.id) is None


def test_same_frontier_and_planning_configuration_is_not_silently_duplicated(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        accepted, first = _seed_resolved_plan(store)
        request_count = store.db.execute(
            "SELECT COUNT(*) FROM context_requests"
        ).fetchone()[0]
        receipt_count = store.db.execute(
            "SELECT COUNT(*) FROM context_need_planning_receipts"
        ).fetchone()[0]

        with pytest.raises(ValueError, match="planning attempt already recorded"):
            ContextNeedPlanningCoordinator(
                store,
                clock=lambda: T0 + timedelta(minutes=4),
            ).plan_accepted(context_need_decision_id=accepted.decision.id)

        assert store.db.execute(
            "SELECT COUNT(*) FROM context_requests"
        ).fetchone()[0] == request_count
        assert store.db.execute(
            "SELECT COUNT(*) FROM context_need_planning_receipts"
        ).fetchone()[0] == receipt_count
        restored = store.context_need_planning_receipt(first.receipt.id)
        assert restored == first.receipt
        assert restored.candidate_limit == 20


def test_different_candidate_limit_is_distinct_planning_configuration(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        accepted, first = _seed_resolved_plan(store)
        second = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=4),
        ).plan_accepted(
            context_need_decision_id=accepted.decision.id,
            candidate_limit=21,
        )

        assert second.receipt.plan.canonical_frontier == first.receipt.plan.canonical_frontier
        assert second.receipt.candidate_limit == 21
        assert second.receipt.id != first.receipt.id
        assert second.derived_request is not None
        assert second.derived_request.id != first.derived_request.id
        receipts = store.context_need_planning_receipts_for_decision(accepted.decision.id)
        assert {receipt.candidate_limit for receipt in receipts} == {20, 21}
