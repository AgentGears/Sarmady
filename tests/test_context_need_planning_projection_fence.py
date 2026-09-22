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
    CoverageContextCompiler,
    ExactContextCompiler,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 19, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    binding_id: str = "fake:planning-projection-fence"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return ContextNeedProposal(
            "Which operating system is installed on system primary?",
            "Need an exact OS obligation.",
            ("current operating system",),
        )


def _observe(store, subject, predicate, value, minute=0) -> None:
    at = T0 + timedelta(minutes=minute)
    EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate=predicate,
        value=value,
        source_ref=f"test:{subject}:{predicate}:{minute}",
        observed_at=at,
        recorded_at=at,
        valid_from=at,
    )


def _accepted(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    _observe(store, "system:primary", "memory_gb", 64)
    _observe(store, "system:primary", "operating_system", "RHEL 9")
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
    return ContextNeedCoordinator(
        store,
        clock=lambda: T0 + timedelta(minutes=2),
    ).accept(
        context_need_artifact_id=step.artifact.id,
        reason="allow exact planning",
        decision_source="test:host-policy",
    )


def test_stale_planning_receipt_cannot_register_any_projection_for_derived_request(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        accepted = _accepted(store)
        planned = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=3),
        ).plan_accepted(context_need_decision_id=accepted.decision.id)
        assert planned.derived_request is not None
        projection_count = store.db.execute(
            "SELECT COUNT(*) FROM context_projections"
        ).fetchone()[0]

        _observe(store, "system:new", "serial_number", "ABC", minute=4)
        assert store.context_need_planning_receipt_is_stale(planned.receipt.id)

        with pytest.raises(ValueError, match="stale context-need planning receipt"):
            CoverageContextCompiler(store).compile(planned.derived_request)

        assert (
            store.db.execute("SELECT COUNT(*) FROM context_projections").fetchone()[0]
            == projection_count
        )

        # Replanning the same accepted child at the new frontier produces a new
        # exact request whose planning proof is current and can be projected.
        replanned = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=5),
        ).plan_accepted(context_need_decision_id=accepted.decision.id)
        assert replanned.derived_request is not None
        assert replanned.derived_request.id != planned.derived_request.id
        projection = CoverageContextCompiler(store).compile(replanned.derived_request)
        assert projection.request_id == replanned.derived_request.id
        assert not store.projection_is_stale(projection.id)
