from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sarmady.context import ContextProjection, ContextRequest, CoverageStatus
from sarmady.kernel import Agent
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize("lookup_name", ["claim", "evidence"])
def test_absent_context_object_lookup_forces_conservative_dependency(
    tmp_path,
    lookup_name: str,
) -> None:
    path = tmp_path / f"absent-{lookup_name}.db"
    missing_id = uuid4()

    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(uuid4(), f"missing {lookup_name}", 512)
        with store.context_read_snapshot() as snapshot:
            lookup = getattr(snapshot, lookup_name)
            assert lookup(missing_id) is None
            projection = ContextProjection(
                id=uuid4(),
                request_id=request.id,
                snapshot_id=f"sqlite:{snapshot.frontier}",
                canonical_frontier=str(snapshot.frontier),
                items=(),
                coverage_status=CoverageStatus.INSUFFICIENT,
                manifest_digest=f"sha256:absent-{lookup_name}",
                compiler_version="test",
            )

        assert "semantic:*" in snapshot.dependency_keys

        # Any semantic advance can invalidate a negative object-presence result.
        # The conservative wildcard therefore makes the registration stale when
        # state moves after the captured snapshot.
        store.register_agent(Agent(uuid4(), "race", T0))
        stale = store.register_context_projection(
            projection,
            request=request,
            dependency_capture=snapshot,
        )
        assert stale
        assert (
            store.projection_stale_reason(projection.id)
            == "dependency-changed-before-registration"
        )


def test_absent_memory_target_lookup_forces_conservative_dependency(tmp_path) -> None:
    path = tmp_path / "absent-memory-target.db"
    target_id = uuid4()

    with SQLiteCanonicalStore(path) as store:
        with store.context_read_snapshot() as snapshot:
            assert snapshot.memory_entry_for_target("Claim", target_id) is None
            assert not snapshot.is_active_memory_target("Claim", target_id)

        assert "semantic:*" in snapshot.dependency_keys


def test_context_snapshot_proxy_rejects_all_semantic_reads_after_close(tmp_path) -> None:
    path = tmp_path / "closed-context-snapshot.db"
    object_id = uuid4()

    with SQLiteCanonicalStore(path) as store:
        with store.context_read_snapshot() as snapshot:
            frontier = snapshot.frontier

        assert snapshot.frontier == frontier
        assert snapshot.dependency_keys == ()

        # Once the pinned SQLite transaction has closed, the proxy is only a
        # completed lineage receipt. It must not perform any read against the
        # now-current database while still carrying the old frontier label.
        with pytest.raises(RuntimeError, match="context read snapshot is closed"):
            snapshot.resolved_state("subject", "predicate")
        with pytest.raises(RuntimeError, match="context read snapshot is closed"):
            snapshot.claim(object_id)
        with pytest.raises(RuntimeError, match="context read snapshot is closed"):
            snapshot.evidence(object_id)
        with pytest.raises(RuntimeError, match="context read snapshot is closed"):
            snapshot.memory_entry_for_target("Claim", object_id)
        with pytest.raises(RuntimeError, match="context read snapshot is closed"):
            snapshot.is_active_memory_target("Claim", object_id)


def test_context_lineage_receipt_cannot_be_relabelled_to_newer_frontier(tmp_path) -> None:
    path = tmp_path / "sealed-context-lineage.db"

    with SQLiteCanonicalStore(path) as store:
        request = ContextRequest(uuid4(), "sealed lineage", 512)
        with store.context_read_snapshot() as snapshot:
            original_frontier = snapshot.frontier

        store.register_agent(Agent(uuid4(), "intervening-write", T0))
        newer_frontier = store.frontier()
        assert newer_frontier > original_frontier

        # The receipt exposes a read-only frontier derived from store-owned
        # capture state. Public reassignment cannot relabel old reads.
        with pytest.raises(AttributeError):
            snapshot.frontier = newer_frontier  # type: ignore[misc]
        assert snapshot.frontier == original_frontier

        relabelled_projection = ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id=f"sqlite:{newer_frontier}",
            canonical_frontier=str(newer_frontier),
            items=(),
            coverage_status=CoverageStatus.INSUFFICIENT,
            manifest_digest="sha256:sealed-lineage",
            compiler_version="test",
        )

        with pytest.raises(
            ValueError,
            match="capture frontier does not match projection frontier",
        ):
            store.register_context_projection(
                relabelled_projection,
                request=request,
                dependency_capture=snapshot,
            )

        assert store.context_request(request.id) is None
        assert store.context_projection(relabelled_projection.id) is None
