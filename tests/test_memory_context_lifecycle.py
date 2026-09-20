from datetime import UTC, datetime, timedelta

from sarmady.context import ContextRequest, CoverageStatus, ExactContextCompiler
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.memory import MemoryLifecycle, MemoryLifecycleEventKind
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def _seed(store: SQLiteCanonicalStore):
    return EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate="memory_gb",
        value=64,
        source_ref="user:statement",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )


def test_memory_seen_used_and_lifecycle_are_separate_and_invalidate_only_when_needed(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim = _seed(store)
        memory = store.memory_entry_for_target("Claim", claim.id)
        assert memory is not None
        assert memory.lifecycle is MemoryLifecycle.ACTIVE
        events = store.memory_lifecycle_events(memory.id)
        assert [event.event_kind for event in events] == [MemoryLifecycleEventKind.CREATED]

        projection = ExactContextCompiler(store).compile(
            ContextRequest(claim.id, "current RAM", 512),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert not store.projection_is_stale(projection.id)

        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.SEEN,
            occurred_at=T0 + timedelta(minutes=1),
            source="context-retrieval",
        )
        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.SEEN,
            occurred_at=T0 + timedelta(minutes=2),
            source="context-retrieval",
        )
        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.USED,
            occurred_at=T0 + timedelta(minutes=3),
            source="cognitive-runtime",
        )
        assert store.memory_access_counts(memory.id) == (2, 1)
        assert not store.projection_is_stale(projection.id)

        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.ARCHIVED,
            occurred_at=T0 + timedelta(minutes=4),
            source="memory-maintenance",
            reason="cold",
        )
        assert store.projection_is_stale(projection.id)
        archived = store.memory_entry(memory.id)
        assert archived is not None and archived.lifecycle is MemoryLifecycle.ARCHIVED

        blocked = ExactContextCompiler(store).compile(
            ContextRequest(claim.id, "current RAM", 512),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert blocked.coverage_status is CoverageStatus.INSUFFICIENT
        assert any("claim-memory-not-active" in gap for gap in blocked.unresolved_gaps)
        assert claim.id in blocked.omitted_refs
        assert all(item.ref_id != claim.id for item in blocked.items)

        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.RESTORED,
            occurred_at=T0 + timedelta(minutes=5),
            source="memory-maintenance",
        )
        assert store.projection_is_stale(blocked.id)
        restored = ExactContextCompiler(store).compile(
            ContextRequest(claim.id, "current RAM", 512),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert restored.coverage_status is CoverageStatus.COMPLETE


def test_memory_lifecycle_materialization_rebuilds_from_event_history(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim = _seed(store)
        memory = store.memory_entry_for_target("Claim", claim.id)
        assert memory is not None

        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.ARCHIVED,
            occurred_at=T0 + timedelta(minutes=1),
            source="memory-maintenance",
        )
        archived = store.memory_entry(memory.id)
        assert archived is not None and archived.lifecycle is MemoryLifecycle.ARCHIVED

        store.db.execute(
            "UPDATE memory_entries SET lifecycle = ? WHERE id = ?",
            (MemoryLifecycle.ACTIVE.value, str(memory.id)),
        )
        corrupted = store.memory_entry(memory.id)
        assert corrupted is not None and corrupted.lifecycle is MemoryLifecycle.ACTIVE

        assert store.rebuild_memory_lifecycle_states() == 1
        repaired = store.memory_entry(memory.id)
        assert repaired is not None and repaired.lifecycle is MemoryLifecycle.ARCHIVED
