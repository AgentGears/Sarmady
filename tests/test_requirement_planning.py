from datetime import UTC, datetime, timedelta, timezone
from uuid import uuid4

import pytest

from sarmady.context import (
    CandidateSet,
    ContextCandidate,
    ContextRequest,
    ControlledRequirementPlanner,
    CoverageContextCompiler,
    CoverageStatus,
    ExactCoverageRequirement,
    LexicalCandidateGenerator,
    RequirementPlanStatus,
    context_request_fingerprint,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)


def _observe(
    store: SQLiteCanonicalStore,
    *,
    subject: str,
    predicate: str,
    value,
    at: datetime = T0,
):
    return EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate=predicate,
        value=value,
        source_ref=f"test:{subject}:{predicate}",
        observed_at=at,
        recorded_at=at,
        valid_from=at,
    )


def _request(query: str, **kwargs) -> ContextRequest:
    return ContextRequest(
        id=kwargs.pop("id", uuid4()),
        query=query,
        token_budget=kwargs.pop("token_budget", 2048),
        **kwargs,
    )


def test_planner_resolves_one_explicit_predicate_for_unique_subject(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim = _observe(
            store,
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
        )
        request = _request("What is machine primary memory?")
        frontier_before = store.frontier()
        candidates = LexicalCandidateGenerator(store).generate(request)

        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert candidates.is_exhaustive is True
        assert plan.status is RequirementPlanStatus.RESOLVED
        assert plan.source_request_id == request.id
        assert plan.candidate_snapshot_id == candidates.snapshot_id
        assert plan.selected_candidate_claim_ids == (claim.id,)
        assert plan.ambiguous_candidate_claim_ids == ()
        assert plan.reasons == ()
        assert len(plan.exact_requirements) == 1
        requirement = plan.exact_requirements[0]
        assert requirement.subject == "machine:primary"
        assert requirement.predicate == "memory_gb"
        assert store.frontier() == frontier_before
        assert store.context_request(request.id) is None


def test_planner_preserves_irreducible_subject_ambiguity(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        alpha = _observe(
            store,
            subject="machine:alpha",
            predicate="memory_gb",
            value=64,
        )
        beta = _observe(
            store,
            subject="machine:beta",
            predicate="memory_gb",
            value=96,
        )
        request = _request("What is the machine memory?")
        candidates = LexicalCandidateGenerator(store).generate(request)

        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert candidates.is_exhaustive is True
        assert plan.status is RequirementPlanStatus.AMBIGUOUS
        assert plan.exact_requirements == ()
        assert set(plan.ambiguous_candidate_claim_ids) == {alpha.id, beta.id}
        assert plan.reasons == ("ambiguous-subject",)


def test_planner_resolves_subject_only_from_discriminating_query_term(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        alpha = _observe(
            store,
            subject="machine:alpha",
            predicate="memory_gb",
            value=64,
        )
        _observe(
            store,
            subject="machine:beta",
            predicate="memory_gb",
            value=96,
        )
        request = _request("What is alpha machine memory?")
        candidates = LexicalCandidateGenerator(store).generate(request)

        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert len(candidates.candidates) == 2
        assert plan.status is RequirementPlanStatus.RESOLVED
        assert plan.selected_candidate_claim_ids == (alpha.id,)
        assert plan.exact_requirements[0].subject == "machine:alpha"


def test_planner_abstains_when_candidate_set_was_truncated(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:alpha",
            predicate="memory_gb",
            value=64,
        )
        _observe(
            store,
            subject="machine:beta",
            predicate="memory_gb",
            value=96,
        )
        request = _request("What is alpha machine memory?")
        candidates = LexicalCandidateGenerator(store).generate(request, limit=1)

        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert len(candidates.candidates) == 1
        assert candidates.is_exhaustive is False
        assert plan.status is RequirementPlanStatus.ABSTAINED
        assert plan.exact_requirements == ()
        assert plan.reasons == ("candidate-set-non-exhaustive",)


def test_planner_rejects_other_generator_exhaustiveness_claims(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
        )
        request = _request("primary memory")
        lexical = LexicalCandidateGenerator(store).generate(request)
        custom = CandidateSet(
            request_id=lexical.request_id,
            snapshot_id=lexical.snapshot_id,
            canonical_frontier=lexical.canonical_frontier,
            candidates=lexical.candidates,
            generator_version="semantic-custom-v1",
            request_fingerprint=lexical.request_fingerprint,
            is_exhaustive=True,
        )

        plan = ControlledRequirementPlanner().plan(request, custom)

        assert plan.status is RequirementPlanStatus.ABSTAINED
        assert plan.reasons == ("unsupported-candidate-generator",)
        assert plan.exact_requirements == ()


def test_planner_does_not_convert_value_only_relevance_into_predicate_constraint(
    tmp_path,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:primary",
            predicate="os",
            value="freebsd",
        )
        request = _request("freebsd")
        candidates = LexicalCandidateGenerator(store).generate(request)

        assert len(candidates.candidates) == 1
        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert plan.status is RequirementPlanStatus.ABSTAINED
        assert plan.reasons == ("no-explicit-predicate-evidence",)
        assert plan.exact_requirements == ()


def test_planner_abstains_when_predicate_evidence_is_not_uniquely_interpretable(
    tmp_path,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
        )
        _observe(
            store,
            subject="machine:primary",
            predicate="os",
            value="linux",
            at=T0 + timedelta(seconds=1),
        )
        request = _request("What are primary memory and os?")
        candidates = LexicalCandidateGenerator(store).generate(request)

        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert plan.status is RequirementPlanStatus.ABSTAINED
        assert plan.reasons == ("predicate-ambiguous-or-multi-intent",)
        assert plan.exact_requirements == ()


def test_planner_rejects_candidate_set_bound_to_different_request_semantics(
    tmp_path,
) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
        )
        request = _request("primary memory")
        candidates = LexicalCandidateGenerator(store).generate(request)
        altered = _request("primary os", id=request.id)

        with pytest.raises(ValueError, match="does not match source request semantics"):
            ControlledRequirementPlanner().plan(altered, candidates)


def test_request_fingerprint_normalizes_equivalent_timezone_offsets() -> None:
    request_id = uuid4()
    local = ContextRequest(
        id=request_id,
        query="primary memory",
        token_budget=1024,
        known_at=datetime(
            2026,
            9,
            21,
            0,
            0,
            tzinfo=timezone(timedelta(hours=3)),
        ),
        valid_at=datetime(
            2026,
            9,
            21,
            1,
            0,
            tzinfo=timezone(timedelta(hours=3)),
        ),
    )
    utc = ContextRequest(
        id=request_id,
        query="primary memory",
        token_budget=1024,
        known_at=datetime(2026, 9, 20, 21, 0, tzinfo=UTC),
        valid_at=datetime(2026, 9, 20, 22, 0, tzinfo=UTC),
    )

    assert local.known_at == utc.known_at
    assert local.valid_at == utc.valid_at
    assert context_request_fingerprint(local) == context_request_fingerprint(utc)


def test_resolved_plan_derives_new_request_and_compiles_coverage(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        claim = _observe(
            store,
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
        )
        goal_id = uuid4()
        task_id = uuid4()
        source = _request(
            "What is primary memory?",
            token_budget=4096,
            latency_budget_ms=250,
            goal_ref=goal_id,
            task_ref=task_id,
            coverage_requirements=("answer the explicit machine fact",),
            known_at=T0,
            valid_at=T0,
        )
        generator = LexicalCandidateGenerator(store)
        planner = ControlledRequirementPlanner()
        plan = planner.plan(source, generator.generate(source))
        derived_id = uuid4()

        derived = planner.derive_request(
            source,
            plan,
            new_request_id=derived_id,
        )

        assert derived.id == derived_id
        assert derived.id != source.id
        assert derived.query == source.query
        assert derived.token_budget == source.token_budget
        assert derived.latency_budget_ms == source.latency_budget_ms
        assert derived.goal_ref == goal_id
        assert derived.task_ref == task_id
        assert derived.coverage_requirements == source.coverage_requirements
        assert derived.known_at == source.known_at
        assert derived.valid_at == source.valid_at
        assert derived.exact_requirements == plan.exact_requirements

        projection = CoverageContextCompiler(store).compile(derived)
        assert projection.coverage_status is CoverageStatus.COMPLETE
        assert claim.id in {
            item.ref_id for item in projection.items if item.ref_type == "Claim"
        }
        assert store.context_request(source.id) is None
        assert store.context_request(derived.id) == derived

        with pytest.raises(ValueError, match="must use a new id"):
            planner.derive_request(source, plan, new_request_id=source.id)
        with pytest.raises(TypeError, match="id must be UUID"):
            planner.derive_request(
                source,
                plan,
                new_request_id="not-a-uuid",  # type: ignore[arg-type]
            )


def test_nonresolved_plan_cannot_derive_request(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:alpha",
            predicate="memory_gb",
            value=64,
        )
        _observe(
            store,
            subject="machine:beta",
            predicate="memory_gb",
            value=96,
        )
        request = _request("machine memory")
        planner = ControlledRequirementPlanner()
        plan = planner.plan(request, LexicalCandidateGenerator(store).generate(request))

        assert plan.status is RequirementPlanStatus.AMBIGUOUS
        with pytest.raises(ValueError, match="only a resolved"):
            planner.derive_request(request, plan, new_request_id=uuid4())


def test_planner_refuses_to_replace_preexisting_exact_requirements(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        _observe(
            store,
            subject="machine:primary",
            predicate="memory_gb",
            value=64,
        )
        request = _request(
            "primary memory",
            exact_requirements=(
                ExactCoverageRequirement(
                    "already-explicit",
                    "machine:primary",
                    "memory_gb",
                ),
            ),
        )
        candidates = LexicalCandidateGenerator(store).generate(request)

        with pytest.raises(ValueError, match="without exact requirements"):
            ControlledRequirementPlanner().plan(request, candidates)


def test_candidate_set_rejects_duplicate_semantic_keys() -> None:
    request = _request("memory")
    first = ContextCandidate(
        subject="machine:primary",
        predicate="memory_gb",
        operative_claim_id=uuid4(),
        rank_score=2.0,
    )
    duplicate = ContextCandidate(
        subject="machine:primary",
        predicate="memory_gb",
        operative_claim_id=uuid4(),
        rank_score=1.0,
    )

    with pytest.raises(ValueError, match="semantic keys must be unique"):
        CandidateSet(
            request_id=request.id,
            snapshot_id="sqlite:1",
            canonical_frontier="1",
            candidates=(first, duplicate),
            generator_version="lexical-v0.2",
            request_fingerprint=context_request_fingerprint(request),
            is_exhaustive=True,
        )
