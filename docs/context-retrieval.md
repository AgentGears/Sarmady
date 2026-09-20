# Context Retrieval v0.2

Sarmady separates **candidate relevance** from **planned information obligations** from **context sufficiency**.

The M2 lexical candidate slice is a derived discovery mechanism. It helps the context system identify semantic keys that may matter to a `ContextRequest`; it does not decide that a requirement has been satisfied and it does not mutate canonical memory.

## Contract

`LexicalCandidateGenerator` consumes a `ContextRequest` value and returns an immutable, ephemeral `CandidateSet` containing:

- the request ID;
- a deterministic fingerprint of the complete source-request semantics;
- the pinned SQLite snapshot/frontier used for discovery;
- ranked `ContextCandidate` records;
- the generator version;
- an `is_exhaustive` flag.

The generator does not persist the request or candidate set. Persistence begins only at later durable boundaries such as `ContextProjection` registration.

The request fingerprint binds an ephemeral candidate receipt to the exact request semantics that produced it. An ID match alone is insufficient because candidate generation does not persist the source request; a caller could otherwise reconstruct or mutate a request under the same UUID and reuse candidates produced for different semantics.

`is_exhaustive` has a deliberately narrow meaning:

> the generator knows that no additional candidate satisfying **its own matching rule** was dropped from this snapshot result.

It does **not** claim perfect retrieval recall. `lexical-v0.2` computes every lexical match before applying `limit`, so it can distinguish a complete result from a truncated top-k result. A later approximate/vector retriever may conservatively report `False` unless its own completeness semantics are provable.

Each candidate identifies one semantic `(subject, predicate)` key and the operative claim resolved for the request's `known_at` / `valid_at` boundary. The generic candidate contract carries a finite generator-local `rank_score` plus optional diagnostic `signals`. Those values are meaningful only within a generator/version; they are not calibrated probabilities and must not be compared across heterogeneous retrievers.

A candidate means only:

> this semantic key had generator-specific evidence of relevance in the pinned snapshot.

It does **not** mean:

- the context is complete;
- the claim is true merely because it matched;
- a coverage obligation is satisfied;
- the candidate set is exhaustive merely because it is short;
- the candidate should be admitted to or strengthened in memory;
- the candidate should be persisted as canonical state.

## Snapshot and temporal semantics

Candidate generation runs inside one `context_read_snapshot()` transaction. The semantic-key enumeration and every subsequent resolution/read therefore see one SQLite WAL snapshot.

Enumeration is negative-space sensitive: a later semantic write could introduce a previously absent matching key. The snapshot proxy consequently records the conservative `semantic:*` dependency for key-space enumeration. This is intentionally broader than exact-key dependencies and makes the enumeration safe to reuse if candidate discovery is later integrated directly into projection compilation under the same capture discipline.

For each semantic key, the generator calls canonical temporal resolution using the request's `known_at` and `valid_at` values. Historical discovery therefore ranks the claim that was operative under the requested knowledge/world-time boundary rather than blindly using today's materialized head.

## Memory gating

A semantic key is eligible only when its operative claim is admitted to **ACTIVE** memory. Archived, tombstoned, or otherwise inactive operative claims are not returned as candidates.

When the resolved key is contested, values from active competing claims may contribute lexical evidence to the same semantic-key candidate. The candidate still names the canonical operative claim; contradiction closure and sufficiency remain the responsibility of the exact/coverage compiler.

Candidate generation performs reads only. It does not emit `SEEN` or `USED` lifecycle events. This preserves the memory invariant that exposure/retrieval alone does not strengthen memory.

## Lexical scoring

Version `lexical-v0.2` preserves the v0.1 ranking profile while strengthening candidate-receipt semantics with request binding and exhaustiveness metadata:

- predicate-term match: weight 5;
- subject-term match: weight 3;
- active claim-value term match: weight 1.

The weights are sealed inside the versioned implementation rather than exposed as mutable public configuration. Changing the profile requires a new generator version.

Tokenization is Unicode-aware, case-folded, and treats underscore/punctuation as separators. Canonical nested mapping/sequence values are traversed recursively so keys and scalar values can contribute terms. Each lexical match is exposed diagnostically as a `term:<token>` candidate signal.

Candidates with no matching term are omitted. Ranking is deterministic for a fixed runtime/version and snapshot: descending `rank_score`, then subject, predicate, and operative claim ID. `limit` truncation happens only after that stable ordering.

These weights are an implementation baseline, not a learned relevance model or calibrated probability.

## Relationship to requirement planning

Candidate retrieval and requirement planning are separate stages. `ControlledRequirementPlanner` may consume an exhaustive, request-bound candidate set and propose exact obligations, but candidate score alone never authorizes a hard semantic constraint. Ambiguity or non-exhaustive retrieval causes abstention rather than over-resolution. See `docs/requirement-planning.md`.

## Deliberate limitations

This slice does not implement:

- stemming, synonyms, fuzzy matching, BM25, embeddings, or vector search;
- general multi-intent natural-language planning;
- adaptive coverage expansion;
- candidate persistence or a durable retrieval index;
- token-budget packing;
- memory strengthening on retrieval;
- a claim that lexical ranking alone produces sufficient context.

The current implementation scans the visible semantic-key space and is therefore an O(N) correctness baseline, not the final indexing strategy. A later semantic or indexed retriever should emit the same generator-neutral candidate contracts where practical, so retrieval machinery remains replaceable while planning, coverage, and projection semantics stay stable.
