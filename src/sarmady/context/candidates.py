from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from sarmady.epistemic import ResolutionStatus
from sarmady.storage.sqlite import SQLiteCanonicalStore

from .models import CandidateSet, ContextCandidate, ContextRequest


_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class LexicalCandidateGenerator:
    """Discover relevant semantic keys without claiming context sufficiency.

    This first retrieval slice is deliberately transparent and deterministic.
    It performs exact lexical token matching over subject, predicate, and the
    values of memory-active claims resolved inside one pinned SQLite snapshot.
    It does not write memory telemetry, persist the candidate set, infer exact
    coverage requirements, or mark relevance as sufficient context.
    """

    version = "lexical-v0.1"

    predicate_weight = 5
    subject_weight = 3
    value_weight = 1

    def __init__(self, store: SQLiteCanonicalStore):
        self.store = store

    def generate(self, request: ContextRequest, *, limit: int = 20) -> CandidateSet:
        if limit <= 0:
            raise ValueError("candidate limit must be positive")

        query_terms = tuple(sorted(_tokenize(request.query)))
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

                subject_terms = _tokenize(subject)
                predicate_terms = _tokenize(predicate)
                subject_matches = query_term_set & subject_terms
                predicate_matches = query_term_set & predicate_terms
                value_matches = query_term_set & value_terms
                matched_terms = tuple(
                    sorted(subject_matches | predicate_matches | value_matches)
                )
                if not matched_terms:
                    continue

                score = (
                    self.predicate_weight * len(predicate_matches)
                    + self.subject_weight * len(subject_matches)
                    + self.value_weight * len(value_matches)
                )
                candidates.append(
                    ContextCandidate(
                        subject=subject,
                        predicate=predicate,
                        operative_claim_id=operative.id,
                        score=score,
                        matched_terms=matched_terms,
                    )
                )

            candidates.sort(
                key=lambda candidate: (
                    -candidate.score,
                    candidate.subject,
                    candidate.predicate,
                    str(candidate.operative_claim_id),
                )
            )
            selected = tuple(candidates[:limit])

        return CandidateSet(
            request_id=request.id,
            snapshot_id=f"sqlite:{frontier}",
            canonical_frontier=str(frontier),
            query_terms=query_terms,
            candidates=selected,
            generator_version=self.version,
        )


def _tokenize(text: str) -> set[str]:
    return {match.group(0).casefold() for match in _TOKEN_RE.finditer(text)}


def _semantic_tokens(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return _tokenize(value)
    if isinstance(value, bool):
        return {"true" if value else "false"}
    if isinstance(value, (int, float)):
        return _tokenize(str(value))
    if isinstance(value, Mapping):
        tokens: set[str] = set()
        for key, item in value.items():
            tokens.update(_tokenize(key))
            tokens.update(_semantic_tokens(item))
        return tokens
    if isinstance(value, tuple):
        tokens: set[str] = set()
        for item in value:
            tokens.update(_semantic_tokens(item))
        return tokens
    raise TypeError("candidate generator received non-canonical semantic value")
