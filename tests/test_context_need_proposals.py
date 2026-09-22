from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import (
    CONTEXT_NEED_ARTIFACT_KIND,
    ContextNeedProposal,
    GeneratedArtifact,
    deserialize_context_need_proposal,
    serialize_context_need_proposal,
)
from sarmady.context import ContextRequest, ExactContextCompiler
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import (
    CognitiveRuntime,
    CognitiveStepResult,
    CognitiveStepStatus,
    ModelInput,
    ModelResponse,
    context_need_from_artifact,
)
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 5, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    proposal: ContextNeedProposal
    binding_id: str = "fake:context-need"
    inputs: list[ModelInput] = field(default_factory=list)

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        self.inputs.append(model_input)
        return self.proposal


@dataclass
class TerminalStepAdapter:
    binding_id: str = "fake:terminal-step"

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        return ModelResponse("answer", "done")


@dataclass
class MalformedStepAdapter:
    binding_id: str = "fake:malformed-step"

    def invoke(self, model_input: ModelInput):
        return {"need": "more context"}


def _seed_agent_projection(store: SQLiteCanonicalStore):
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
    request = ContextRequest(
        id=uuid4(),
        query="How much memory is installed?",
        token_budget=1024,
    )
    projection = ExactContextCompiler(store).compile(
        request,
        subject="machine:primary",
        predicate="memory_gb",
    )
    return agent, projection


def test_context_need_proposal_round_trips_with_strict_versioned_payload() -> None:
    raw_requirements = ["current operating system", "supporting evidence"]
    proposal = ContextNeedProposal(
        query="Which operating system is installed?",
        reason="The current projection contains memory capacity but not the OS fact.",
        coverage_requirements=raw_requirements,  # type: ignore[arg-type]
    )
    raw_requirements.append("caller mutation")

    content = serialize_context_need_proposal(proposal)

    assert proposal.coverage_requirements == (
        "current operating system",
        "supporting evidence",
    )
    assert deserialize_context_need_proposal(content) == proposal
    assert serialize_context_need_proposal(deserialize_context_need_proposal(content)) == content


def test_context_need_serialization_revalidates_frozen_value_at_durable_boundary() -> None:
    proposal = ContextNeedProposal("os", "needed")
    object.__setattr__(proposal, "query", 42)

    with pytest.raises(ValueError, match="query is required"):
        serialize_context_need_proposal(proposal)


def test_context_need_proposal_rejects_ambiguous_or_malformed_contracts() -> None:
    with pytest.raises(ValueError, match="query is required"):
        ContextNeedProposal(" ", "needed")
    with pytest.raises(ValueError, match="reason is required"):
        ContextNeedProposal("os", " ")
    with pytest.raises(TypeError, match="iterable of strings"):
        ContextNeedProposal("os", "needed", "not-a-sequence")
    with pytest.raises(ValueError, match="must be unique"):
        ContextNeedProposal("os", "needed", ("fact", "fact"))
    with pytest.raises(ValueError, match="unexpected fields"):
        deserialize_context_need_proposal(
            '{"contract":"ContextNeedProposal:v1","query":"os","reason":"needed","coverage_requirements":[],"budget":1}'
        )
    with pytest.raises(ValueError, match="unsupported"):
        deserialize_context_need_proposal(
            '{"contract":"ContextNeedProposal:v2","query":"os","reason":"needed","coverage_requirements":[]}'
        )


def test_terminal_model_response_cannot_claim_reserved_context_need_kind() -> None:
    with pytest.raises(ValueError, match="reserved"):
        ModelResponse(CONTEXT_NEED_ARTIFACT_KIND, "{}")


