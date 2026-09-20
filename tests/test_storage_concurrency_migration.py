from datetime import UTC, datetime, timedelta
import sqlite3
from uuid import uuid4

import pytest

from sarmady.epistemic import Claim, ClaimRelation, ClaimRelationKind, Evidence, Event
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.memory import MemoryEntry, MemoryKind, MemoryLifecycleEventKind
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


def test_read_snapshot_cannot_mix_frontier_with_newer_concurrent_state(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as seed_store:
        _seed(seed_store)

    with SQLiteCanonicalStore(path) as reader, SQLiteCanonicalStore(path) as writer:
        with reader.read_snapshot() as frontier:
            before = reader.current_claim("machine:primary", "memory_gb")
            assert before is not None and before.value == 64

            EpistemicMemoryService(writer).observe_claim(
                subject="machine:primary",
                predicate="memory_gb",
                value=96,
                source_ref="user:upgrade",
                observed_at=T0 + timedelta(hours=1),
                valid_from=T0 + timedelta(minutes=30),
                relation_kind=ClaimRelationKind.SUPERSEDES,
            )

            # The reader is still pinned to the snapshot established at frontier.
            during = reader.current_claim("machine:primary", "memory_gb")
            assert during is not None and during.value == 64
            assert reader.frontier() == frontier

        after = reader.current_claim("machine:primary", "memory_gb")
        assert after is not None and after.value == 96



def test_legacy_memory_admission_gets_created_event_during_schema_v3_upgrade(tmp_path) -> None:
    path = tmp_path / "legacy.db"
    memory_id = uuid4()
    target_id = uuid4()
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE semantic_log (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL,
            ref_id TEXT NOT NULL,
            recorded_at TEXT NOT NULL
        );
        CREATE TABLE memory_entries (
            id TEXT PRIMARY KEY,
            target_type TEXT NOT NULL,
            target_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            created_at TEXT NOT NULL,
            lifecycle TEXT NOT NULL
        );
        """
    )
    db.execute(
        "INSERT INTO memory_entries VALUES (?, 'Claim', ?, 'SEMANTIC', ?, 'ACTIVE')",
        (str(memory_id), str(target_id), T0.isoformat()),
    )
    db.execute("PRAGMA user_version = 2")
    db.commit()
    db.close()

    with SQLiteCanonicalStore(path) as store:
        assert store.db.execute("PRAGMA user_version").fetchone()[0] == 4
        events = store.memory_lifecycle_events(memory_id)
        assert len(events) == 1
        assert events[0].event_kind is MemoryLifecycleEventKind.CREATED
        assert events[0].source == "schema-migration-v2"
        assert store.rebuild_memory_lifecycle_states() == 1
        tables = {
            row[0]
            for row in store.db.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "reasoning_policies" in tables



def test_stale_writer_cannot_commit_revision_against_obsolete_head(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim_64 = _seed(store)

        # Build a revision proposal against C1 but intentionally delay commit.
        stale_event = Event(
            uuid4(),
            "OBSERVATION",
            T0 + timedelta(hours=2),
            T0 + timedelta(hours=2),
            {},
        )
        stale_evidence = Evidence(
            uuid4(),
            stale_event.id,
            "stale-writer",
            T0 + timedelta(hours=2),
        )
        stale_claim = Claim(
            uuid4(),
            "machine:primary",
            "memory_gb",
            128,
            T0 + timedelta(hours=2),
            (stale_evidence.id,),
            valid_from=T0 + timedelta(hours=2),
        )
        stale_memory = MemoryEntry(
            uuid4(),
            "Claim",
            stale_claim.id,
            MemoryKind.SEMANTIC,
            T0 + timedelta(hours=2),
        )
        stale_relation = ClaimRelation(
            uuid4(),
            stale_claim.id,
            claim_64.id,
            ClaimRelationKind.SUPERSEDES,
            T0 + timedelta(hours=2),
        )

        # Another writer advances the head first.
        winning = EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="winning-writer",
            observed_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(hours=1),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )

        with pytest.raises(ValueError, match="locked current claim"):
            store.commit_claim_bundle(
                event=stale_event,
                evidence=stale_evidence,
                claim=stale_claim,
                memory=stale_memory,
                relation=stale_relation,
            )

        current = store.current_claim("machine:primary", "memory_gb")
        assert current is not None and current.id == winning.id
        assert store.claim(stale_claim.id) is None
        assert store.evidence(stale_evidence.id) is None



def test_record_time_cannot_precede_observation_time(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        with pytest.raises(ValueError, match="cannot precede"):
            EpistemicMemoryService(store).observe_claim(
                subject="machine:primary",
                predicate="memory_gb",
                value=64,
                source_ref="user:statement",
                observed_at=T0 + timedelta(minutes=1),
                recorded_at=T0,
            )


def test_snapshot_frontier_cannot_label_unpinned_current_state(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _seed(store)
        old_frontier = store.frontier()
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

        with pytest.raises(RuntimeError, match="pinned transaction"):
            store.resolved_state(
                "machine:primary",
                "memory_gb",
                snapshot_frontier=old_frontier,
            )

        with store.read_snapshot() as frontier:
            with pytest.raises(RuntimeError, match="does not match"):
                store.resolved_state(
                    "machine:primary",
                    "memory_gb",
                    snapshot_frontier=frontier - 1,
                )


def test_backdated_revision_cannot_create_impossible_knowledge_lineage(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        first = EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="user:statement",
            observed_at=T0 + timedelta(hours=1),
            recorded_at=T0 + timedelta(hours=1),
            valid_from=T0,
        )

        with pytest.raises(ValueError, match="cannot precede the locked current claim"):
            EpistemicMemoryService(store).observe_claim(
                subject="machine:primary",
                predicate="memory_gb",
                value=96,
                source_ref="backdated-correction",
                observed_at=T0,
                recorded_at=T0,
                valid_from=T0,
                relation_kind=ClaimRelationKind.SUPERSEDES,
            )

        current = store.current_claim("machine:primary", "memory_gb")
        assert current is not None and current.id == first.id
        assert [claim.id for claim in store.claim_history("machine:primary", "memory_gb")] == [first.id]


def test_event_contract_rejects_recording_before_occurrence() -> None:
    with pytest.raises(ValueError, match="cannot precede occurred_at"):
        Event(
            uuid4(),
            "OBSERVATION",
            T0 + timedelta(minutes=1),
            T0,
            {},
        )
