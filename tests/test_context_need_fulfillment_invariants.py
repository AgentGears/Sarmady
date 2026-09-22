from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import (
    ContextNeedDecision,
    ContextNeedDecisionKind,
    ContextNeedProposal,
)
from sarmady.context import (
    ContextNeedCoordinator,
    ContextProjection,
    ContextRequest,
    CoverageStatus,
    ExactContextCompiler,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    proposal: ContextNeedProposal
    binding_id: str = "fake:need-invariants"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return self.proposal


def _seed_need(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate="memory_gb",
        value=64,
        source_ref="test:memory",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    parent = ContextRequest(
        id=uuid4(),
        query="How much memory is installed?",
        token_budget=1200,
        latency_budget_ms=2400,
    )
    projection = ExactContextCompiler(store).compile(
        parent,
        subject="machine:primary",
        predicate="memory_gb",
    )
    proposal = ContextNeedProposal(
        "Which operating system is installed?",
        "The source projection does not contain the OS fact.",
        ("current operating system",),
    )
    step = CognitiveRuntime(
        store,
        clock=lambda: T0 + timedelta(minutes=2),
    ).invoke_step(
        agent_id=agent.id,
        context_projection_id=projection.id,
        operation="answer-machine-question",
        adapter=NeedAdapter(proposal),
    )
    invocation = store.invocations_for_agent(agent.id)[0]
    cognitive_request = store.cognitive_request(invocation.cognitive_request_id)
    assert cognitive_request is not None
    return agent, parent, projection, proposal, step.artifact, invocation, cognitive_request


def _accepted_decision(
    *,
    parent: ContextRequest,
    projection,
    artifact,
    invocation,
    cognitive_request,
    child: ContextRequest,
    decided_at: datetime | None = None,
    decision_id=None,
) -> ContextNeedDecision:
    return ContextNeedDecision(
        id=decision_id or uuid4(),
        context_need_artifact_id=artifact.id,
        decision=ContextNeedDecisionKind.ACCEPTED,
        decided_at=decided_at or T0 + timedelta(minutes=3),
        reason="host accepts one bounded child request",
        decision_source="test:host-policy",
        parent_invocation_id=invocation.id,
        parent_cognitive_request_id=cognitive_request.id,
        parent_context_projection_id=projection.id,
        parent_context_request_id=parent.id,
        child_context_request_id=child.id,
    )


def test_context_need_decision_requires_uuid_identity_fields() -> None:
    with pytest.raises(TypeError, match="decision id must be UUID"):
        ContextNeedDecision(
            id="not-a-uuid",  # type: ignore[arg-type]
            context_need_artifact_id=uuid4(),
            decision=ContextNeedDecisionKind.REJECTED,
            decided_at=T0,
            reason="invalid identity",
            decision_source="test",
            parent_invocation_id=uuid4(),
            parent_cognitive_request_id=uuid4(),
            parent_context_projection_id=uuid4(),
            parent_context_request_id=uuid4(),
        )


def test_durable_decision_cannot_predate_completed_context_need(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, parent, projection, proposal, artifact, invocation, cognitive_request = _seed_need(store)
        child = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=600,
            latency_budget_ms=1200,
            coverage_requirements=proposal.coverage_requirements,
        )
        decision = _accepted_decision(
            parent=parent,
            projection=projection,
            artifact=artifact,
            invocation=invocation,
            cognitive_request=cognitive_request,
            child=child,
            decided_at=T0 + timedelta(minutes=1),
        )

        with pytest.raises(ValueError, match="cannot precede its completed proposal"):
            store.register_context_need_decision(decision, child_request=child)

        assert store.context_need_decision_for_artifact(artifact.id) is None
        assert store.context_request(child.id) is None


def test_direct_store_rejects_bool_child_budgets(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, parent, projection, proposal, artifact, invocation, cognitive_request = _seed_need(store)
        child = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=True,  # type: ignore[arg-type]
            latency_budget_ms=1200,
            coverage_requirements=proposal.coverage_requirements,
        )
        decision = _accepted_decision(
            parent=parent,
            projection=projection,
            artifact=artifact,
            invocation=invocation,
            cognitive_request=cognitive_request,
            child=child,
        )
        with pytest.raises(TypeError, match="child token budget must be an integer"):
            store.register_context_need_decision(decision, child_request=child)
        assert store.context_request(child.id) is None

        latency_child = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=600,
            latency_budget_ms=True,  # type: ignore[arg-type]
            coverage_requirements=proposal.coverage_requirements,
        )
        latency_decision = _accepted_decision(
            parent=parent,
            projection=projection,
            artifact=artifact,
            invocation=invocation,
            cognitive_request=cognitive_request,
            child=latency_child,
        )
        with pytest.raises(TypeError, match="child latency budget must be an integer"):
            store.register_context_need_decision(
                latency_decision,
                child_request=latency_child,
            )
        assert store.context_request(latency_child.id) is None


def test_acceptance_must_create_a_fresh_child_request_identity(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, parent, projection, proposal, artifact, invocation, cognitive_request = _seed_need(store)
        existing = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=600,
            latency_budget_ms=1200,
            coverage_requirements=proposal.coverage_requirements,
        )
        existing_projection = ContextProjection(
            id=uuid4(),
            request_id=existing.id,
            snapshot_id=f"sqlite:{store.frontier()}",
            canonical_frontier=str(store.frontier()),
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:preexisting-request",
            compiler_version="test",
        )
        store.register_context_projection(existing_projection, request=existing)

        decision = _accepted_decision(
            parent=parent,
            projection=projection,
            artifact=artifact,
            invocation=invocation,
            cognitive_request=cognitive_request,
            child=existing,
        )
        with pytest.raises(ValueError, match="child context request id already exists"):
            store.register_context_need_decision(decision, child_request=existing)

        assert store.context_need_decision_for_artifact(artifact.id) is None
        assert store.context_request(existing.id) == existing


def test_child_insert_rolls_back_if_decision_insert_fails(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        agent, parent, projection, proposal, first_artifact, _, _ = _seed_need(store)
        fixed_decision_id = uuid4()
        ContextNeedCoordinator(store, clock=lambda: T0 + timedelta(minutes=3)).reject(
            context_need_artifact_id=first_artifact.id,
            reason="occupy the decision id",
            decision_source="test:host-policy",
            decision_id=fixed_decision_id,
        )

        second_step = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=4),
        ).invoke_step(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-machine-question-again",
            adapter=NeedAdapter(proposal),
        )
        second_invocation = store.invocations_for_agent(agent.id)[1]
        second_cognitive = store.cognitive_request(second_invocation.cognitive_request_id)
        assert second_cognitive is not None
        child = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=600,
            latency_budget_ms=1200,
            coverage_requirements=proposal.coverage_requirements,
        )
        conflicting = _accepted_decision(
            parent=parent,
            projection=projection,
            artifact=second_step.artifact,
            invocation=second_invocation,
            cognitive_request=second_cognitive,
            child=child,
            decided_at=T0 + timedelta(minutes=5),
            decision_id=fixed_decision_id,
        )

        with pytest.raises(sqlite3.IntegrityError):
            store.register_context_need_decision(conflicting, child_request=child)

        assert store.context_request(child.id) is None
        assert store.context_need_decision_for_artifact(second_step.artifact.id) is None


def test_schema_enforces_one_decision_owner_per_child_request(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        indexes = store.db.execute("PRAGMA index_list('context_need_decisions')").fetchall()
        names = {row[1] for row in indexes if row[2]}
        assert "idx_context_need_decisions_child_request" in names
