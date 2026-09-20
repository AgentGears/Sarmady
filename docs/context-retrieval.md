# Context Retrieval v0.1

Sarmady separates **candidate relevance** from **context sufficiency**.

The M2 lexical candidate slice is a derived discovery mechanism. It helps the context system identify semantic keys that may matter to a `ContextRequest`; it does not decide that a requirement has been satisfied and it does not mutate canonical memory.

## Contract

`LexicalCandidateGenerator` consumes a `ContextRequest` value and returns an immutable, ephemeral `CandidateSet` containing:

- the request ID;
- the pinned SQLite snapshot/frontier used for discovery;
- ranked `ContextCandidate` records;
- the generator version.

The generator does not persist the request or candidate set. Persistence begins only at later durable boundaries such as `ContextProjection` registration.

Each candidate identifies one semantic `(subject, predicate)` key and the operative claim resolved for the request's `known_at` / `valid_at` boundary. The generic candidate contract carries a finite generator-local `rank_score` plus optional diagnostic `signals`. Those values are meaningful only within a generator/version; they are not calibrated probabilities and must not be compared across heterogeneous retrievers.

A candidate means only:

> this semantic key had generator-specific evidence of relevance in the pinned snapshot.

It does **not** mean:

- the context is complete;
- the claim is true merely because it matched;
- a coverage obligation is satisfied;
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

Version `lexical-v0.1` uses transparent exact token matching:

- predicate-term match: weight 5;
- subject-term match: weight 3;
- active claim-value term match: weight 1.

The weights are sealed inside the versioned implementation rather than exposed as mutable public configuration. Changing the profile requires a new generator version.

Tokenization is Unicode-aware, case-folded, and treats underscore/punctuation as separators. Canonical nested mapping/sequence values are traversed recursively so keys and scalar values can contribute terms. Each lexical match is exposed diagnostically as a `term:<token>` candidate signal.

Candidates with no matching term are omitted. Ranking is deterministic for a fixed runtime/version and snapshot: descending `rank_score`, then subject, predicate, and operative claim ID. `limit` truncation happens only after that stable ordering.

These weights are an implementation baseline, not a learned relevance model or calibrated probability.

## Deliberate limitations

This slice does not implement:

- stemming, synonyms, fuzzy matching, BM25, embeddings, or vector search;
- automatic natural-language-to-coverage-requirement planning;
- adaptive coverage expansion;
- candidate persistence or a durable retrieval index;
- token-budget packing;
- memory strengthening on retrieval;
- a claim that lexical ranking alone produces sufficient context.

The current implementation scans the visible semantic-key space and is therefore an O(N) correctness baseline, not the final indexing strategy. A later semantic or indexed retriever should emit the same generator-neutral candidate contracts where practical, so retrieval machinery remains replaceable while coverage and projection semantics stay stable.
