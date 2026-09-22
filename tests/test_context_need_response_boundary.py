from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.cognition import CONTEXT_NEED_ARTIFACT_KIND
from sarmady.context import ContextRequest, ExactContextCompiler
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput, ModelResponse
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 22, 5, 30, tzinfo=UTC)


@dataclass
class MutatedReservedResponseAdapter:
    binding_id: str = "fake:mutated-reserved-response"

    def invoke(self, model_input: ModelInput) -> ModelResponse:
        response = ModelResponse("answer", "ordinary terminal text")
        object.__setattr__(response, "artifact_kind", CONTEXT_NEED_ARTIFACT_KIND)
        return response


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


@pytest.mark.parametrize("step_api", [False, True])
def test_runtime_revalidates_mutated_model_response_before_reserved_artifact_persistence(
    tmp_path,
    step_api: bool,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        agent, projection = _seed_agent_projection(store)
        runtime = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=1),
        )
        kwargs = dict(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-machine-question",
            adapter=MutatedReservedResponseAdapter(),
        )

        with pytest.raises(ValueError, match="reserved"):
            if step_api:
                runtime.invoke_step(**kwargs)
            else:
                runtime.invoke(**kwargs)

        invocations = store.invocations_for_agent(agent.id)
        assert len(invocations) == 1
        assert invocations[0].completed_at is not None
        assert invocations[0].error_code == "adapter-error:ValueError"
        assert store.db.execute("SELECT COUNT(*) FROM generated_artifacts").fetchone()[0] == 0
