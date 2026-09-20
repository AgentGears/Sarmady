from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sarmady.epistemic import ResolutionStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import (
    CandidateSet,
    ContextCandidate,
    ContextRequest,
    context_request_fingerprint,
)


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class LexicalCandidateGenerator:
    """Discover relevant semantic keys without claiming context sufficiency.

    This first retrieval slice is deliberately transparent and deterministic.
    It performs exact lexical token matching over subject, predicate, and the
    values of memory-active claims resolved inside one pinned SQLite snapshot.
    It does not write memory telemetry, persist the candidate set, infer exact
    coverage requirements, or mark relevance as sufficient context.
    """

    __slots__ = ("store",)

    version = "lexical-v0.1"

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    def generate(self, request: ContextRequest, *, limit: int = 20) -> CandidateSet:
        if isinstance(limit, bool) or not isinstance(limit, int) or limit <= 0:
            raise ValueError("candidate limit must be a positive integer")
        if not isinstance(request.query, str):
            raise TypeError("context request query must be a string")

        request_fingerprint = context_request_fingerprint(request)
        query_terms = tuple(sorted(lexical_tokens(request.query)))
        if not query_terms:
            raise ValueError("context request query must contain a lexical term")
        query_term_set = set(query_terms)

        candidates: list[ContextCandidate] = []
        with self.store.context_read_snapshot() as snapshot:
            frontier = snapshot.frontier
            for subject, predicate in snapshot.semantic_keys():
                state = snapshot.resolved_state(
                    subject,
                    predicate,
                    known_at=request.known_at,
                    valid_at=request.valid_at,
                )
                if (
                    state.status is ResolutionStatus.MISSING
                    or state.operative_claim_id is None
                ):
                    continue

                operative = snapshot.claim(state.operative_claim_id)
                if operative is None:
                    continue
                if not snapshot.is_active_memory_target("Claim", operative.id):
                    continue

                value_terms = set(_semantic_tokens(operative.value))
                for competing_id in state.competing_claim_ids:
                    competing = snapshot.claim(competing_id)
                    if competing is None:
                        continue
                    if not snapshot.is_active_memory_target("Claim", competing.id):
                        continue
                    value_terms.update(_semantic_tokens(competing.value))

                subject_terms = lexical_tokens(subject)
                predicate_terms = lexical_tokens(predicate)
                subject_matches = query_term_set & subject_terms
                predicate_matches = query_term_set & predicate_terms
                value_matches = query_term_set & value_terms
                matched_terms = tuple(
                    sorted(subject_matches | predicate_matches | value_matches)
                )
                if not matched_terms:
                    continue

                # These literals are part of lexical-v0.1. Keeping them inside
                # the implementation prevents callers from mutating a public
                # scoring profile while retaining the same generator version.
                rank_score = float(
                    5 * len(predicate_matches)
                    + 3 * len(subject_matches)
                    + len(value_matches)
                )
                candidates.append(
                    ContextCandidate(
                        subject=subject,
                        predicate=predicate,
                        operative_claim_id=operative.id,
                        rank_score=rank_score,
                        signals=tuple(f"term:{term}" for term in matched_terms),
                    )
                )

            candidates.sort(
                key=lambda candidate: (
                    -candidate.rank_score,
                    candidate.subject,
                    candidate.predicate,
                    str(candidate.operative_claim_id),
                )
            )
            selected = tuple(candidates[:limit])
            is_exhaustive = len(candidates) <= limit

        return CandidateSet(
            request_id=request.id,
            snapshot_id=f"sqlite:{frontier}",
            canonical_frontier=str(frontier),
            candidates=selected,
            generator_version=self.version,
            request_fingerprint=request_fingerprint,
            is_exhaustive=is_exhaustive,
        )


def lexical_tokens(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text)}


def _semantic_tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return lexical_tokens(value)
    if isinstance(value, bool):
        return {"true" if value else "false"}
    if isinstance(value, (int, float)):
        return lexical_tokens(str(value))
    if isinstance(value, Mapping):
        tokens: set[str] = set()
        for key, item in value.items():
            tokens.update(lexical_tokens(key))
            tokens.update(_semantic_tokens(item))
        return tokens
    if isinstance(value, tuple):
        tokens: set[str] = set()
        for item in value:
            tokens.update(_semantic_tokens(item))
        return tokens
    raise TypeError("candidate generator received non-canonical semantic value")
