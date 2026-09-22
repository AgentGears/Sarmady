from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sarmady.cognition import ContextNeedProposal
from sarmady.context import ContextNeedCoordinator, ContextRequest, ExactContextCompiler
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.storage.sqlite.schema import SCHEMA_VERSION


T0 = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    binding_id: str = "fake:v6-upgrade"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return ContextNeedProposal(
            "Which operating system is installed?",
            "Need OS context after upgrade.",
            ("current operating system",),
        )


def test_v6_store_without_decision_table_upgrades_and_can_decide_existing_need(tmp_path) -> None:
    path = tmp_path / "legacy-v6.db"
    with SQLiteCanonicalStore(path) as store:
        agent = Agent(uuid4(), "Sarmady", T0)
        store.register_agent(agent)
        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="test:v6-upgrade",
            observed_at=T0,
            recorded_at=T0,
            valid_from=T0,
        )
        request = ContextRequest(uuid4(), "How much memory is installed?", 512)
        projection = ExactContextCompiler(store).compile(
            request,
            subject="machine:primary",
            predicate="memory_gb",
        )
        step = CognitiveRuntime(
            store,
            clock=lambda: T0 + timedelta(minutes=1),
        ).invoke_step(
            agent_id=agent.id,
            context_projection_id=projection.id,
            operation="answer-machine-question",
            adapter=NeedAdapter(),
        )
        artifact_id = step.artifact.id

    legacy = sqlite3.connect(path)
    try:
        legacy.execute("DROP TABLE context_need_decisions")
        legacy.execute("PRAGMA user_version = 6")
        legacy.commit()
    finally:
        legacy.close()

    with SQLiteCanonicalStore(path) as upgraded:
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        table = upgraded.db.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='context_need_decisions'"
        ).fetchone()
        assert table is not None

        result = ContextNeedCoordinator(
            upgraded,
            clock=lambda: T0 + timedelta(minutes=2),
        ).reject(
            context_need_artifact_id=artifact_id,
            reason="upgrade preserves proposal provenance",
            decision_source="test:v6-upgrade",
        )
        assert upgraded.context_need_decision(result.decision.id) == result.decision
