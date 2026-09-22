from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import ContextNeedProposal
from sarmady.context import (
    ContextNeedCoordinator,
    ContextNeedPlanningCoordinator,
    ContextRequest,
    ExactContextCompiler,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.memory import MemoryLifecycleEventKind
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 21, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    binding_id: str = "fake:planning-retry-telemetry"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return ContextNeedProposal(
            "Which operating system is installed on system primary?",
            "Need an exact OS obligation.",
            ("current operating system",),
        )


def test_seen_telemetry_does_not_turn_retry_into_a_new_planning_attempt(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
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
        first = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=3),
        ).plan_accepted(context_need_decision_id=accepted.decision.id)
        assert first.derived_request is not None
        first_frontier = int(first.receipt.plan.canonical_frontier)
        request_count = store.db.execute(
            "SELECT COUNT(*) FROM context_requests"
        ).fetchone()[0]
        receipt_count = store.db.execute(
            "SELECT COUNT(*) FROM context_need_planning_receipts"
        ).fetchone()[0]

        selected_claim_id = first.receipt.plan.selected_candidate_claim_ids[0]
        memory = store.memory_entry_for_target("Claim", selected_claim_id)
        assert memory is not None
        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.SEEN,
            occurred_at=T0 + timedelta(minutes=4),
            source="test:telemetry",
        )

        assert store.frontier() > first_frontier
        assert not store.context_need_planning_receipt_is_stale(first.receipt.id)

        with pytest.raises(ValueError, match="current context need planning attempt"):
            ContextNeedPlanningCoordinator(
                store,
                clock=lambda: T0 + timedelta(minutes=5),
            ).plan_accepted(context_need_decision_id=accepted.decision.id)

        assert store.db.execute(
            "SELECT COUNT(*) FROM context_requests"
        ).fetchone()[0] == request_count
        assert store.db.execute(
            "SELECT COUNT(*) FROM context_need_planning_receipts"
        ).fetchone()[0] == receipt_count
