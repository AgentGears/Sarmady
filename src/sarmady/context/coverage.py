from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sarmady.epistemic import ResolutionStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import ContextItem, ContextProjection, ContextRequest, CoverageStatus


class CoverageContextCompiler:
    """Compile several exact semantic obligations inside one pinned snapshot.

    This compiler deliberately performs no semantic search. It isolates the
    distinction between retrieving something relevant and satisfying an
    explicit information requirement.
    """

    version = "coverage-exact-v0.1"

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    def compile(self, request: ContextRequest) -> ContextProjection:
        if not request.exact_requirements:
            raise ValueError(
                "CoverageContextCompiler requires at least one exact coverage requirement"
            )

        dependency_keys: set[str] = set()
        items: list[ContextItem] = []
        gaps: list[str] = []
        omitted_refs: list[UUID] = []
        conflict_refs: list[UUID] = []
        seen_refs: set[tuple[str, UUID]] = set()
        satisfied_keys: list[str] = []

        with self.store.read_snapshot() as frontier:
            for requirement in request.exact_requirements:
                dependency_keys.add(
                    self.store.epistemic_dependency_key(
                        requirement.subject, requirement.predicate
                    )
                )
                requirement_gaps: list[str] = []
                state = self.store.resolved_state(
                    requirement.subject,
                    requirement.predicate,
                    known_at=request.known_at,
                    valid_at=request.valid_at,
                    snapshot_frontier=frontier,
                )

                if state.status is ResolutionStatus.MISSING:
                    requirement_gaps.append("missing-resolved-state")
                else:
                    conflict_refs.extend(state.conflict_relation_ids)
                    claim_ids = [state.operative_claim_id, *state.competing_claim_ids]
                    for index, claim_id in enumerate(claim_ids):
                        if claim_id is None:
                            requirement_gaps.append("missing-operative-claim")
                            continue
                        claim = self.store.claim(claim_id)
                        if claim is None:
                            requirement_gaps.append(f"missing-claim:{claim_id}")
                            continue

                        memory = self.store.memory_entry_for_target("Claim", claim.id)
                        if memory is None:
                            requirement_gaps.append(
                                f"claim-not-admitted-to-memory:{claim.id}"
                            )
                            omitted_refs.append(claim.id)
                            continue

                        dependency_keys.add(
                            self.store.memory_dependency_key(memory.id)
                        )
                        if not self.store.is_active_memory_target("Claim", claim.id):
                            requirement_gaps.append(
                                f"claim-memory-not-active:{claim.id}"
                            )
                            omitted_refs.append(claim.id)
                            continue

                        role = requirement.role if index == 0 else "counterevidence"
                        claim_key = ("Claim", claim.id)
                        if claim_key not in seen_refs:
                            items.append(
                                ContextItem(
                                    "Claim",
                                    claim.id,
                                    role,
                                    claim.evidence_refs,
                                )
                            )
                            seen_refs.add(claim_key)

                        if not claim.evidence_refs:
                            requirement_gaps.append(f"claim-without-evidence:{claim.id}")
                        for evidence_id in claim.evidence_refs:
                            evidence = self.store.evidence(evidence_id)
                            if evidence is None:
                                requirement_gaps.append(
                                    f"missing-evidence:{evidence_id}"
                                )
                                continue
                            evidence_key = ("Evidence", evidence_id)
                            if evidence_key not in seen_refs:
                                items.append(
                                    ContextItem(
                                        "Evidence",
                                        evidence_id,
                                        "provenance",
                                        (evidence_id,),
                                    )
                                )
                                seen_refs.add(evidence_key)

                if requirement_gaps:
                    gaps.extend(
                        f"coverage:{requirement.key}:{gap}"
                        for gap in requirement_gaps
                    )
                else:
                    satisfied_keys.append(requirement.key)

            required_count = len(request.exact_requirements)
            satisfied_count = len(satisfied_keys)
            if satisfied_count == required_count:
                coverage = CoverageStatus.COMPLETE
            elif satisfied_count > 0:
                coverage = CoverageStatus.PARTIAL
            else:
                coverage = CoverageStatus.INSUFFICIENT

            unique_conflicts = tuple(dict.fromkeys(conflict_refs))
            manifest_parts = [
                str(frontier),
                request.known_at.isoformat() if request.known_at else "",
                request.valid_at.isoformat() if request.valid_at else "",
            ]
            manifest_parts.extend(
                "requirement:"
                + ":".join(
                    [
                        requirement.key,
                        requirement.subject,
                        requirement.predicate,
                        requirement.role,
                    ]
                )
                for requirement in request.exact_requirements
            )
            manifest_parts.extend(f"satisfied:{key}" for key in satisfied_keys)
            manifest_parts.extend(
                f"{item.ref_type}:{item.ref_id}:{item.role}" for item in items
            )
            manifest_parts.extend(f"conflict:{ref}" for ref in unique_conflicts)
            manifest_parts.extend(gaps)
            digest = "sha256:" + hashlib.sha256(
                "|".join(manifest_parts).encode("utf-8")
            ).hexdigest()

            projection = ContextProjection(
                id=uuid4(),
                request_id=request.id,
                snapshot_id=f"sqlite:{frontier}",
                canonical_frontier=str(frontier),
                items=tuple(items),
                coverage_status=coverage,
                manifest_digest=digest,
                compiler_version=self.version,
                conflict_refs=unique_conflicts,
                unresolved_gaps=tuple(gaps),
                omitted_refs=tuple(dict.fromkeys(omitted_refs)),
            )

        self.store.register_context_projection(
            projection,
            request=request,
            dependency_keys=tuple(dependency_keys),
        )
        return projection
