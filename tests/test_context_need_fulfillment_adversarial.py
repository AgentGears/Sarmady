from __future__ import annotations

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
    ContextRequest,
    ExactContextCompiler,
    ExactCoverageRequirement,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput, ModelResponse
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 11, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    binding_id: str = "fake:adversarial-need"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return ContextNeedProposal(
            "Which operating system is installed?",
            "The current projection does not contain the OS fact.",
            ("current operating system",),
        )


@dataclass
class TerminalAdapter:
    binding_id: str = "fake:terminal"

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        return ModelResponse("answer", "done")


def _seed(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate="memory_gb",
        value=64,
        source_ref="test:adversarial",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    parent = ContextRequest(
        id=uuid4(),
        query="How much memory is installed?",
        token_budget=1024,
        latency_budget_ms=2000,
        goal_ref=uuid4(),
        task_ref=uuid4(),
        known_at=T0 + timedelta(minutes=1),
        valid_at=T0 + timedelta(minutes=1),
    )
    projection = ExactContextCompiler(store).compile(
        parent,
        subject="machine:primary",
        predicate="memory_gb",
    )
    return agent, parent, projection


def _seed_need(store: SQLiteCanonicalStore):
    agent, parent, projection = _seed(store)
    result = CognitiveRuntime(
        store,
        clock=lambda: T0 + timedelta(minutes=2),
    ).invoke_step(
        agent_id=agent.id,
        context_projection_id=projection.id,
        operation="answer-machine-question",
        adapter=NeedAdapter(),
    )
    invocation = store.invocations_for_agent(agent.id)[0]
    cognitive = store.cognitive_request(invocation.cognitive_request_id)
    assert cognitive is not None
    proposal = ContextNeedProposal(
        "Which operating system is installed?",
        "The current projection does not contain the OS fact.",
        ("current operating system",),
    )
    return parent, projection, proposal, result.artifact, invocation, cognitive


def _decision(parent, projection, artifact, invocation, cognitive, child):
    return ContextNeedDecision(
        id=uuid4(),
        context_need_artifact_id=artifact.id,
        decision=ContextNeedDecisionKind.ACCEPTED,
        decided_at=T0 + timedelta(minutes=3),
        reason="accepted by host",
        decision_source="test:host-policy",
        parent_invocation_id=invocation.id,
        parent_cognitive_request_id=cognitive.id,
        parent_context_projection_id=projection.id,
        parent_context_request_id=parent.id,
        child_context_request_id=child.id,
    )


def test_non_context_artifact_cannot_be_decided_as_context_need(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        agent, _, projection = _seed(store)
        artifact = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=2),
        ).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-machine-question",
            adapter=TerminalAdapter(),
        )

        with pytest.raises(ValueError, match="not a context-need proposal"):
            ContextNeedCoordinator(store).reject(
                context_need_artifact_id=artifact.id,
                reason="must not reinterpret ordinary output",
                decision_source="test:host-policy",
            )
        assert store.context_need_decision_for_artifact(artifact.id) is None


def test_malformed_persisted_context_need_payload_is_rejected_at_decision_boundary(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, _, artifact, _, _ = _seed_need(store)
        store.db.execute(
            "UPDATE generated_artifacts SET content = ? WHERE id = ?",
            ('{"contract":"ContextNeedProposal:v1"}', str(artifact.id)),
        )

        with pytest.raises(ValueError, match="unexpected fields"):
            ContextNeedCoordinator(store).reject(
                context_need_artifact_id=artifact.id,
                reason="corrupt payload must fail closed",
                decision_source="test:host-policy",
            )
        assert store.context_need_decision_for_artifact(artifact.id) is None


def test_failed_invocation_cannot_supply_a_decidable_context_need(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        _, _, _, artifact, invocation, _ = _seed_need(store)
        store.db.execute(
            "UPDATE model_invocations SET error_code = 'tampered-failure' WHERE id = ?",
            (str(invocation.id),),
        )

        with pytest.raises(ValueError, match="successful invocation"):
            ContextNeedCoordinator(store).reject(
                context_need_artifact_id=artifact.id,
                reason="failed source must not authorize follow-up",
                decision_source="test:host-policy",
            )
        assert store.context_need_decision_for_artifact(artifact.id) is None


def test_direct_store_cannot_smuggle_exact_requirements_into_accepted_child(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        parent, projection, proposal, artifact, invocation, cognitive = _seed_need(store)
        child = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=512,
            latency_budget_ms=1000,
            goal_ref=parent.goal_ref,
            task_ref=parent.task_ref,
            coverage_requirements=proposal.coverage_requirements,
            exact_requirements=(
                ExactCoverageRequirement(
                    key="model-picked-address",
                    subject="machine:primary",
                    predicate="operating_system",
                ),
            ),
            known_at=parent.known_at,
            valid_at=parent.valid_at,
        )
        decision = _decision(
            parent,
            projection,
            artifact,
            invocation,
            cognitive,
            child,
        )

        with pytest.raises(ValueError, match="cannot directly create exact semantic requirements"):
            store.register_context_need_decision(decision, child_request=child)
        assert store.context_request(child.id) is None


def test_direct_store_requires_parent_task_and_temporal_lineage(tmp_path) -> None:
    with SQLiteCanonicalStore(tmp_path / "sarmady.db") as store:
        parent, projection, proposal, artifact, invocation, cognitive = _seed_need(store)
        altered_task = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=512,
            latency_budget_ms=1000,
            goal_ref=parent.goal_ref,
            task_ref=uuid4(),
            coverage_requirements=proposal.coverage_requirements,
            known_at=parent.known_at,
            valid_at=parent.valid_at,
        )
        with pytest.raises(ValueError, match="inherit parent goal/task lineage"):
            store.register_context_need_decision(
                _decision(
                    parent,
                    projection,
                    artifact,
                    invocation,
                    cognitive,
                    altered_task,
                ),
                child_request=altered_task,
            )
        assert store.context_request(altered_task.id) is None

        altered_time = ContextRequest(
            id=uuid4(),
            query=proposal.query,
            token_budget=512,
            latency_budget_ms=1000,
            goal_ref=parent.goal_ref,
            task_ref=parent.task_ref,
            coverage_requirements=proposal.coverage_requirements,
            known_at=T0 + timedelta(minutes=10),
            valid_at=parent.valid_at,
        )
        with pytest.raises(ValueError, match="inherit parent temporal selectors"):
            store.register_context_need_decision(
                _decision(
                    parent,
                    projection,
                    artifact,
                    invocation,
                    cognitive,
                    altered_time,
                ),
                child_request=altered_time,
            )
        assert store.context_request(altered_time.id) is None


def test_context_need_decision_rejects_blank_audit_fields() -> None:
    common = dict(
        id=uuid4(),
        context_need_artifact_id=uuid4(),
        decision=ContextNeedDecisionKind.REJECTED,
        decided_at=T0,
        parent_invocation_id=uuid4(),
        parent_cognitive_request_id=uuid4(),
        parent_context_projection_id=uuid4(),
        parent_context_request_id=uuid4(),
    )
    with pytest.raises(ValueError, match="reason is required"):
        ContextNeedDecision(reason=" ", decision_source="test", **common)
    with pytest.raises(ValueError, match="source is required"):
        ContextNeedDecision(reason="reason", decision_source=" ", **common)
