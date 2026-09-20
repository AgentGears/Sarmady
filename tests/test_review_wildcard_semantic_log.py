from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from sarmady.context import ContextProjection, ContextRequest, CoverageStatus
from sarmady.kernel import Agent
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


def test_unproven_projection_is_invalidated_by_generic_semantic_log_write(tmp_path) -> None:
    path = tmp_path / "wildcard-identity.db"
    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(uuid4(), "manual identity-sensitive context", 512)
        frontier = store.frontier()
        projection = ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id=f"sqlite:{frontier}",
            canonical_frontier=str(frontier),
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:test-wildcard-identity",
            compiler_version="external-test",
        )
        assert not store.register_context_projection(
            projection,
            request=request,
        )
        assert not store.projection_is_stale(projection.id)

        # register_agent() advances semantic_log through the generic _log()
        # primitive and has no specialized projection-invalidation hook.
        store.register_agent(Agent(uuid4(), "New Agent", T0))

        assert store.projection_is_stale(projection.id)
        assert (
            store.projection_stale_reason(projection.id)
            == "unproven-lineage-semantic-state-changed"
        )
