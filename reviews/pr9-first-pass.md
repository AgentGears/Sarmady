# PR #9 — Lexical Candidate Generation First-Pass Review

Status: **FIRST-PASS REVIEW COMPLETE / FROZEN**

Implementation head reviewed before this review-record commit: `ea00fbeac93a7e7eb71eb4036d0329f66a95c150`.

This record freezes the maintainer's independent exhaustive review before Codex is invoked. It must not be retroactively rewritten to incorporate Codex findings.

## Review objective

Review the M2 lexical candidate-generation slice as a bounded architecture and implementation change, not merely as a unit-test addition. The review asks whether Sarmady can discover potentially relevant semantic keys from a natural-language query without collapsing retrieval into canonical truth, coverage sufficiency, memory strengthening, or provider-specific machinery.

## Review surface

Reviewed objectives, architecture, interfaces, dependencies, data flow, trust/failure boundaries, tests, operational assumptions, performance assumptions, and unresolved decisions across:

- `src/sarmady/context/models.py` — generator-neutral derived candidate DTOs;
- `src/sarmady/context/candidates.py` — lexical retrieval implementation;
- `src/sarmady/storage/sqlite/store.py` — snapshot-bound semantic-key enumeration;
- `src/sarmady/context/__init__.py` — public exports;
- `tests/test_lexical_candidates.py` — behavioral and concurrency evidence;
- `docs/context-retrieval.md`, `docs/architecture.md`, `docs/milestones.md`, `README.md` — architecture/roadmap claims;
- adjacent exact/coverage compilers, temporal resolution, contradiction handling, memory lifecycle, projection lineage capture, strict canonical values, and schema contracts.

Data flow reviewed:

```text
ContextRequest
     |
LexicalCandidateGenerator
     |
context_read_snapshot()
     |
semantic_keys() -> resolved_state() -> claim() -> active-memory gate
     |
lexical token evidence + deterministic ranking
     |
CandidateSet (derived, immutable, ephemeral)
```

No path in this slice performs semantic admission, memory lifecycle writes, context-projection registration, model invocation, or external action.

## Independent review passes

### Intent / requirements

The change addresses the next M2 frontier at narrow scope: candidate discovery before embeddings, automatic requirement planning, or adaptive expansion. A functional search would still be architecturally wrong if it strengthened memory on exposure, bypassed temporal resolution, mixed snapshots, persisted relevance as truth, or forced future retrievers into lexical-only contracts.

### Structure

After the findings below were fixed, the boundary is acceptable: domain candidate DTOs remain storage-neutral; SQLite-specific orchestration lives in the lexical service/snapshot adapter; semantic-key enumeration is a derived read rather than a new canonical table; no schema/index migration is introduced.

### Correctness

Verified by source tracing and regressions:

- nonlexical/empty queries fail;
- `limit` is a positive integer and rejects bool;
- post-construction-mutated non-string query fails at the generator boundary;
- canonical values are traversed only through supported strict semantic shapes;
- operative claim must exist and be active memory;
- active competing claims may contribute relevance evidence without replacing the operative claim ID;
- canonical `known_at` / `valid_at` resolution is reused;
- ranking/tie-breaks are deterministic for fixed runtime/version/snapshot;
- scores are finite generator-local rank values, not probabilities.

### Failure / concurrency

Malformed input, absent state, inactive memory, contested state, historical state, closed-snapshot reads, and concurrent writer behavior were examined. A two-connection WAL test proves whole-key enumeration remains pinned while another connection adds a new key. Candidate generation is read-only, so interruption cannot leave partial canonical state.

### Security / trust

No new auth, authorization, secrets, command execution, provider, deserialization, or network surface. Query/value text is tokenized as data only and is not executed or interpolated into SQL. The generator cannot create claims, mutate memory, or convert relevance into coverage.

### Operability

`CandidateSet` carries request identity, snapshot/frontier, generator version, and ranked candidates/signals. It is intentionally ephemeral, not an audit log or durable retrieval receipt. No migration/configuration burden is added.

### Maintainability / performance

The algorithm is deliberately simple. Scoring semantics are sealed inside `lexical-v0.1` instead of mutable public knobs. Whole-key scanning is O(N), accepted only as a correctness baseline. Generic DTOs do not encode lexical-specific fields.

### Evidence

Directly observed:

