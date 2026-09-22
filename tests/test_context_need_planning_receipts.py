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
    ControlledRequirementPlanner,
    ExactContextCompiler,
    LexicalCandidateGenerator,
    RequirementPlanStatus,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    proposal: ContextNeedProposal
    binding_id: str = "fake:planning-receipt"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return self.proposal


def _observe(
    store: SQLiteCanonicalStore,
    *,
    subject: str,
    predicate: str,
    value,
    minute: int = 0,
):
    at = T0 + timedelta(minutes=minute)
    return EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate=predicate,
        value=value,
        source_ref=f"test:{subject}:{predicate}:{minute}",
        observed_at=at,
        recorded_at=at,
        valid_from=at,
    )


def _seed_accepted_need(
    store: SQLiteCanonicalStore,
    *,
    proposal_query: str = "Which operating system is installed on system primary?",
    extra_os_subjects: tuple[str, ...] = ("system:primary",),
):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    _observe(
        store,
        subject="system:primary",
        predicate="memory_gb",
        value=64,
    )
    for subject in extra_os_subjects:
        _observe(
            store,
            subject=subject,
            predicate="operating_system",
            value="RHEL 9",
        )

    parent = ContextRequest(
        id=uuid4(),
        query="How much memory is installed on system primary?",
        token_budget=1200,
        latency_budget_ms=2400,
        goal_ref=uuid4(),
        task_ref=uuid4(),
        known_at=T0 + timedelta(minutes=1),
        valid_at=T0 + timedelta(minutes=1),
    )
    projection = ExactContextCompiler(store).compile(
        parent,
        subject="system:primary",
        predicate="memory_gb",
    )
    proposal = ContextNeedProposal(
        proposal_query,
        "The source projection does not contain the requested platform fact.",
        ("current operating system",),
    )
    step = CognitiveRuntime(
        store,
        clock=lambda: T0 + timedelta(minutes=2),
    ).invoke_step(
        agent_id=agent.id,
        context_projection_id=projection.id,
        operation="answer-system-question",
        adapter=NeedAdapter(proposal),
    )
    accepted = ContextNeedCoordinator(
        store,
        clock=lambda: T0 + timedelta(minutes=3),
    ).accept(
        context_need_artifact_id=step.artifact.id,
        reason="allow one bounded planning request",
        decision_source="test:host-policy",
        token_budget=600,
        latency_budget_ms=1200,
    )
    assert accepted.child_request is not None
    return agent, projection, accepted


def test_resolved_planning_receipt_creates_durable_exact_request_only(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, _, accepted = _seed_accepted_need(store)
        projection_count = store.db.execute(
            "SELECT COUNT(*) FROM context_projections"
        ).fetchone()[0]
        cognitive_count = store.db.execute(
            "SELECT COUNT(*) FROM cognitive_requests"
        ).fetchone()[0]
        invocation_count = store.db.execute(
            "SELECT COUNT(*) FROM model_invocations"
        ).fetchone()[0]
        frontier_before = store.frontier()

        result = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=4),
        ).plan_accepted(
            context_need_decision_id=accepted.decision.id,
            candidate_limit=20,
        )

        assert result.receipt.plan.status is RequirementPlanStatus.RESOLVED
        assert result.derived_request is not None
        assert result.derived_request.id == result.receipt.derived_context_request_id
        assert result.derived_request.id != accepted.child_request.id
        assert result.derived_request.query == accepted.child_request.query
        assert result.derived_request.token_budget == accepted.child_request.token_budget
        assert (
            result.derived_request.latency_budget_ms
            == accepted.child_request.latency_budget_ms
        )
        assert result.derived_request.goal_ref == accepted.child_request.goal_ref
        assert result.derived_request.task_ref == accepted.child_request.task_ref
        assert result.derived_request.known_at == accepted.child_request.known_at
        assert result.derived_request.valid_at == accepted.child_request.valid_at
        assert len(result.derived_request.exact_requirements) == 1
        requirement = result.derived_request.exact_requirements[0]
        assert requirement.subject == "system:primary"
        assert requirement.predicate == "operating_system"

        assert store.context_need_planning_receipt(result.receipt.id) == result.receipt
        assert store.context_request(result.derived_request.id) == result.derived_request
        assert not store.context_need_planning_receipt_is_stale(result.receipt.id)
        assert store.frontier() == frontier_before

        # Planning records an exact follow-up request only. It does not compile
        # a projection, create a cognitive request, or invoke a model.
        assert (
            store.db.execute("SELECT COUNT(*) FROM context_projections").fetchone()[0]
            == projection_count
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM cognitive_requests").fetchone()[0]
            == cognitive_count
        )
        assert (
            store.db.execute("SELECT COUNT(*) FROM model_invocations").fetchone()[0]
            == invocation_count
        )
        assert len(store.invocations_for_agent(agent.id)) == 1

        receipt_id = result.receipt.id
        derived_id = result.derived_request.id

    with SQLiteCanonicalStore(path) as reopened:
        restored = reopened.context_need_planning_receipt(receipt_id)
        assert restored == result.receipt
        assert reopened.context_request(derived_id) == result.derived_request


