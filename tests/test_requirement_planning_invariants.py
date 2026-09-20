from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sarmady.context import (
    ContextRequest,
    ControlledRequirementPlanner,
    ExactCoverageRequirement,
    LexicalCandidateGenerator,
    RequirementPlan,
    RequirementPlanStatus,
    context_request_fingerprint,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 21, 1, 0, tzinfo=UTC)


def _observe(store, subject: str, value: int):
    return EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate="memory_gb",
        value=value,
        source_ref=f"test:{subject}",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )


def test_higher_value_match_rank_does_not_break_subject_ambiguity(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        alpha = _observe(store, "machine:alpha", 64)
        beta = _observe(store, "machine:beta", 96)
        request = ContextRequest(
            id=uuid4(),
            query="What is the machine memory 64?",
            token_budget=1024,
        )
        candidates = LexicalCandidateGenerator(store).generate(request)

        by_id = {candidate.operative_claim_id: candidate for candidate in candidates.candidates}
        assert by_id[alpha.id].rank_score > by_id[beta.id].rank_score

        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert plan.status is RequirementPlanStatus.AMBIGUOUS
        assert plan.exact_requirements == ()
        assert set(plan.ambiguous_candidate_claim_ids) == {alpha.id, beta.id}


def test_derive_request_revalidates_single_obligation_planner_contract() -> None:
    source = ContextRequest(
        id=uuid4(),
        query="primary memory",
        token_budget=1024,
    )
    first = ExactCoverageRequirement(
        "planned:machine:primary:memory_gb",
        "machine:primary",
        "memory_gb",
    )
    second = ExactCoverageRequirement(
        "forged-second",
        "machine:primary",
        "os",
    )
    plan = RequirementPlan(
        source_request_id=source.id,
        source_request_fingerprint=context_request_fingerprint(source),
        candidate_snapshot_id="sqlite:1",
        canonical_frontier="1",
        candidate_generator_version="lexical-v0.2",
        planner_version="controlled-requirement-v0.1",
        status=RequirementPlanStatus.RESOLVED,
        exact_requirements=(first, second),
        selected_candidate_claim_ids=(uuid4(), uuid4()),
    )

    with pytest.raises(ValueError, match="exactly one obligation"):
        ControlledRequirementPlanner().derive_request(
            source,
            plan,
            new_request_id=uuid4(),
        )
