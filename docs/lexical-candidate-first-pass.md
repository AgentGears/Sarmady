# Lexical Candidate Generation — First-Pass Review

Status: **FIRST-PASS REVIEW COMPLETE / FROZEN**

Implementation head reviewed before this review-record commit: `ea00fbeac93a7e7eb71eb4036d0329f66a95c150`.

This file freezes the maintainer's independent exhaustive review before Codex is invoked. It must not be retroactively rewritten to incorporate Codex findings. Later factual appendices may record second-review provenance and disposition, but this first-pass assessment remains the baseline.

## Review objective

Review the M2 lexical candidate-generation slice as a bounded architecture and implementation change, not merely as a unit-test addition. The review asks whether Sarmady can discover potentially relevant semantic keys from a natural-language query without collapsing retrieval into canonical truth, coverage sufficiency, memory strengthening, or provider-specific machinery.

## Review surface

### Objectives and requirements

The slice is expected to:

- introduce candidate discovery before adaptive context expansion;
- keep candidate relevance distinct from context sufficiency;
- preserve `memory != context` and `SEEN != USED`;
- run against one transactionally pinned semantic snapshot;
- respect existing `known_at` / `valid_at` epistemic resolution;
- exclude claims that are not presently eligible for active-memory recall;
- expose deterministic, inspectable lexical ranking as a correctness baseline;
- remain replaceable by later indexed/semantic retrieval machinery;
- avoid schema changes, provider SDKs, embeddings, adaptive planning, and canonical writes.

### Architecture and ownership

Reviewed components:

- `src/sarmady/context/models.py` — generator-neutral derived candidate DTOs;
- `src/sarmady/context/candidates.py` — lexical retrieval implementation;
- `src/sarmady/storage/sqlite/store.py` — snapshot-bound semantic-key enumeration;
- `src/sarmady/context/__init__.py` — public exports;
- `tests/test_lexical_candidates.py` — behavioral and concurrency evidence;
- `docs/context-retrieval.md`, `docs/architecture.md`, `docs/milestones.md`, `README.md` — architecture/roadmap claims.

Adjacent contracts inspected:

- exact and multi-key coverage compilers;
- temporal resolution and contradiction semantics;
- memory lifecycle access/gating;
- projection lineage capture and wildcard dependency semantics;
- strict canonical semantic-value representation;
- schema version and storage boundaries.

### Interfaces and data flow

```text
ContextRequest
     |
     v
LexicalCandidateGenerator
     |
context_read_snapshot()
     |
semantic_keys() -> resolved_state() -> claim() -> active-memory gate
     |
lexical token evidence + deterministic ranking
     |
     v
CandidateSet (derived, immutable, ephemeral)
```

No path from this slice performs semantic admission, memory lifecycle writes, context-projection registration, model invocation, or external action.

### Trust and failure boundaries

- Input boundary: `ContextRequest.query`, temporal selectors, and candidate `limit`.
- Canonical-read boundary: SQLite pinned read snapshot.
- Semantic boundary: canonical `resolved_state()` determines operative/competing claims; lexical code does not reconstruct truth independently.
- Memory boundary: candidate eligibility uses memory admission/lifecycle state; retrieval itself emits no lifecycle event.
- Derived-output boundary: scores/signals are generator-local evidence, not canonical truth or calibrated confidence.
- Concurrency boundary: the key-space scan and all downstream reads must remain on one WAL snapshot while another writer may commit.

## Independent review passes

### A — Intent and requirement review

The change solves the intended next M2 problem at the smallest useful scope: candidate discovery without yet attempting semantic embeddings, requirement planning, or adaptive expansion. The design explicitly preserves relevance versus sufficiency and does not claim lexical ranking is a context compiler.

No conflicting product requirement was identified. The main success condition is architectural: a technically functional search would still be unacceptable if it strengthened memory on exposure, bypassed temporal resolution, mixed snapshots, persisted relevance as truth, or forced later semantic retrievers into lexical-only contracts.

### B — Structural review

The boundary is acceptable after the findings below were fixed:

- candidate DTOs live in `context.models` and do not import storage;
- the lexical service owns SQLite-specific orchestration, consistent with current M2 exact/coverage compiler implementations;
- semantic-key enumeration remains an internal snapshot capability rather than a new canonical table/materialization;
- no schema/index migration is introduced;
- later semantic/indexed retrievers can reuse the candidate DTOs without pretending to expose lexical terms.

Dependency direction remains consistent with the current architecture: context service code may depend on the SQLite adapter, while the domain contracts remain storage-independent.

### C — Correctness review

Verified by source tracing and regression coverage:

- empty/nonlexical queries fail rather than creating meaningless candidates;
- `limit` must be a positive integer and booleans are rejected;
- a post-construction-mutated non-string request query fails at the generator boundary;
- semantic values are tokenized only from the existing strict canonical value shapes;
- the operative claim must exist and be in active memory;
- active competing claims may contribute relevance evidence without replacing the operative claim ID;
- historical epistemic resolution uses `known_at` and `valid_at` via the canonical resolver;
- ranking is stable for a fixed runtime/generator version/snapshot;
- truncation occurs after deterministic ordering;
- candidate scores are finite generator-local rank values, not probabilities.

