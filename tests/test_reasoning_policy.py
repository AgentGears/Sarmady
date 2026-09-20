from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import (
    COMPACT_V1,
    DIRECT_V1,
    FULL_V1,
    ReasoningMode,
    ReasoningPolicy,
    ReasoningRequirement,
)
from sarmady.context import ContextRequest, ExactContextCompiler
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput, ModelResponse
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@dataclass
class PolicyRecordingAdapter:
    binding_id: str = "fake:policy-aware"
    inputs: list[ModelInput] = field(default_factory=list)

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        self.inputs.append(model_input)
        mode = (
            model_input.reasoning_policy.mode.value
            if model_input.reasoning_policy is not None
            else "NONE"
        )
        return ModelResponse("answer", mode)


def _seed(store: SQLiteCanonicalStore):
    agent = Agent(uuid4(), "Sarmady", T0)
    store.register_agent(agent)
    EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate="memory_gb",
        value=64,
        source_ref="user:statement",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )
    projection = ExactContextCompiler(store).compile(
        ContextRequest(uuid4(), "How much RAM?", 1024),
        subject="machine:primary",
        predicate="memory_gb",
    )
    return agent, projection


def test_builtin_policies_preserve_reasoning_engine_lineage_and_structure() -> None:
    assert DIRECT_V1.mode is ReasoningMode.DIRECT
    assert DIRECT_V1.stages == ()
    assert DIRECT_V1.source_sha256 == (
        "66aaf0b5825eef6df78f9ab6d0d3d59ba0ee32f91b71a11503d6cc1c6542cfdc"
    )

    assert COMPACT_V1.mode is ReasoningMode.COMPACT
    assert COMPACT_V1.stages == (
        "PROBLEM",
        "FIRST_PRINCIPLE",
        "MECHANISM",
        "EVIDENCE",
        "SOLUTION",
    )
    assert COMPACT_V1.source_sha256 == (
        "8e9d66f50c4afaa10f0df58c5c2b11fd6c30d8600d7246c2a0aea63c71a83bd4"
    )

    assert FULL_V1.mode is ReasoningMode.FULL
    assert FULL_V1.stages == (
        "OBSERVE",
        "DIAGNOSE",
        "DERIVE",
        "HYPOTHESIZE",
        "PREDICT",
        "TEST",
        "REVISE",
        "ENGINEER",
    )
    assert FULL_V1.source_sha256 == (
        "e5e5556dc09ae25b7b84aae05a3a4c921c24751645bd9e965cc506fc9e42df2d"
    )
    assert "71c69fcf0b5fc3d7b89497f98ddc1755ead5f6c2" in FULL_V1.source_ref
    assert FULL_V1.fingerprint.startswith("sha256:")
    assert COMPACT_V1.fingerprint != FULL_V1.fingerprint


def test_reasoning_policy_registration_is_immutable_and_does_not_move_epistemic_frontier(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        frontier = store.frontier()
        registered = store.register_reasoning_policy(COMPACT_V1, registered_at=T0)
        assert registered == COMPACT_V1
        assert store.reasoning_policy(COMPACT_V1.id) == COMPACT_V1
        assert store.reasoning_policy_fingerprint(COMPACT_V1.id) == COMPACT_V1.fingerprint
        assert store.frontier() == frontier

        # Idempotent registration of the exact same definition is allowed.
        assert (
            store.register_reasoning_policy(
                COMPACT_V1, registered_at=T0 + timedelta(minutes=1)
            )
            == COMPACT_V1
        )
        assert store.frontier() == frontier

        conflicting = ReasoningPolicy(
            id=COMPACT_V1.id,
            version="1",
            mode=ReasoningMode.COMPACT,
            stages=COMPACT_V1.stages,
            requirements=COMPACT_V1.requirements
            + (
                ReasoningRequirement(
                    "silently_changed_meaning",
                    "This requirement must not be allowed to rebind an existing policy id.",
                ),
            ),
            source_ref=COMPACT_V1.source_ref,
            source_sha256=COMPACT_V1.source_sha256,
        )
        with pytest.raises(ValueError, match="already bound to different semantics"):
            store.register_reasoning_policy(
                conflicting,
                registered_at=T0 + timedelta(minutes=2),
            )


def test_runtime_passes_structured_policy_and_rehydrates_it_after_restart(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    adapter_a = PolicyRecordingAdapter("fake:model-a")

    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed(store)
        frontier = store.frontier()
        artifact = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=1),
        ).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-current-memory",
            adapter=adapter_a,
            reasoning_policy=COMPACT_V1,
        )
        assert artifact.content == "COMPACT"
        assert store.frontier() == frontier
        model_input = adapter_a.inputs[0]
        assert model_input.reasoning_policy == COMPACT_V1
        assert model_input.reasoning_policy_id == COMPACT_V1.id
        assert model_input.reasoning_policy_fingerprint == COMPACT_V1.fingerprint

    adapter_b = PolicyRecordingAdapter("fake:model-b")
    with SQLiteCanonicalStore(path) as reopened:
        assert reopened.reasoning_policy(COMPACT_V1.id) == COMPACT_V1
        frontier = reopened.frontier()
        artifact = CognitiveRuntime(
            reopened,
            clock=lambda: T0 + timedelta(minutes=2),
        ).invoke(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-current-memory",
            adapter=adapter_b,
            reasoning_policy_id=COMPACT_V1.id,
        )
        assert artifact.content == "COMPACT"
        assert reopened.frontier() == frontier
        assert adapter_b.inputs[0].reasoning_policy == COMPACT_V1

        invocations = reopened.invocations_for_agent(agent.id)
        latest_request = reopened.cognitive_request(invocations[-1].cognitive_request_id)
        assert latest_request is not None
        assert latest_request.reasoning_policy_id == COMPACT_V1.id


def test_unknown_reasoning_policy_id_is_rejected_before_request_admission(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed(store)
        with pytest.raises(ValueError, match="unknown reasoning policy"):
            CognitiveRuntime(store, clock=lambda: T0 + timedelta(minutes=1)).invoke(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-current-memory",
                adapter=PolicyRecordingAdapter(),
                reasoning_policy_id="missing:policy:v1",
            )
        count = store.db.execute("SELECT COUNT(*) FROM cognitive_requests").fetchone()[0]
        assert count == 0


def test_policy_object_and_policy_id_cannot_disagree(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed(store)
        with pytest.raises(ValueError, match="different policies"):
            CognitiveRuntime(store).invoke(
                agent_id=agent.id,
                context_projection_id=projection.id,
                operation="answer-current-memory",
                adapter=PolicyRecordingAdapter(),
                reasoning_policy=COMPACT_V1,
                reasoning_policy_id=FULL_V1.id,
            )