def test_invoke_step_persists_context_need_without_creating_context_authority(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    proposal = ContextNeedProposal(
        query="Which operating system is installed?",
        reason="The present context does not contain the operating-system fact.",
        coverage_requirements=("current operating system",),
    )

    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed_agent_projection(store)
        context_requests_before = store.db.execute(
            "SELECT COUNT(*) FROM context_requests"
        ).fetchone()[0]
        frontier_before = store.frontier()
        adapter = NeedAdapter(proposal)

        result = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=1),
        ).invoke_step(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-machine-question",
            adapter=adapter,
        )

        assert result.status is CognitiveStepStatus.NEEDS_CONTEXT
        assert result.context_need == proposal
        assert result.artifact.artifact_kind == CONTEXT_NEED_ARTIFACT_KIND
        assert context_need_from_artifact(result.artifact) == proposal
        assert store.artifact(result.artifact.id) == result.artifact
        assert store.frontier() == frontier_before
        assert (
            store.db.execute("SELECT COUNT(*) FROM context_requests").fetchone()[0]
            == context_requests_before
        )
        assert len(adapter.inputs) == 1
        assert adapter.inputs[0].context_projection_id == projection.id

        invocations = store.invocations_for_agent(agent.id)
        assert len(invocations) == 1
        assert invocations[0].completed_at is not None
        assert invocations[0].error_code is None
        request = store.cognitive_request(invocations[0].cognitive_request_id)
        assert request is not None
        assert request.context_projection_id == projection.id


def test_invoke_step_preserves_terminal_model_response_path(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed_agent_projection(store)

        result = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=1),
        ).invoke_step(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-machine-question",
            adapter=TerminalStepAdapter(),
        )

        assert result.status is CognitiveStepStatus.COMPLETED
        assert result.context_need is None
        assert result.artifact.artifact_kind == "answer"
        assert result.artifact.content == "done"


def test_invoke_step_records_malformed_adapter_output_as_terminal_failure(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed_agent_projection(store)

        with pytest.raises(TypeError, match="ModelResponse or ContextNeedProposal"):
            CognitiveRuntime(
                store,
                clock=lambda: T0 + timedelta(minutes=1),
            ).invoke_step(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-machine-question",
                adapter=MalformedStepAdapter(),
            )

        invocations = store.invocations_for_agent(agent.id)
        assert len(invocations) == 1
        assert invocations[0].completed_at is not None
        assert invocations[0].error_code == "adapter-error:TypeError"
        assert store.db.execute("SELECT COUNT(*) FROM generated_artifacts").fetchone()[0] == 0


def test_mutated_context_need_output_fails_invocation_before_artifact_persistence(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    proposal = ContextNeedProposal("os", "needed")
    object.__setattr__(proposal, "reason", 7)

    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed_agent_projection(store)

        with pytest.raises(ValueError, match="reason is required"):
            CognitiveRuntime(
                store,
                clock=lambda: T0 + timedelta(minutes=1),
            ).invoke_step(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-machine-question",
                adapter=NeedAdapter(proposal),
            )

        invocation = store.invocations_for_agent(agent.id)[0]
        assert invocation.error_code == "adapter-error:ValueError"
        assert store.db.execute("SELECT COUNT(*) FROM generated_artifacts").fetchone()[0] == 0


def test_cognitive_step_result_rejects_mismatched_proposal_and_artifact() -> None:
    proposal = ContextNeedProposal("os", "needed")
    other = ContextNeedProposal("kernel", "needed")
    artifact = GeneratedArtifact(
        id=uuid4(),
        invocation_id=uuid4(),
        artifact_kind=CONTEXT_NEED_ARTIFACT_KIND,
        content=serialize_context_need_proposal(proposal),
        created_at=T0,
    )

    with pytest.raises(ValueError, match="does not match"):
        CognitiveStepResult(
            status=CognitiveStepStatus.NEEDS_CONTEXT,
            artifact=artifact,
            context_need=other,
        )


def test_context_need_artifact_rehydration_rejects_wrong_kind_and_bad_payload() -> None:
    wrong_kind = GeneratedArtifact(
        id=uuid4(),
        invocation_id=uuid4(),
        artifact_kind="answer",
        content="done",
        created_at=T0,
    )
    with pytest.raises(ValueError, match="not a context-need"):
        context_need_from_artifact(wrong_kind)

    malformed = GeneratedArtifact(
        id=uuid4(),
        invocation_id=uuid4(),
        artifact_kind=CONTEXT_NEED_ARTIFACT_KIND,
        content="not-json",
        created_at=T0,
    )
    with pytest.raises(ValueError, match="not valid JSON"):
        context_need_from_artifact(malformed)