### D — Failure and concurrency review

Examined malformed input, absent state, inactive memory, contested state, historical state, closed snapshot use, and concurrent writer behavior.

A dedicated two-connection WAL test proves that semantic-key enumeration remains pinned while another connection commits a new semantic key. The reader continues to see the old key space and resolves the newly written key as missing until its snapshot closes.

Candidate generation is read-only; interruption cannot leave partial canonical state because there is no write transaction or durable candidate persistence.

### E — Security and trust review

No new authentication, authorization, secret, command-execution, provider, deserialization, or external-network surface is introduced.

The relevant trust issue is semantic authority. The generator cannot create/adopt claims, mutate memory, or convert relevance into coverage. Canonical interpretation stays in the existing resolver and memory admission/lifecycle mechanisms.

Query/value text is treated as data for tokenization only; it is not executed, interpolated into SQL, or passed to a model/tool.

### F — Operability review

`CandidateSet` carries:

- request identity;
- exact snapshot/frontier identity;
- generator version;
- ranked candidate records and diagnostic signals.

This is sufficient for an ephemeral retrieval result to explain which generator/version produced the ordering. Candidate sets are deliberately not persisted in this slice, so they are not an audit log or durable replay artifact.

The implementation has no new configuration or migration/rollback burden.

### G — Maintainability review

The lexical algorithm is intentionally simple and contained. Scoring semantics are sealed inside `lexical-v0.1` rather than mutable public knobs, preventing silent semantic drift under an unchanged provenance label.

The whole-key scan is O(N). That is acceptable as a correctness baseline but is not a production-scale indexing architecture. The generic candidate DTO avoids coupling future BM25/vector/agentic retrievers to lexical-specific fields.

### H — Evidence review

Directly observed:

- source boundaries and no-write control flow;
- use of canonical temporal resolution;
- active-memory gating;
- wildcard dependency acquisition for whole-key enumeration;
- deterministic sort/tie-break behavior;
- CI success on Python 3.12/3.13/3.14 for implementation head `ea00fbe...`;
- 114 tests passed on the Python 3.13 CI job for that head.

Strongly inferred:

- O(N) scan cost will become unsuitable as semantic-key cardinality grows substantially;
- the conservative wildcard is safe but will be too coarse if this capture is later used directly for long-lived projections.

Explicitly unverified / outside this slice:

- ranking quality on realistic corpora;
- multilingual relevance quality beyond Python's Unicode token/casefold behavior;
- BM25/vector retrieval quality and calibration;
- adaptive expansion behavior;
- natural-language-to-coverage planning;
- large-scale latency/resource behavior.

## First-pass findings register

### FP-P2-01 — Generic candidate contracts encoded lexical-only semantics

**Area:** Architecture / public contract

**Finding:** The initial DTO used integer `score`, mandatory `matched_terms`, and candidate-set `query_terms`, despite the architectural intent that future semantic/embedding retrievers reuse the same candidate seam where practical.

**Evidence:** Initial implementation in this PR revision before `eda2f7c...`.

**Why it matters:** A supposedly generic contract would force heterogeneous retrievers to fabricate lexical metadata or create parallel incompatible DTOs, leaking one retrieval mechanism into the architecture.

**Severity:** P2

**Confidence:** High

**Disposition:** **ACCEPTED / FIXED.** `ContextCandidate` now uses finite generator-local `rank_score` plus optional `signals`; `CandidateSet` no longer carries lexical query terms. Regression coverage proves a nonlexical-style finite negative score is valid while non-finite scores fail.

### FP-P2-02 — Mutable ranking semantics under an unchanged generator version

**Area:** Provenance / determinism

**Finding:** The initial lexical generator exposed subject/predicate/value weights as mutable public class attributes while reporting a fixed `lexical-v0.1` version.

**Evidence:** Initial implementation in this PR revision before `7ef7431...`.

**Why it matters:** Callers could alter ranking behavior while preserving the same provenance/version label, undermining reproducibility and auditability.

**Severity:** P2

**Confidence:** High

**Disposition:** **ACCEPTED / FIXED.** Public mutable weights were removed; the v0.1 profile is sealed in the implementation and instance slots reject ad-hoc weight injection. Changing the scoring profile now requires a new generator version.

### FP-P2-03 — Snapshot enumeration lacked direct concurrent-writer evidence

**Area:** Test adequacy / concurrency

**Finding:** The first test set exercised snapshot closure but did not directly prove that whole semantic-key enumeration remains pinned while another connection commits a new key.

**Evidence:** Initial test surface before `df521eb...`.

**Why it matters:** Candidate discovery depends on negative space as well as present rows. A mixed-snapshot key scan could make the advertised candidate frontier false even if individual claim reads were otherwise correct.

**Severity:** P2 evidence gap

**Confidence:** High

**Disposition:** **ACCEPTED / FIXED.** Added a two-connection WAL regression proving repeated enumeration and resolution remain on the original snapshot until close.

### FP-DOC-01 — Architecture document reported stale schema version

