from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from sarmady.cognition import (
    ContextNeedDecision,
    ContextNeedDecisionKind,
    ContextNeedProposal,
)
from sarmady.context import ContextNeedCoordinator, ContextRequest, ExactContextCompiler
from sarmady.epistemic import ClaimRelationKind
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.storage.sqlite.schema import SCHEMA_VERSION


T0 = datetime(2026, 9, 22, 9, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    proposal: ContextNeedProposal
    binding_id: str = "fake:need-governance"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return self.proposal


def _seed_need(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    claim = EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate="memory_gb",
        value=64,
        source_ref="test:memory",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    goal_ref = uuid4()
    task_ref = uuid4()
    parent_request = ContextRequest(
        id=uuid4(),
        query="How much memory is installed?",
        token_budget=1200,
        latency_budget_ms=2400,
        goal_ref=goal_ref,
        task_ref=task_ref,
        coverage_requirements=("current memory",),
        known_at=T0 + timedelta(minutes=1),
        valid_at=T0 + timedelta(minutes=1),
    )
    projection = ExactContextCompiler(store).compile(
        parent_request,
        subject="machine:primary",
        predicate="memory_gb",
    )
    proposal = ContextNeedProposal(
        query="Which operating system is installed?",
        reason="The current projection contains memory capacity but not the OS fact.",
        coverage_requirements=("current operating system", "supporting evidence"),
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
    return agent, claim, parent_request, projection, proposal, step.artifact, invocation, cognitive_request


def test_accept_creates_bounded_durable_child_request_without_automatic_fulfillment(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        (
            _,
            _,
            parent_request,
            projection,
            proposal,
            artifact,
            invocation,
            cognitive_request,
        ) = _seed_need(store)
        frontier_before = store.frontier()
        child_id = uuid4()
        decision_id = uuid4()

        result = ContextNeedCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=3),
        ).accept(
            context_need_artifact_id=artifact.id,
            reason="Host policy permits one bounded follow-up context request.",
            decision_source="test:host-policy",
            token_budget=600,
            latency_budget_ms=1200,
            decision_id=decision_id,
            child_context_request_id=child_id,
        )

        assert result.decision.id == decision_id
        assert result.decision.decision is ContextNeedDecisionKind.ACCEPTED
        assert result.decision.context_need_artifact_id == artifact.id
        assert result.decision.parent_invocation_id == invocation.id
        assert result.decision.parent_cognitive_request_id == cognitive_request.id
        assert result.decision.parent_context_projection_id == projection.id
        assert result.decision.parent_context_request_id == parent_request.id
        assert result.decision.child_context_request_id == child_id
        assert result.child_request is not None
        assert result.child_request.id == child_id
        assert result.child_request.query == proposal.query
        assert result.child_request.coverage_requirements == proposal.coverage_requirements
        assert result.child_request.exact_requirements == ()
        assert result.child_request.token_budget == 600
        assert result.child_request.latency_budget_ms == 1200
        assert result.child_request.goal_ref == parent_request.goal_ref
        assert result.child_request.task_ref == parent_request.task_ref
        assert result.child_request.known_at == parent_request.known_at
        assert result.child_request.valid_at == parent_request.valid_at

        assert store.context_need_decision(decision_id) == result.decision
        assert store.context_need_decision_for_artifact(artifact.id) == result.decision
        assert store.context_request(child_id) == result.child_request
        assert store.frontier() == frontier_before

        # Acceptance authorizes one child ContextRequest only. It does not run
        # retrieval/planning, compile a projection, or continue cognition.
        assert store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0] == 2
        assert store.db.execute("SELECT COUNT(*) FROM context_projections").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM cognitive_requests").fetchone()[0] == 1
        assert store.db.execute("SELECT COUNT(*) FROM model_invocations").fetchone()[0] == 1


def test_accept_defaults_to_non_amplifying_parent_budgets(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, parent, _, _, artifact, _, _ = _seed_need(store)

        result = ContextNeedCoordinator(store, clock=lambda: T0 + timedelta(minutes=3)).accept(
            context_need_artifact_id=artifact.id,
            reason="Accept with inherited bounds.",
            decision_source="test:host-policy",
        )

        assert result.child_request is not None
        assert result.child_request.token_budget == parent.token_budget
        assert result.child_request.latency_budget_ms == parent.latency_budget_ms


def test_accept_rejects_budget_amplification_before_writing(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, parent, _, _, artifact, _, _ = _seed_need(store)
        coordinator = ContextNeedCoordinator(store)
        request_count = store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0]

        with pytest.raises(ValueError, match="token_budget cannot exceed"):
            coordinator.accept(
                context_need_artifact_id=artifact.id,
                reason="bad allocation",
                decision_source="test:host-policy",
                token_budget=parent.token_budget + 1,
            )
        with pytest.raises(ValueError, match="latency_budget_ms cannot exceed"):
            coordinator.accept(
                context_need_artifact_id=artifact.id,
                reason="bad allocation",
                decision_source="test:host-policy",
                latency_budget_ms=parent.latency_budget_ms + 1,  # type: ignore[operator]
            )

        assert store.context_need_decision_for_artifact(artifact.id) is None
        assert store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0] == request_count


def test_accept_is_fenced_by_source_projection_staleness(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, _, projection, _, artifact, _, _ = _seed_need(store)
        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="test:upgrade",
            observed_at=T0 + timedelta(minutes=4),
            recorded_at=T0 + timedelta(minutes=4),
            valid_from=T0 + timedelta(minutes=4),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )
        assert store.projection_is_stale(projection.id)
        request_count = store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0]

        with pytest.raises(ValueError, match="stale context projection"):
            ContextNeedCoordinator(store).accept(
                context_need_artifact_id=artifact.id,
                reason="would be obsolete",
                decision_source="test:host-policy",
            )

        assert store.context_need_decision_for_artifact(artifact.id) is None
        assert store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0] == request_count