- no-write control flow;
- canonical temporal resolution;
- active-memory gating;
- wildcard dependency for key-space enumeration;
- deterministic ranking;
- Python 3.12/3.13/3.14 CI success on implementation head `ea00fbe...`;
- 114 tests passed on the Python 3.13 job.

Not established by this slice: corpus-level relevance quality, multilingual quality, large-scale latency, BM25/vector calibration, adaptive expansion, automatic requirement planning, or historical memory-lifecycle semantics.

## Findings register

### FP-P2-01 — Generic candidate contract encoded lexical-only semantics

Initial DTOs used integer `score`, mandatory `matched_terms`, and candidate-set `query_terms` while the seam was intended for future heterogeneous retrieval. That would force nonlexical retrievers to fabricate lexical metadata or fork the contract.

**Disposition: ACCEPTED / FIXED.** `ContextCandidate` now uses finite generator-local `rank_score` plus optional `signals`; `CandidateSet` no longer carries lexical query terms. Regression proves nonlexical-style finite negative scores are valid and non-finite values fail.

### FP-P2-02 — Mutable ranking semantics under a fixed generator version

Initial subject/predicate/value weights were mutable public class attributes while the generator still reported `lexical-v0.1`, allowing behavior drift without provenance drift.

**Disposition: ACCEPTED / FIXED.** Public weight knobs removed; profile sealed in versioned implementation; slots reject ad-hoc weight injection. A scoring-profile change now requires a new generator version.

### FP-P2-03 — Missing direct concurrent enumeration evidence

Initial tests did not prove whole semantic-key enumeration remained pinned while a separate writer added a new key. Candidate discovery depends on negative space, so this was a material evidence gap.

**Disposition: ACCEPTED / FIXED.** Added two-connection WAL regression proving repeated enumeration/resolution remain on the captured snapshot until close.

### FP-DOC-01 — Architecture reported stale schema version

`docs/architecture.md` still named schema v5 while the runtime is schema v6.

**Disposition: ACCEPTED / FIXED.** Documentation now reports v6.

## Open questions / explicit limitations

1. **Historical memory lifecycle:** `known_at` reconstructs historical epistemic state, but memory eligibility is current lifecycle state, inherited from exact/coverage compilers. This PR does not claim bitemporal memory lifecycle.
2. **Candidate durability:** candidate sets are ephemeral; future audit/replay may require a durable retrieval receipt rather than canonicalizing candidates.
3. **Index replacement:** an indexed retriever needs explicit frontier/index freshness semantics before replacing O(N) scan.
4. **Cross-generator ranking:** raw `rank_score` is only meaningful inside one generator/version; fusion needs a separate normalization/calibration contract.
5. **Scale:** O(N) scan is a correctness baseline, not a production-scale index.
6. **Unicode/runtime:** lexical determinism is for fixed runtime/generator version + snapshot, not a cross-runtime durable replay guarantee.
7. **Wildcard dependency:** whole-key enumeration conservatively records `semantic:*`; safe, but potentially coarse for future long-lived projections.

## Areas reviewed with no issue found

- canonical semantic state remains read-only;
- retrieval emits no `SEEN`/`USED`;
- present active-memory gating matches existing compilers;
- canonical resolver owns operative/competing state;
- contested values do not become alternate canonical heads;
- no SQL-injection path;
- no provider/model/tool dependency enters kernel semantics;
- no schema migration/materialization is needed;
- public candidate contracts do not import storage;
- relevance does not become coverage status;
- no token-budget/adaptive-expansion/calibrated-probability claim;
- closed snapshot capability rejects further reads;
- tie-breaking is explicit.

## Frozen state

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
  semantics, cross-generator score fusion, scale, and Unicode/runtime replay.

Areas considered sound:
  Semantic authority boundary, read-only candidate generation, snapshot pinning,
  temporal resolution, present active-memory gating, contradiction handling,
  deterministic lexical ranking, generator-neutral DTOs, and relevance !=
  sufficiency separation.

Areas requiring deeper verification:
  Retrieval quality/scale, bitemporal memory lifecycle, semantic/indexed
  retrieval, adaptive expansion, and retriever fusion.
```

Codex must review PR #9 independently from this frozen baseline. If Codex is unavailable because of quota/service limits, the documented substitute exact-head second-review process applies without rewriting this record.
