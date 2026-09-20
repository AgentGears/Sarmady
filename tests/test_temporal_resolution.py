from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.context import ContextRequest, CoverageStatus, ExactContextCompiler
from sarmady.epistemic import ClaimRelationKind, ResolutionStatus
from sarmady.epistemic.service import EpistemicMemoryService
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


def test_valid_time_and_knowledge_time_are_distinct(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        claim_64 = _seed(store)
        claim_96 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="user:later-observation",
            observed_at=T0 + timedelta(hours=1),
            recorded_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(minutes=30),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )

        as_known = store.claim_as_known_at(
            "machine:primary",
            "memory_gb",
            T0 + timedelta(minutes=45),
        )
        assert as_known.status is ResolutionStatus.RESOLVED
        assert as_known.operative_claim_id == claim_64.id
        assert as_known.value == 64

        valid_later = store.claim_valid_at(
            "machine:primary",
            "memory_gb",
            T0 + timedelta(minutes=45),
        )
        assert valid_later.operative_claim_id == claim_96.id
        assert valid_later.value == 96

        valid_earlier = store.claim_valid_at(
            "machine:primary",
            "memory_gb",
            T0 + timedelta(minutes=15),
        )
        assert valid_earlier.operative_claim_id == claim_64.id
        assert valid_earlier.value == 64

        bounded = store.resolved_state(
            "machine:primary",
            "memory_gb",
            known_at=T0 + timedelta(minutes=45),
            valid_at=T0 + timedelta(minutes=45),
        )
        assert bounded.operative_claim_id == claim_64.id


def test_claim_heads_can_be_destroyed_and_rebuilt_from_canonical_history(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        _seed(store)
        claim_96 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="user:upgrade",
            observed_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(minutes=30),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )
        history_before = store.claim_history("machine:primary", "memory_gb")

        store.db.execute("DELETE FROM claim_heads")
        assert store.current_claim("machine:primary", "memory_gb") is None

        assert store.rebuild_claim_heads() == 1
        current = store.current_claim("machine:primary", "memory_gb")
        assert current is not None
        assert current.id == claim_96.id
        assert store.claim_history("machine:primary", "memory_gb") == history_before


def test_contradiction_is_contested_state_and_context_carries_counterevidence(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        claim_64 = _seed(store)
        claim_32 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=32,
            source_ref="inventory:scan",
            observed_at=T0 + timedelta(minutes=5),
            recorded_at=T0 + timedelta(minutes=5),
            valid_from=T0,
            relation_kind=ClaimRelationKind.CONTRADICTS,
        )

        current = store.current_claim("machine:primary", "memory_gb")
        assert current is not None and current.id == claim_64.id

        resolved = store.resolved_state("machine:primary", "memory_gb")
        assert resolved.status is ResolutionStatus.CONTESTED
        assert resolved.operative_claim_id == claim_64.id
        assert resolved.competing_claim_ids == (claim_32.id,)
        assert len(resolved.conflict_relation_ids) == 1

        projection = ExactContextCompiler(store).compile(
            ContextRequest(claim_64.id, "How much RAM?", 1024),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert projection.coverage_status is CoverageStatus.COMPLETE
        assert projection.conflict_refs == resolved.conflict_relation_ids
        claim_items = [i for i in projection.items if i.ref_type == "Claim"]
        assert [i.ref_id for i in claim_items] == [claim_64.id, claim_32.id]
        assert [i.role for i in claim_items] == ["essential_now", "counterevidence"]


def test_future_valid_claim_is_rejected_until_scheduled_activation_exists(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        with pytest.raises(ValueError, match="future-valid"):
            EpistemicMemoryService(store).observe_claim(
                subject="machine:primary",
                predicate="memory_gb",
                value=128,
                source_ref="user:plan",
                observed_at=T0,
                recorded_at=T0,
                valid_from=T0 + timedelta(days=1),
            )


def test_context_request_honors_knowledge_and_valid_time(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        claim_64 = _seed(store)
        claim_96 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="user:later-observation",
            observed_at=T0 + timedelta(hours=1),
            recorded_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(minutes=30),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )

        historical_knowledge = ExactContextCompiler(store).compile(
            ContextRequest(
                uuid4(),
                "what did we know at 09:45?",
                512,
                known_at=T0 + timedelta(minutes=45),
            ),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert historical_knowledge.items[0].ref_id == claim_64.id

        historical_world = ExactContextCompiler(store).compile(
            ContextRequest(
                uuid4(),
                "what was valid at 09:45?",
                512,
                valid_at=T0 + timedelta(minutes=45),
            ),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert historical_world.items[0].ref_id == claim_96.id
