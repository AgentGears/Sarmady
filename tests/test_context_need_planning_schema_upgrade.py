from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sarmady.cognition import ContextNeedProposal
from sarmady.context import (
    ContextNeedCoordinator,
    ContextNeedPlanningCoordinator,
    ContextRequest,
    ExactContextCompiler,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.kernel import Agent
from sarmady.runtime import CognitiveRuntime, ModelInput
from sarmady.storage.sqlite import SQLiteCanonicalStore
from sarmady.storage.sqlite.schema import SCHEMA_VERSION


T0 = datetime(2026, 9, 22, 18, 0, tzinfo=UTC)


@dataclass
class NeedAdapter:
    binding_id: str = "fake:v7-planning-upgrade"

    def invoke(self, model_input: ModelInput) -> ContextNeedProposal:
        return ContextNeedProposal(
            "Which operating system is installed on system primary?",
            "Need OS context after upgrade.",
            ("current operating system",),
        )


def _observe(store, subject, predicate, value) -> None:
    EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate=predicate,
        value=value,
        source_ref=f"test:{subject}:{predicate}",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )


def test_v7_store_without_planning_table_upgrades_and_can_plan_existing_acceptance(tmp_path) -> None:
    path = tmp_path / "legacy-v7.db"
    with SQLiteCanonicalStore(path) as store:
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
        accepted = ContextNeedCoordinator(
            store,
            clock=lambda: T0 + timedelta(minutes=2),
        ).accept(
            context_need_artifact_id=step.artifact.id,
            reason="persist v7 acceptance",
            decision_source="test:v7-upgrade",
        )
        decision_id = accepted.decision.id

    legacy = sqlite3.connect(path)
    try:
        legacy.execute("DROP TABLE context_need_planning_receipts")
        legacy.execute("PRAGMA user_version = 7")
        legacy.commit()
    finally:
        legacy.close()

    with SQLiteCanonicalStore(path) as upgraded:
        assert upgraded.db.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        table = upgraded.db.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='context_need_planning_receipts'
            """
        ).fetchone()
        assert table is not None
        assert upgraded.context_need_decision(decision_id) is not None

        result = ContextNeedPlanningCoordinator(
            upgraded,
            clock=lambda: T0 + timedelta(minutes=3),
        ).plan_accepted(context_need_decision_id=decision_id)
        assert upgraded.context_need_planning_receipt(result.receipt.id) == result.receipt
