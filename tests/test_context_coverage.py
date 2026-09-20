from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sarmady.context import (
    ContextRequest,
    CoverageContextCompiler,
    CoverageStatus,
    ExactCoverageRequirement,
)
from sarmady.epistemic import ClaimRelationKind
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.memory import MemoryLifecycleEventKind
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 20, 13, 0, tzinfo=UTC)


def _observe(store, predicate: str, value, *, at=T0):
    return EpistemicMemoryService(store).observe_claim(
        subject="machine:primary",
        predicate=predicate,
        value=value,
        source_ref=f"user:{predicate}",
        observed_at=at,
        recorded_at=at,
        valid_from=at,
    )


def _request(*requirements: ExactCoverageRequirement) -> ContextRequest:
    return ContextRequest(
        id=uuid4(),
        query="Summarize the requested machine facts",
        token_budget=2048,
        coverage_requirements=("all explicitly required machine facts",),
        exact_requirements=tuple(requirements),
    )


def test_multi_key_coverage_compiles_complete_projection_in_one_snapshot(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        memory_claim = _observe(store, "memory_gb", 64)
        os_claim = _observe(store, "os", "linux")

        request = _request(
            ExactCoverageRequirement("memory", "machine:primary", "memory_gb"),
            ExactCoverageRequirement("os", "machine:primary", "os"),
        )
        projection = CoverageContextCompiler(store).compile(request)

        assert projection.coverage_status is CoverageStatus.COMPLETE
        assert projection.unresolved_gaps == ()
        assert projection.snapshot_id == f"sqlite:{projection.canonical_frontier}"
        claim_ids = {
            item.ref_id for item in projection.items if item.ref_type == "Claim"
        }
        assert claim_ids == {memory_claim.id, os_claim.id}
        restored = store.context_request(request.id)
        assert restored == request
        assert restored.exact_requirements == request.exact_requirements


def test_missing_one_required_key_is_partial_not_complete(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(store, "memory_gb", 64)
        request = _request(
            ExactCoverageRequirement("memory", "machine:primary", "memory_gb"),
            ExactCoverageRequirement("os", "machine:primary", "os"),
        )
        projection = CoverageContextCompiler(store).compile(request)

        assert projection.coverage_status is CoverageStatus.PARTIAL
        assert "coverage:os:missing-resolved-state" in projection.unresolved_gaps
        assert all(
            not gap.startswith("coverage:memory:")
            for gap in projection.unresolved_gaps
        )


def test_missing_all_required_keys_is_insufficient(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        projection = CoverageContextCompiler(store).compile(
            _request(
                ExactCoverageRequirement("memory", "machine:primary", "memory_gb"),
                ExactCoverageRequirement("os", "machine:primary", "os"),
            )
        )
        assert projection.coverage_status is CoverageStatus.INSUFFICIENT
        assert len(projection.unresolved_gaps) == 2


def test_contested_requirement_requires_counterevidence_to_be_complete(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        current = _observe(store, "memory_gb", 64)
        counter = EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="memory_gb",
            value=96,
            source_ref="conflicting-source",
            observed_at=T0 + timedelta(minutes=1),
            recorded_at=T0 + timedelta(minutes=1),
            valid_from=T0,
            relation_kind=ClaimRelationKind.CONTRADICTS,
        )

        request = _request(
            ExactCoverageRequirement("memory", "machine:primary", "memory_gb")
        )
        complete = CoverageContextCompiler(store).compile(request)
        assert complete.coverage_status is CoverageStatus.COMPLETE
        claim_ids = {
            item.ref_id for item in complete.items if item.ref_type == "Claim"
        }
        assert claim_ids == {current.id, counter.id}
        assert complete.conflict_refs

        counter_memory = store.memory_entry_for_target("Claim", counter.id)
        assert counter_memory is not None
        store.record_memory_event(
            counter_memory.id,
            MemoryLifecycleEventKind.ARCHIVED,
            occurred_at=T0 + timedelta(minutes=2),
            source="test",
        )

        blocked = CoverageContextCompiler(store).compile(
            _request(
                ExactCoverageRequirement("memory", "machine:primary", "memory_gb")
            )
        )
        assert blocked.coverage_status is CoverageStatus.INSUFFICIENT
        assert any(
            gap.startswith("coverage:memory:claim-memory-not-active:")
            for gap in blocked.unresolved_gaps
        )
        assert counter.id in blocked.omitted_refs


def test_projection_depends_on_every_required_epistemic_key(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(store, "memory_gb", 64)
        _observe(store, "os", "linux")
        projection = CoverageContextCompiler(store).compile(
            _request(
                ExactCoverageRequirement("memory", "machine:primary", "memory_gb"),
                ExactCoverageRequirement("os", "machine:primary", "os"),
            )
        )
        assert not store.projection_is_stale(projection.id)

        EpistemicMemoryService(store).observe_claim(
            subject="machine:primary",
            predicate="os",
            value="freebsd",
            source_ref="user:os-update",
            observed_at=T0 + timedelta(hours=1),
            recorded_at=T0 + timedelta(hours=1),
            valid_from=T0 + timedelta(hours=1),
            relation_kind=ClaimRelationKind.SUPERSEDES,
        )
        assert store.projection_is_stale(projection.id)
        assert store.projection_stale_reason(projection.id) == "epistemic-state-changed"


def test_legacy_label_only_context_request_still_rehydrates(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(store, "memory_gb", 64)
        request = ContextRequest(
            uuid4(),
            "How much RAM?",
            1024,
            coverage_requirements=("current machine memory", "supporting evidence"),
        )
        # The existing exact single-key compiler persists the new tagged encoding.
        from sarmady.context import ExactContextCompiler

        ExactContextCompiler(store).compile(
            request, subject="machine:primary", predicate="memory_gb"
        )
        assert store.context_request(request.id) == request


def test_pre_v5_list_encoding_remains_readable(tmp_path) -> None:
    import json

    path = tmp_path / "sarmady.db"
    request_id = uuid4()
    with SQLiteCanonicalStore(path) as store:
        store.db.execute(
            """
            INSERT INTO context_requests(
                id, query, token_budget, latency_budget_ms, goal_ref, task_ref,
                coverage_requirements_json, known_at, valid_at
            ) VALUES (?, ?, ?, NULL, NULL, NULL, ?, NULL, NULL)
            """,
            (
                str(request_id),
                "legacy request",
                512,
                json.dumps(["legacy label one", "legacy label two"]),
            ),
        )
        restored = store.context_request(request_id)
        assert restored is not None
        assert restored.coverage_requirements == (
            "legacy label one",
            "legacy label two",
        )
        assert restored.exact_requirements == ()
