from __future__ import annotations

import hashlib
from uuid import uuid4

from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import ContextItem, ContextProjection, ContextRequest, CoverageStatus


class ExactContextCompiler:
    """Deterministic M1 compiler for an exact subject/predicate lookup.

    This is deliberately not semantic retrieval. It proves bounded projection,
    provenance, memory admission, snapshot/frontier pinning, and reconstruction.
    """

    version = "exact-v0.1"

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    def compile(self, request: ContextRequest, *, subject: str, predicate: str) -> ContextProjection:
        frontier = self.store.frontier()
        claim = self.store.current_claim(subject, predicate)
        items: list[ContextItem] = []
        gaps: list[str] = []

        if claim is None:
            gaps.append(f"missing-current-claim:{subject}:{predicate}")
        elif not self.store.is_active_memory_target("Claim", claim.id):
            gaps.append(f"claim-not-admitted-to-memory:{claim.id}")
        else:
            items.append(ContextItem("Claim", claim.id, "essential_now", claim.evidence_refs))
            for evidence_id in claim.evidence_refs:
                if self.store.evidence(evidence_id) is not None:
                    items.append(ContextItem("Evidence", evidence_id, "provenance", (evidence_id,)))
                else:
                    gaps.append(f"missing-evidence:{evidence_id}")

        coverage = CoverageStatus.COMPLETE if items and not gaps else CoverageStatus.INSUFFICIENT
        manifest_source = "|".join(
            [str(frontier), subject, predicate]
            + [f"{item.ref_type}:{item.ref_id}:{item.role}" for item in items]
            + gaps
        )
        digest = "sha256:" + hashlib.sha256(manifest_source.encode("utf-8")).hexdigest()

        return ContextProjection(
            id=uuid4(),
            request_id=request.id,
            snapshot_id=f"sqlite:{frontier}",
            canonical_frontier=str(frontier),
            items=tuple(items),
            coverage_status=coverage,
            manifest_digest=digest,
            compiler_version=self.version,
            unresolved_gaps=tuple(gaps),
        )
