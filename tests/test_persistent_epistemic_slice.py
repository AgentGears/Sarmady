from datetime import UTC, datetime, timedelta

from sarmady.context import ContextRequest, CoverageStatus, ExactContextCompiler
from sarmady.epistemic import ClaimRelationKind
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 9, 0, tzinfo=UTC)


def test_claim_survives_reopen_and_compiles_bounded_context(tmp_path) -> None:
    path = tmp_path / "sarmady.db"

    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        claim_64 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="user:statement",
            observed_at=T0,
            payload={"utterance": "My workstation has 64 GB RAM."},
            valid_from=T0,
        )
        frontier_before_restart = store.frontier()
        assert frontier_before_restart > 0

    with SQLiteCanonicalStore(path) as reopened:
        current = reopened.current_claim("machine:primary", "memory_gb")
        assert current is not None
        assert current.id == claim_64.id
        assert current.value == 64

        request = ContextRequest(
            id=claim_64.id,
            query="How much RAM does my workstation have?",
            token_budget=1024,
            coverage_requirements=("current machine memory", "supporting evidence"),
        )
        projection = ExactContextCompiler(reopened).compile(
            request,
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert projection.coverage_status is CoverageStatus.COMPLETE
        assert projection.snapshot_id == f"sqlite:{projection.canonical_frontier}"
        assert [item.ref_type for item in projection.items] == ["Claim", "Evidence"]
        assert projection.items[0].ref_id == claim_64.id


def test_supersession_preserves_history_and_moves_only_materialized_head(tmp_path) -> None:
    path = tmp_path / "sarmady.db"

    with SQLiteCanonicalStore(path) as store:
        service = EpistemicMemoryService(store)
        claim_64 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
            source_ref="user:statement",
            observed_at=T0,
            valid_from=T0,
        )
        first_projection = ExactContextCompiler(store).compile(
            ContextRequest(claim_64.id, "current RAM", 512),
            subject="machine:primary",
            predicate="memory_gb",
        )

        claim_96 = service.observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="user:correction",
            observed_at=T0 + timedelta(hours=1),
            payload={"utterance": "Actually I upgraded it to 96 GB."},
            valid_from=T0 + timedelta(minutes=30),
            supersede_current=True,
        )

        current = store.current_claim("machine:primary", "memory_gb")
        assert current is not None
        assert current.id == claim_96.id
        assert current.value == 96

        history = store.claim_history("machine:primary", "memory_gb")
        assert [claim.id for claim in history] == [claim_64.id, claim_96.id]
        assert [claim.value for claim in history] == [64, 96]
        assert store.evidence(claim_64.evidence_refs[0]) is not None
        assert store.evidence(claim_96.evidence_refs[0]) is not None

        relations = store.relations_for(claim_96.id)
        assert len(relations) == 1
        assert relations[0].source_claim_id == claim_96.id
        assert relations[0].target_claim_id == claim_64.id
        assert relations[0].kind is ClaimRelationKind.SUPERSEDES

        second_projection = ExactContextCompiler(store).compile(
            ContextRequest(claim_96.id, "current RAM", 512),
            subject="machine:primary",
            predicate="memory_gb",
        )
        assert second_projection.coverage_status is CoverageStatus.COMPLETE
        assert second_projection.items[0].ref_id == claim_96.id
        assert first_projection.snapshot_id != second_projection.snapshot_id
        assert first_projection.manifest_digest != second_projection.manifest_digest
        assert store.projection_is_stale(first_projection.id)
        assert not store.projection_is_stale(second_projection.id)

    with SQLiteCanonicalStore(path) as reopened:
        current = reopened.current_claim("machine:primary", "memory_gb")
        assert current is not None
        assert current.value == 96
        assert [claim.value for claim in reopened.claim_history("machine:primary", "memory_gb")] == [64, 96]
