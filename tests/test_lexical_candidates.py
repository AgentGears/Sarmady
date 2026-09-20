from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from sarmady.context import (
    CandidateSet,
    ContextCandidate,
    ContextRequest,
    LexicalCandidateGenerator,
)
from sarmady.epistemic import ClaimRelationKind, ResolutionStatus
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.memory import MemoryLifecycleEventKind
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 20, 0, tzinfo=UTC)


def _observe(
    store: SQLiteCanonicalStore,
    *,
    subject: str = "machine:primary",
    predicate: str,
    value,
    at: datetime = T0,
    relation_kind: ClaimRelationKind | None = None,
):
    return EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate=predicate,
        value=value,
        source_ref=f"test:{subject}:{predicate}:{at.isoformat()}",
        observed_at=at,
        recorded_at=at,
        valid_from=at,
        relation_kind=relation_kind,
    )


def _request(query: str, *, known_at: datetime | None = None) -> ContextRequest:
    return ContextRequest(
        id=uuid4(),
        query=query,
        token_budget=1024,
        known_at=known_at,
    )


def test_lexical_candidates_rank_predicate_match_over_subject_only(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        memory = _observe(store, predicate="memory_gb", value=64)
        os_claim = _observe(store, predicate="os", value="linux")

        result = LexicalCandidateGenerator(store).generate(
            _request("machine memory")
        )

        assert [candidate.operative_claim_id for candidate in result.candidates] == [
            memory.id,
            os_claim.id,
        ]
        assert result.candidates[0].rank_score > result.candidates[1].rank_score
        assert result.candidates[0].signals == ("term:machine", "term:memory")
        assert result.snapshot_id == f"sqlite:{result.canonical_frontier}"


def test_candidate_generation_respects_active_memory_without_seen_or_used_writes(
    tmp_path,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim = _observe(store, predicate="memory_gb", value=64)
        memory = store.memory_entry_for_target("Claim", claim.id)
        assert memory is not None
        store.record_memory_event(
            memory.id,
            MemoryLifecycleEventKind.ARCHIVED,
            occurred_at=T0 + timedelta(minutes=1),
            source="test",
        )
        frontier_before = store.frontier()
        counts_before = store.memory_access_counts(memory.id)
        request = _request("memory")

        result = LexicalCandidateGenerator(store).generate(request)

        assert result.candidates == ()
        assert store.frontier() == frontier_before
        assert store.memory_access_counts(memory.id) == counts_before == (0, 0)
        assert store.context_request(request.id) is None


def test_candidate_generation_uses_requested_knowledge_time(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        old_claim = _observe(store, predicate="os", value="ubuntu")
        _observe(
            store,
            predicate="os",
            value="freebsd",
            at=T0 + timedelta(hours=1),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )

        historical = LexicalCandidateGenerator(store).generate(
            _request("ubuntu", known_at=T0 + timedelta(minutes=30))
        )
        current = LexicalCandidateGenerator(store).generate(_request("ubuntu"))

        assert len(historical.candidates) == 1
        assert historical.candidates[0].operative_claim_id == old_claim.id
        assert historical.candidates[0].signals == ("term:ubuntu",)
        assert current.candidates == ()


def test_candidate_generation_can_match_active_counterclaim_value(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        operative = _observe(store, predicate="os", value="linux")
        _observe(
            store,
            predicate="os",
            value="freebsd",
            at=T0 + timedelta(minutes=1),
            relation_kind=ClaimRelationKind.CONTRADICTS,
        )

        result = LexicalCandidateGenerator(store).generate(_request("freebsd"))

        assert len(result.candidates) == 1
        assert result.candidates[0].operative_claim_id == operative.id
        assert result.candidates[0].signals == ("term:freebsd",)


def test_candidate_generation_tokenizes_nested_canonical_values(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim = _observe(
            store,
            predicate="hardware_profile",
            value={"accelerator": {"gpu_model": "RTX-4090"}},
        )

        result = LexicalCandidateGenerator(store).generate(_request("gpu 4090"))

        assert len(result.candidates) == 1
        assert result.candidates[0].operative_claim_id == claim.id
        assert result.candidates[0].signals == ("term:4090", "term:gpu")


def test_candidate_generation_is_deterministic_and_honors_limit(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        alpha = _observe(
            store,
            subject="machine:alpha",
            predicate="status",
            value="ready",
        )
        _observe(
            store,
            subject="machine:beta",
            predicate="status",
            value="ready",
        )

        generator = LexicalCandidateGenerator(store)
        first = generator.generate(_request("status"), limit=1)
        second = generator.generate(_request("status"), limit=1)

        assert first.candidates == second.candidates
        assert len(first.candidates) == 1
        assert first.candidates[0].operative_claim_id == alpha.id
        assert first.generator_version == "lexical-v0.1"
        with pytest.raises(AttributeError):
            generator.predicate_weight = 99  # type: ignore[attr-defined]


def test_candidate_generation_rejects_empty_query_bad_limit_and_mutated_query(
    tmp_path,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        generator = LexicalCandidateGenerator(store)
        with pytest.raises(ValueError, match="lexical term"):
            generator.generate(_request("___ ---"))
        with pytest.raises(ValueError, match="positive integer"):
            generator.generate(_request("memory"), limit=0)
        with pytest.raises(ValueError, match="positive integer"):
            generator.generate(_request("memory"), limit=True)

        mutated = _request("memory")
        object.__setattr__(mutated, "query", 42)
        with pytest.raises(TypeError, match="query must be a string"):
            generator.generate(mutated)


def test_generic_candidate_contract_allows_nonlexical_finite_scores() -> None:
    candidate = ContextCandidate(
        subject="machine:primary",
        predicate="memory_gb",
        operative_claim_id=uuid4(),
        rank_score=-0.125,
    )
    assert candidate.rank_score == -0.125
    assert candidate.signals == ()

    with pytest.raises(ValueError, match="finite"):
        ContextCandidate(
            subject="machine:primary",
            predicate="memory_gb",
            operative_claim_id=uuid4(),
            rank_score=float("nan"),
        )


def test_candidate_contract_defensively_freezes_caller_owned_collections() -> None:
    raw_signals = ["term:memory"]
    candidate = ContextCandidate(
        subject="machine:primary",
        predicate="memory_gb",
        operative_claim_id=uuid4(),
        rank_score=1.0,
        signals=raw_signals,  # type: ignore[arg-type]
    )
    raw_signals.append("term:changed")
    assert candidate.signals == ("term:memory",)

    raw_candidates = [candidate]
    candidate_set = CandidateSet(
        request_id=uuid4(),
        snapshot_id="sqlite:1",
        canonical_frontier="1",
        candidates=raw_candidates,  # type: ignore[arg-type]
        generator_version="custom-v1",
    )
    raw_candidates.clear()
    assert candidate_set.candidates == (candidate,)

    with pytest.raises(TypeError, match="ContextCandidate"):
        CandidateSet(
            request_id=uuid4(),
            snapshot_id="sqlite:1",
            canonical_frontier="1",
            candidates=["not-a-candidate"],  # type: ignore[list-item]
            generator_version="custom-v1",
        )


def test_candidate_set_is_immutable_and_snapshot_enumerator_closes(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(store, predicate="memory_gb", value=64)
        result = LexicalCandidateGenerator(store).generate(_request("memory"))

        with pytest.raises(FrozenInstanceError):
            result.generator_version = "changed"  # type: ignore[misc]

        with store.context_read_snapshot() as snapshot:
            assert snapshot.semantic_keys() == (("machine:primary", "memory_gb"),)
        with pytest.raises(RuntimeError, match="snapshot is closed"):
            snapshot.semantic_keys()


def test_semantic_key_enumeration_remains_pinned_during_concurrent_write(
    tmp_path,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as reader:
        _observe(reader, predicate="memory_gb", value=64)

        with reader.context_read_snapshot() as snapshot:
            assert snapshot.semantic_keys() == (("machine:primary", "memory_gb"),)

            with SQLiteCanonicalStore(path) as writer:
                _observe(writer, predicate="os", value="linux", at=T0 + timedelta(minutes=1))

            assert snapshot.semantic_keys() == (("machine:primary", "memory_gb"),)
            assert (
                snapshot.resolved_state("machine:primary", "os").status
                is ResolutionStatus.MISSING
            )

        assert reader.frontier() > snapshot.frontier
