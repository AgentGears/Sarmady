from __future__ import annotations

import hashlib
from uuid import UUID, uuid4

from sarmady.epistemic import ResolutionStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import ContextItem, ContextProjection, ContextRequest, CoverageStatus


class ExactContextCompiler:
    """Deterministic exact-key M1 context compiler.

    The compiler intentionally does not perform semantic retrieval. It proves
    transactional snapshot pinning, temporal resolution, contradiction
    coverage, memory-admission gating, provenance, and dependency-aware
    invalidation.
    """

    version = "exact-v0.2"

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    def compile(
        self, request: ContextRequest, *, subject: str, predicate: str
    ) -> ContextProjection:
        with self.store.context_read_snapshot() as snapshot:
            frontier = snapshot.frontier
            state = snapshot.resolved_state(
                subject,
                predicate,
                known_at=request.known_at,
                valid_at=request.valid_at,
            )
            items: list[ContextItem] = []
            gaps: list[str] = []
            omitted_refs: list[UUID] = []
            seen_refs: set[tuple[str, UUID]] = set()

            if state.status is ResolutionStatus.MISSING:
                gaps.append(f"missing-resolved-state:{subject}:{predicate}")
            else:
                claim_ids = [state.operative_claim_id, *state.competing_claim_ids]
                for index, claim_id in enumerate(claim_ids):
                    if claim_id is None:
                        continue
                    claim = snapshot.claim(claim_id)
                    if claim is None:
                        gaps.append(f"missing-claim:{claim_id}")
                        continue

                    memory = snapshot.memory_entry_for_target("Claim", claim.id)
                    if memory is None:
                        gaps.append(f"claim-not-admitted-to-memory:{claim.id}")
                        omitted_refs.append(claim.id)
                        continue

                    if not snapshot.is_active_memory_target("Claim", claim.id):
                        gaps.append(f"claim-memory-not-active:{claim.id}")
                        omitted_refs.append(claim.id)
                        continue

                    role = "essential_now" if index == 0 else "counterevidence"
                    key = ("Claim", claim.id)
                    if key not in seen_refs:
                        items.append(
                            ContextItem(
                                "Claim",
                                claim.id,
                                role,
                                claim.evidence_refs,
                            )
                        )
                        seen_refs.add(key)

                    for evidence_id in claim.evidence_refs:
                        evidence = snapshot.evidence(evidence_id)
                        if evidence is None:
                            gaps.append(f"missing-evidence:{evidence_id}")
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

            coverage = (
                CoverageStatus.COMPLETE
                if state.status is not ResolutionStatus.MISSING and items and not gaps
                else CoverageStatus.INSUFFICIENT
            )
            conflict_refs = state.conflict_relation_ids
            manifest_source = "|".join(
                [
                    str(frontier),
                    subject,
                    predicate,
                    request.known_at.isoformat() if request.known_at else "",
                    request.valid_at.isoformat() if request.valid_at else "",
                ]
                + [
                    f"{item.ref_type}:{item.ref_id}:{item.role}"
                    for item in items
                ]
                + [f"conflict:{ref}" for ref in conflict_refs]
                + gaps
            )
            digest = (
                "sha256:"
                + hashlib.sha256(manifest_source.encode("utf-8")).hexdigest()
            )
            projection = ContextProjection(
                id=uuid4(),
                request_id=request.id,
                snapshot_id=f"sqlite:{frontier}",
                canonical_frontier=str(frontier),
                items=tuple(items),
                coverage_status=coverage,
                manifest_digest=digest,
                compiler_version=self.version,
                conflict_refs=conflict_refs,
                unresolved_gaps=tuple(gaps),
                omitted_refs=tuple(omitted_refs),
            )

        self.store.register_context_projection(
            projection,
            request=request,
            dependency_capture=snapshot,
        )
        return projection