**Area:** Documentation

**Finding:** `docs/architecture.md` still said schema v5 although current `SCHEMA_VERSION` is 6.

**Evidence:** Direct comparison with `src/sarmady/storage/sqlite/schema.py`.

**Why it matters:** Misstates the current durable-storage baseline, though it does not alter runtime correctness.

**Severity:** Documentation

**Confidence:** High

**Disposition:** **ACCEPTED / FIXED.** Architecture text now reports schema v6.

## Open questions

1. **Historical memory lifecycle.** `known_at` reconstructs historical epistemic state, but memory eligibility is evaluated from the current materialized lifecycle state. This is inherited from the exact/coverage compilers. A historical query can therefore find the historically operative claim but exclude it if that memory is archived today. This PR does not claim bitemporal memory-lifecycle reconstruction.
2. **Candidate durability.** Candidate sets are intentionally ephemeral. If future executive/reasoning flows need deterministic audit/replay of retrieval decisions, Sarmady may need a durable retrieval receipt rather than persisting candidate state as truth.
3. **Index replacement.** A future indexed retriever needs explicit snapshot/index freshness semantics before it can replace the O(N) scan without weakening the frontier contract.
4. **Cross-generator ranking.** `rank_score` is only meaningful within one generator/version. Any future ensemble/fusion layer will need its own normalization/calibration contract rather than comparing raw scores directly.

## Assumptions

- Semantic keys are bounded enough in M2 tests for an O(N) scan to be a correctness baseline.
- Current memory lifecycle is the intended eligibility gate for all existing context compilers until historical lifecycle semantics are separately designed.
- Python/runtime Unicode behavior is part of the lexical generator version's execution environment; candidate sets are not durable cross-runtime replay artifacts.
- The current SQLite-specific service dependency is acceptable for this executable adapter slice because the domain candidate contracts themselves remain storage-neutral.

## Potential failure modes retained for later work

- latency/resource growth as key cardinality increases;
- recall loss from exact token matching, morphology, synonyms, spelling variation, or multilingual segmentation;
- over-conservative invalidation if wildcard enumeration lineage is later attached directly to durable projections;
- stale or inconsistent external retrieval indexes if a future index is not frontier-aware;
- accidental use of generator-local scores as calibrated confidence or cross-retriever comparable values.

## Missing evidence

- corpus-level precision/recall benchmarks;
- performance/load measurements at large semantic-key cardinality;
- multilingual tokenization benchmarks;
- semantic/vector index snapshot-consistency design;
- historical memory-lifecycle query semantics.

These omissions limit claims about retrieval quality and scale; they do not invalidate the narrow correctness contract proven by this slice.

## Areas reviewed with no issue found

- canonical semantic state remains read-only from the candidate generator;
- retrieval exposure does not emit `SEEN` or `USED`;
- current memory lifecycle gating is consistent with existing context compilers;
- canonical temporal resolver remains the sole owner of operative/competing claim interpretation;
- contested claims do not become alternate canonical heads merely because their values match a query;
- key enumeration is parameter-free SQL over canonical tables and creates no SQL-injection surface;
- no provider/model/tool dependency enters the kernel;
- no schema migration or new canonical materialization is required;
- public candidate contracts do not import SQLite/storage;
- candidate relevance is not converted into `COMPLETE` / `PARTIAL` / `INSUFFICIENT` coverage;
- no token-budget or adaptive-expansion claim is made;
- no calibrated-probability claim is made for lexical scores;
- closed snapshot capabilities reject further semantic reads;
- deterministic tie-breaking is explicit;
- documentation now states the O(N) and present-lifecycle limitations.

## Areas requiring deeper verification in future slices

- historical/bitemporal memory lifecycle;
- candidate-to-coverage planning;
- adaptive context expansion loops;
- indexed/semantic retrieval freshness and consistency;
- score normalization if multiple retrievers are fused;
- durable retrieval receipts if executive audit/replay requires them.

## Frozen first-pass state

```text
FIRST-PASS REVIEW COMPLETE

Known findings:
  FP-P2-01 accepted/fixed — generic candidate contract leaked lexical semantics.
  FP-P2-02 accepted/fixed — ranking profile was mutable under a fixed version.
  FP-P2-03 accepted/fixed — direct concurrent enumeration evidence was missing.
  FP-DOC-01 accepted/fixed — architecture schema version was stale.

Suspected findings:
  None currently blocking.

Open questions:
  Historical memory lifecycle, candidate durability, indexed-retriever frontier
  semantics, and cross-generator score fusion.

Areas considered sound:
  Semantic authority boundary, read-only candidate generation, snapshot pinning,
  temporal resolution, present active-memory gating, contradiction handling,
  deterministic lexical ranking, generator-neutral DTOs, and relevance !=
  sufficiency separation.

Areas requiring deeper verification:
  Retrieval quality/scale, bitemporal memory lifecycle, semantic/indexed
  retrieval, adaptive expansion, and retriever fusion.
```

Codex must review independently from this frozen baseline. If Codex is unavailable because of quota/service limits, the documented substitute exact-head second-review process applies without rewriting this first-pass record.
