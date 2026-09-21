from datetime import UTC, datetime
from uuid import uuid4

from sarmady.context import (
    ContextRequest,
    ControlledRequirementPlanner,
    LexicalCandidateGenerator,
    RequirementPlanStatus,
)
from sarmady.epistemic.service import EpistemicMemoryService
from sarmady.storage.sqlite import SQLiteCanonicalStore


T0 = datetime(2026, 9, 21, 0, 0, tzinfo=UTC)


def _observe(store: SQLiteCanonicalStore, *, subject: str):
    return EpistemicMemoryService(store).observe_claim(
        subject=subject,
        predicate="memory_gb",
        value=64,
        source_ref=f"test:{subject}:memory_gb",
        observed_at=T0,
        recorded_at=T0,
        valid_from=T0,
    )


def test_predicate_evidence_cannot_double_as_subject_identity(tmp_path) -> None:
    path = tmp_path / "sarmady.db"
    with SQLiteCanonicalStore(path) as store:
        memory = _observe(store, subject="machine:memory")
        primary = _observe(store, subject="machine:primary")
        request = ContextRequest(
            id=uuid4(),
            query="How much memory?",
            token_budget=2048,
        )
        candidates = LexicalCandidateGenerator(store).generate(request)

        assert len(candidates.candidates) == 2
        plan = ControlledRequirementPlanner().plan(request, candidates)

        assert plan.status is RequirementPlanStatus.AMBIGUOUS
        assert plan.exact_requirements == ()
        assert set(plan.ambiguous_candidate_claim_ids) == {memory.id, primary.id}
        assert plan.reasons == ("ambiguous-subject",)