def test_rejection_is_durable_and_does_not_create_child_request_even_if_source_is_stale(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _, _, parent, projection, _, artifact, _, _ = _seed_need(store)
        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="test:upgrade",
            observed_at=T0 + timedelta(minutes=4),
            recorded_at=T0 + timedelta(minutes=4),
            valid_from=T0 + timedelta(minutes=4),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )
        assert store.projection_is_stale(projection.id)
        request_count = store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0]

        result = ContextNeedCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=5),
        ).reject(
            context_need_artifact_id=artifact.id,
            reason="The host declines further context acquisition.",
            decision_source="test:host-policy",
        )

        assert result.decision.decision is ContextNeedDecisionKind.REJECTED
        assert result.decision.parent_context_request_id == parent.id
        assert result.decision.child_context_request_id is None
        assert result.child_request is None
        assert store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0] == request_count

        decision_id = result.decision.id

    with SQLiteCanonicalStore(path) as reopened:
        restored = reopened.context_need_decision(decision_id)
        assert restored == result.decision
        assert reopened.context_need_decision_for_artifact(artifact.id) == result.decision


def test_store_revalidates_lineage_and_child_semantics_at_durable_boundary(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, parent, projection, proposal, artifact, invocation, cognitive_request = _seed_need(store)
        child = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=600,
            latency_budget_ms=1200,
            goal_ref=parent.goal_ref,
            task_ref=parent.task_ref,
            coverage_requirements=proposal.coverage_requirements,
            known_at=parent.known_at,
            valid_at=parent.valid_at,
        )
        forged = ContextNeedDecision(
            id=uuid4(),
            context_need_artifact_id=artifact.id,
            decision=ContextNeedDecisionKind.ACCEPTED,
            decided_at=T0 + timedelta(minutes=3),
            reason="forged lineage",
            decision_source="test:direct-store",
            parent_invocation_id=uuid4(),
            parent_cognitive_request_id=cognitive_request.id,
            parent_context_projection_id=projection.id,
            parent_context_request_id=parent.id,
            child_context_request_id=child.id,
        )

        with pytest.raises(ValueError, match="invocation lineage mismatch"):
            store.register_context_need_decision(forged, child_request=child)

        assert store.context_need_decision_for_artifact(artifact.id) is None
        assert store.context_request(child.id) is None

        wrong_query = ContextRequest(
            id=uuid4(),
            query="Ignore the proposal and fetch something else",
            token_budget=600,
            latency_budget_ms=1200,
            goal_ref=parent.goal_ref,
            task_ref=parent.task_ref,
            coverage_requirements=proposal.coverage_requirements,
            known_at=parent.known_at,
            valid_at=parent.valid_at,
        )
        structurally_linked = ContextNeedDecision(
            id=uuid4(),
            context_need_artifact_id=artifact.id,
            decision=ContextNeedDecisionKind.ACCEPTED,
            decided_at=T0 + timedelta(minutes=3),
            reason="wrong semantics",
            decision_source="test:direct-store",
            parent_invocation_id=invocation.id,
            parent_cognitive_request_id=cognitive_request.id,
            parent_context_projection_id=projection.id,
            parent_context_request_id=parent.id,
            child_context_request_id=wrong_query.id,
        )
        with pytest.raises(ValueError, match="query must match"):
            store.register_context_need_decision(
                structurally_linked,
                child_request=wrong_query,
            )
        assert store.context_request(wrong_query.id) is None


def test_one_persisted_context_need_cannot_receive_two_decisions(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, _, _, _, artifact, _, _ = _seed_need(store)
        coordinator = ContextNeedCoordinator(store)
        coordinator.reject(
            context_need_artifact_id=artifact.id,
            reason="first decision",
            decision_source="test:host-policy",
        )

        with pytest.raises(ValueError, match="already has a decision"):
            coordinator.reject(
                context_need_artifact_id=artifact.id,
                reason="second decision",
                decision_source="test:host-policy",
            )

        assert store.db.execute("SELECT COUNT(*) FROM context_need_decisions").fetchone()[0] == 1


def test_acceptance_rehydrates_child_request_and_decision_after_restart(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _, _, _, _, _, artifact, _, _ = _seed_need(store)
        result = ContextNeedCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=3),
        ).accept(
            context_need_artifact_id=artifact.id,
            reason="durable accepted follow-up",
            decision_source="test:host-policy",
            token_budget=400,
            latency_budget_ms=800,
        )
        decision_id = result.decision.id
        child_id = result.child_request.id  # type: ignore[union-attr]

    with SQLiteCanonicalStore(path) as reopened:
        assert reopened.context_need_decision(decision_id) == result.decision
        assert reopened.context_request(child_id) == result.child_request
        assert reopened.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION


def test_unknown_or_non_context_need_artifact_cannot_cross_decision_boundary(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        coordinator = ContextNeedCoordinator(store)
        with pytest.raises(ValueError, match="unknown context need artifact"):
            coordinator.reject(
                context_need_artifact_id=uuid4(),
                reason="no provenance",
                decision_source="test:host-policy",
            )
