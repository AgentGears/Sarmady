from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest

from sarmady.cognition import CognitiveRequest, ModelInvocation
from sarmady.context import ContextRequest, ExactContextCompiler
from sarmady.epistemic import ClaimRelationKind
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput, ModelResponse
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@dataclass
class RecordingAdapter:
    binding_id: str
    prefix: str
    inputs: list[ModelInput] = field(default_factory=list)

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        self.inputs.append(model_input)
        claim_items = [item for item in model_input.items if item.ref_type == "Claim"]
        value: Any = claim_items[0].payload["value"] if claim_items else None
        return ModelResponse("answer", f"{self.prefix}:{value}")


@dataclass
class FailingAdapter:
    binding_id: str = "fake:failure"

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        raise RuntimeError("synthetic provider failure")


@dataclass
class MalformedAdapter:
    binding_id: str = "fake:malformed"

    def invoke(self, model_input: ModelInput):
        return "not-a-model-response"


def _seed_agent_claim_projection(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    claim = EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate="memory_gb",
        value=64,
        source_ref="user:statement",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    request = ContextRequest(
        uuid4(),
        "How much RAM does my workstation have?",
        1024,
        coverage_requirements=("current machine memory", "supporting evidence"),
    )
    projection = ExactContextCompiler(store).compile(
        request,
        subject="machine:primary",
        predicate="memory_gb",
    )
    memory = store.memory_entry_for_target("Claim", claim.id)
    assert memory is not None
    return agent, claim, memory, projection


def test_model_binding_can_change_after_restart_without_changing_agent_or_memory(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    adapter_a = RecordingAdapter("fake:model-a", "A")

    with SQLiteCanonicalStore(path) as store:
        agent, claim, memory, projection = _seed_agent_claim_projection(store)
        frontier_before_compute = store.frontier()
        artifact_a = CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=1)).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-current-memory",
            adapter=adapter_a,
        )
        assert artifact_a.content == "A:64"
        assert store.frontier() == frontier_before_compute
        assert len(adapter_a.inputs) == 1
        assert adapter_a.inputs[0].agent_id == agent.id
        assert adapter_a.inputs[0].snapshot_id == projection.snapshot_id
        assert not hasattr(adapter_a.inputs[0], "store")

    adapter_b = RecordingAdapter("fake:model-b", "B")
    with SQLiteCanonicalStore(path) as reopened:
        restored_agent = reopened.agent(agent.id)
        assert restored_agent == agent
        restored_projection = reopened.context_projection(projection.id)
        assert restored_projection == projection
        restored_context_request = reopened.context_request(projection.request_id)
        assert restored_context_request is not None
        assert restored_context_request.query == "How much RAM does my workstation have?"
        assert restored_context_request.coverage_requirements == (
            "current machine memory",
            "supporting evidence",
        )

        restored_claim = reopened.current_claim("machine:primary", "memory_gb")
        assert restored_claim == claim
        restored_memory = reopened.memory_entry(memory.id)
        assert restored_memory == memory

        frontier_before_swap = reopened.frontier()
        artifact_b = CognitiveRuntime(
            reopened, clock=lambda: T0 + timedelta(minutes=2)
        ).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-current-memory",
            adapter=adapter_b,
        )
        assert artifact_b.content == "B:64"
        assert reopened.frontier() == frontier_before_swap

        invocations = reopened.invocations_for_agent(agent.id)
        assert [item.model_binding for item in invocations] == [
            "fake:model-a",
            "fake:model-b",
        ]
        for invocation in invocations:
            request = reopened.cognitive_request(invocation.cognitive_request_id)
            assert request is not None
            assert request.agent_id == agent.id
            assert request.context_projection_id == projection.id

        assert reopened.current_claim("machine:primary", "memory_gb") == claim
        assert reopened.memory_entry(memory.id) == memory
        assert reopened.artifact(artifact_a.id) == artifact_a
        assert reopened.artifact(artifact_b.id) == artifact_b


def test_stale_projection_is_rejected_before_cognitive_request_is_admitted(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, _, _, projection = _seed_agent_claim_projection(store)
        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="user:upgrade",
            observed_at=T0 + timedelta(hours=1),
            recorded_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(hours=1),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )
        assert store.projection_is_stale(projection.id)

        with pytest.raises(ValueError, match="stale context projection"):
            CognitiveRuntime(store, clock=lambda: T0 + timedelta(hours=2)).invoke(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-current-memory",
                adapter=RecordingAdapter("fake:model", "X"),
            )

        count = store.db.execute("SELECT COUNT(*) FROM cognitive_requests").fetchone()[0]
        assert count == 0


def test_projection_is_revalidated_immediately_before_invocation_start(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, _, _, projection = _seed_agent_claim_projection(store)
        request = CognitiveRequest(
            uuid4(),
            agent.id,
            projection.id,
            "answer-current-memory",
            T0 + timedelta(minutes=1),
        )
        store.create_cognitive_request(request)

        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="user:upgrade",
            observed_at=T0 + timedelta(hours=1),
            recorded_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(hours=1),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )

        with pytest.raises(ValueError, match="stale context projection"):
            store.start_model_invocation(
                ModelInvocation(
                    uuid4(),
                    request.id,
                    "fake:model",
                    T0 + timedelta(hours=2),
                )
            )
        assert store.invocations_for_agent(agent.id) == ()


def test_adapter_exception_leaves_durable_terminal_failure_without_artifact(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, _, _, projection = _seed_agent_claim_projection(store)
        runtime = CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=1))
        with pytest.raises(RuntimeError, match="synthetic provider failure"):
            runtime.invoke(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-current-memory",
                adapter=FailingAdapter(),
            )

        invocations = store.invocations_for_agent(agent.id)
        assert len(invocations) == 1
        assert invocations[0].completed_at is not None
        assert invocations[0].error_code == "adapter-error:RuntimeError"
        artifact_count = store.db.execute(
            "SELECT COUNT(*) FROM generated_artifacts"
        ).fetchone()[0]
        assert artifact_count == 0


def test_malformed_adapter_response_is_also_durably_failed(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, _, _, projection = _seed_agent_claim_projection(store)
        runtime = CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=1))
        with pytest.raises(TypeError, match="ModelResponse"):
            runtime.invoke(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-current-memory",
                adapter=MalformedAdapter(),
            )

        invocation = store.invocations_for_agent(agent.id)[0]
        assert invocation.completed_at is not None
        assert invocation.error_code == "adapter-error:TypeError"


def test_context_request_id_cannot_be_reused_with_different_semantics(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, claim, _, projection = _seed_agent_claim_projection(store)
        assert agent is not None
        conflicting = ContextRequest(
            projection.request_id,
            "A different question with the same id",
            1024,
        )
        with pytest.raises(ValueError, match="different semantics"):
            ExactContextCompiler(store).compile(
                conflicting,
                subject="machine:primary",
                predicate="memory_gb",
            )
        assert store.context_request(projection.request_id) is not None
        assert store.current_claim("machine:primary", "memory_gb") == claim
