from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from .candidates import lexical_tokens
from .models import (
    CandidateSet,
    ContextCandidate,
    ContextRequest,
    ExactCoverageRequirement,
    RequirementPlan,
    RequirementPlanStatus,
    context_request_fingerprint,
)


class ControlledRequirementPlanner:
    """Infer one exact semantic obligation or preserve uncertainty.

    The v0.1 planner is intentionally conservative. It only converts explicit
    predicate-token evidence into a hard requirement, requires an exhaustive
    candidate set, resolves subject collisions only from discriminating subject
    terms present in the question, and abstains on unsupported multi-predicate
    intent. Candidate rank alone never authorizes a hard semantic constraint.
    """

    __slots__ = ()

    version = "controlled-requirement-v0.1"

    def plan(
        self,
        request: ContextRequest,
        candidate_set: CandidateSet,
    ) -> RequirementPlan:
        if request.exact_requirements:
            raise ValueError(
                "controlled requirement planning expects a request without exact requirements"
            )
        if not isinstance(request.query, str):
            raise TypeError("context request query must be a string")
        if candidate_set.request_id != request.id:
            raise ValueError("candidate set belongs to a different context request")

        request_fingerprint = context_request_fingerprint(request)
        if not candidate_set.request_fingerprint:
            raise ValueError("candidate set is not bound to source request semantics")
        if candidate_set.request_fingerprint != request_fingerprint:
            raise ValueError("candidate set does not match source request semantics")

        common = dict(
            source_request_id=request.id,
            source_request_fingerprint=request_fingerprint,
            candidate_snapshot_id=candidate_set.snapshot_id,
            canonical_frontier=candidate_set.canonical_frontier,
            candidate_generator_version=candidate_set.generator_version,
            planner_version=self.version,
        )

        if not candidate_set.is_exhaustive:
            return RequirementPlan(
                **common,
                status=RequirementPlanStatus.ABSTAINED,
                reasons=("candidate-set-non-exhaustive",),
            )
        if not candidate_set.candidates:
            return RequirementPlan(
                **common,
                status=RequirementPlanStatus.ABSTAINED,
                reasons=("no-candidates",),
            )

        query_terms = lexical_tokens(request.query)
        predicate_candidates = tuple(
            candidate
            for candidate in candidate_set.candidates
            if query_terms & lexical_tokens(candidate.predicate)
        )
        if not predicate_candidates:
            return RequirementPlan(
                **common,
                status=RequirementPlanStatus.ABSTAINED,
                reasons=("no-explicit-predicate-evidence",),
            )

        predicates = sorted({candidate.predicate for candidate in predicate_candidates})
        if len(predicates) != 1:
            return RequirementPlan(
                **common,
                status=RequirementPlanStatus.ABSTAINED,
                reasons=("unsupported-multi-predicate-intent",),
            )

        predicate = predicates[0]
        pool = tuple(
            candidate
            for candidate in predicate_candidates
            if candidate.predicate == predicate
        )
        selected = self._resolve_subject(query_terms, pool)
        if selected is None:
            return RequirementPlan(
                **common,
                status=RequirementPlanStatus.AMBIGUOUS,
                ambiguous_candidate_claim_ids=tuple(
                    candidate.operative_claim_id for candidate in pool
                ),
                reasons=("ambiguous-subject",),
            )

        requirement = ExactCoverageRequirement(
            key=f"planned:{selected.subject}:{selected.predicate}",
            subject=selected.subject,
            predicate=selected.predicate,
        )
        return RequirementPlan(
            **common,
            status=RequirementPlanStatus.RESOLVED,
            exact_requirements=(requirement,),
            selected_candidate_claim_ids=(selected.operative_claim_id,),
        )

    @staticmethod
    def _resolve_subject(
        query_terms: set[str],
        candidates: tuple[ContextCandidate, ...],
    ) -> ContextCandidate | None:
        if len(candidates) == 1:
            return candidates[0]

        term_subjects: dict[str, set[str]] = defaultdict(set)
        subject_terms: dict[str, set[str]] = {}
        for candidate in candidates:
            terms = lexical_tokens(candidate.subject)
            subject_terms[candidate.subject] = terms
            for term in terms:
                term_subjects[term].add(candidate.subject)

        qualified_subjects: set[str] = set()
        for subject, terms in subject_terms.items():
            discriminating_terms = {
                term for term in terms if len(term_subjects[term]) == 1
            }
            if query_terms & discriminating_terms:
                qualified_subjects.add(subject)

        if len(qualified_subjects) != 1:
            return None
        selected_subject = next(iter(qualified_subjects))
        for candidate in candidates:
            if candidate.subject == selected_subject:
                return candidate
        raise AssertionError("resolved subject is absent from candidate pool")

    def derive_request(
        self,
        source: ContextRequest,
        plan: RequirementPlan,
        *,
        new_request_id: UUID,
    ) -> ContextRequest:
        """Create a new request carrying a resolved plan's hard requirements."""

        if plan.planner_version != self.version:
            raise ValueError("requirement plan belongs to a different planner version")
        if plan.source_request_id != source.id:
            raise ValueError("requirement plan belongs to a different source request")
        if plan.source_request_fingerprint != context_request_fingerprint(source):
            raise ValueError("source request semantics changed after requirement planning")
        if plan.status is not RequirementPlanStatus.RESOLVED:
            raise ValueError("only a resolved requirement plan can derive a context request")
        if new_request_id == source.id:
            raise ValueError("derived context request must use a new id")

        return ContextRequest(
            id=new_request_id,
            query=source.query,
            token_budget=source.token_budget,
            latency_budget_ms=source.latency_budget_ms,
            goal_ref=source.goal_ref,
            task_ref=source.task_ref,
            coverage_requirements=source.coverage_requirements,
            exact_requirements=plan.exact_requirements,
            known_at=source.known_at,
            valid_at=source.valid_at,
        )