def test_ambiguous_planning_receipt_is_durable_without_derived_request(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, accepted = _seed_accepted_need(
            store,
            proposal_query="Which operating system is installed?",
            extra_os_subjects=("system:primary", "system:backup"),
        )
        request_count = store.db.execute(
            "SELECT COUNT(*) FROM context_requests"
        ).fetchone()[0]

        result = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=4),
        ).plan_accepted(context_need_decision_id=accepted.decision.id)

        assert result.receipt.plan.status is RequirementPlanStatus.AMBIGUOUS
        assert len(result.receipt.plan.ambiguous_candidate_claim_ids) == 2
        assert result.receipt.derived_context_request_id is None
        assert result.derived_request is None
        assert (
            store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0]
            == request_count
        )
        assert store.context_need_planning_receipt(result.receipt.id) == result.receipt


def test_abstained_planning_receipt_is_durable_without_derived_request(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, accepted = _seed_accepted_need(
            store,
            proposal_query="Which firmware release is installed?",
        )
        result = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=4),
        ).plan_accepted(context_need_decision_id=accepted.decision.id)

        assert result.receipt.plan.status is RequirementPlanStatus.ABSTAINED
        assert result.receipt.plan.reasons == ("no-candidates",)
        assert result.derived_request is None
        assert store.context_need_planning_receipt(result.receipt.id) == result.receipt


def test_rejected_context_need_cannot_be_planned(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        agent = Agent(uuid4(), "Sarmady", T0)
        store.register_agent(agent)
        _observe(
            store,
            subject="system:primary",
            predicate="memory_gb",
            value=64,
        )
        request = ContextRequest(uuid4(), "memory_gb system primary", 600)
        projection = ExactContextCompiler(store).compile(
            request,
            subject="system:primary",
            predicate="memory_gb",
        )
        step = CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=2)).invoke_step(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="need-more",
            adapter=NeedAdapter(
                ContextNeedProposal(
                    "operating_system system primary",
                    "need OS",
                    ("operating system",),
                )
            ),
        )
        rejected = ContextNeedCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=3),
        ).reject(
            context_need_artifact_id=step.artifact.id,
            reason="decline",
            decision_source="test:host-policy",
        )

        with pytest.raises(ValueError, match="only an accepted context need"):
            ContextNeedPlanningCoordinator(store).plan_accepted(
                context_need_decision_id=rejected.decision.id
            )
        assert store.db.execute(
            "SELECT COUNT(*) FROM context_need_planning_receipts"
        ).fetchone()[0] == 0


def test_registration_rejects_plan_if_semantic_universe_changed_since_candidates(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, accepted = _seed_accepted_need(store)
        source = accepted.child_request
        candidates = LexicalCandidateGenerator(store).generate(source)
        plan = ControlledRequirementPlanner().plan(source, candidates)
        assert plan.status is RequirementPlanStatus.RESOLVED
        derived = ControlledRequirementPlanner().derive_request(
            source,
            plan,
            new_request_id=uuid4(),
        )
        receipt = ContextNeedPlanningReceipt(
            id=uuid4(),
            context_need_decision_id=accepted.decision.id,
            planned_at=T0 + timedelta(minutes=4),
            plan=plan,
            derived_context_request_id=derived.id,
        )

        # A later semantic key can change lexical exhaustiveness/uniqueness even
        # when it is unrelated to the previously selected candidate.
        _observe(
            store,
            subject="system:new",
            predicate="serial_number",
            value="ABC",
            minute=4,
        )

        with pytest.raises(ValueError, match="candidate snapshot is stale"):
            store.register_context_need_planning_receipt(
                receipt,
                derived_request=derived,
            )
        assert store.context_need_planning_receipt(receipt.id) is None
        assert store.context_request(derived.id) is None


def test_persisted_planning_receipt_becomes_stale_after_relevant_semantic_change(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, accepted = _seed_accepted_need(store)
        result = ContextNeedPlanningCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=4),
        ).plan_accepted(context_need_decision_id=accepted.decision.id)
        assert not store.context_need_planning_receipt_is_stale(result.receipt.id)

        _observe(
            store,
            subject="system:other",
            predicate="operating_system",
            value="RHEL 10",
            minute=5,
        )
        assert store.context_need_planning_receipt_is_stale(result.receipt.id)


def test_store_rejects_forged_source_lineage_and_planning_causality(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, accepted = _seed_accepted_need(store)
        source = accepted.child_request
        candidates = LexicalCandidateGenerator(store).generate(source)
        plan = ControlledRequirementPlanner().plan(source, candidates)
        derived = ControlledRequirementPlanner().derive_request(
            source,
            plan,
            new_request_id=uuid4(),
        )

        object.__setattr__(plan, "source_request_id", uuid4())
        forged = ContextNeedPlanningReceipt(
            id=uuid4(),
            context_need_decision_id=accepted.decision.id,
            planned_at=T0 + timedelta(minutes=4),
            plan=plan,
            derived_context_request_id=derived.id,
        )
        with pytest.raises(ValueError, match="source request is not the accepted child"):
            store.register_context_need_planning_receipt(
                forged,
                derived_request=derived,
            )

        object.__setattr__(plan, "source_request_id", source.id)
        too_early = ContextNeedPlanningReceipt(
            id=uuid4(),
            context_need_decision_id=accepted.decision.id,
            planned_at=T0 + timedelta(minutes=2),
            plan=plan,
            derived_context_request_id=derived.id,
        )
        with pytest.raises(ValueError, match="cannot precede"):
            store.register_context_need_planning_receipt(
                too_early,
                derived_request=derived,
            )
