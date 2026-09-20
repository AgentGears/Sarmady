# PR #10 — Controlled Requirement Planning — First-Pass Review

Status: **FIRST-PASS REVIEW COMPLETE / FROZEN**

Implementation head reviewed: `a2493e56e0450b7403fe4badf099ff016e1b5d20`.

This document freezes the maintainer's exhaustive review before Codex is invoked. It lives on a separate review-ledger branch so the independent second reviewer is not primed by these findings. This baseline must not be rewritten to incorporate later Codex feedback.

## Objective

Review the M2 requirement-planning slice as an architecture boundary between retrieval relevance and context sufficiency. The implementation must be able to infer a narrowly controlled exact information obligation from natural-language input while preserving ambiguity, abstaining when its evidence is insufficient, and never converting retrieval rank into semantic authority.

The intended pipeline is:

```text
ContextRequest
    -> CandidateSet                # relevance only
    -> RequirementPlan             # resolved / ambiguous / abstained
    -> new ContextRequest          # exact obligations, new identity
    -> CoverageContextCompiler     # actual support/sufficiency
```

## Requirements and invariants reviewed

The slice is expected to preserve:

- `candidate relevance != planned obligation != coverage sufficiency`;
- `retrieval != memory strengthening`;
- a hard requirement must not be emitted from a truncated candidate set;
- ambiguity must be a first-class result, not silently broken by rank preference;
- source-request semantics must be bound to ephemeral candidate/plan artifacts;
- a planner may not rebind an existing `ContextRequest.id` to changed semantics;
- planning remains derived computation and performs no canonical semantic write;
- a resolved plan is not itself evidence that coverage exists;
- later coverage compilation must independently resolve/support the exact obligation;
- provider/model/storage details must not leak into pure planning contracts.

## Review surface

Primary code:

- `src/sarmady/context/models.py`
- `src/sarmady/context/_lexical.py`
- `src/sarmady/context/candidates.py`
- `src/sarmady/context/planning.py`
- `src/sarmady/context/__init__.py`

Primary tests:

- `tests/test_lexical_candidates.py`
- `tests/test_requirement_planning.py`
- `tests/test_requirement_planning_invariants.py`

Documentation:

- `README.md`
- `docs/architecture.md`
- `docs/context-retrieval.md`
- `docs/requirement-planning.md`
- `docs/milestones.md`

Adjacent contracts inspected:

- `CoverageContextCompiler` and exact requirement semantics;
- context-request persistence/collision rules in `ProjectionStoreMixin`;
- pinned snapshot and temporal resolution semantics;
- memory-active gating inherited from candidate discovery;
- the DIC v0.4 planner experiment and its explicit abstention behavior.

## Architecture and ownership map

```text
canonical semantic state
        |
        v
LexicalCandidateGenerator (SQLite read service)
        |
        v
CandidateSet (derived, ephemeral, snapshot-bound)
        |
        v
ControlledRequirementPlanner (storage-neutral pure planner)
        |
        v
RequirementPlan (derived, ephemeral)
        |
        v
new ContextRequest (exact obligations, new UUID)
        |
        v
CoverageContextCompiler (fresh pinned read)
        |
        v
ContextProjection (durable derived lineage)
```

The planner itself imports only storage-neutral context contracts/helpers. SQLite remains confined to candidate discovery and coverage compilation.

## Trust and failure boundaries

- **Query/input boundary:** source `ContextRequest` and controlled lexical parsing.
- **Retrieval boundary:** candidate sets are derived values; rank is relevance evidence only.
- **Compatibility boundary:** v0.1's uniqueness proof is explicitly pinned to `lexical-v0.2` semantics.
- **Integrity boundary:** request fingerprint binds exact source semantics but is not a signature/MAC/capability.
- **Ambiguity boundary:** non-resolved plans are structurally unable to carry hard exact requirements.
- **Identity boundary:** adding planned obligations requires a new request UUID.
- **Freshness boundary:** planning is anchored to the candidate snapshot; it is not a later-frontier uniqueness fence.
- **Coverage boundary:** a resolved plan must still pass independent coverage compilation.
- **Write boundary:** candidate generation/planning itself creates no canonical writes or memory telemetry.

## Independent review passes

### A — Intent and requirements

The slice addresses the next M2 seam without prematurely introducing LLM planning, embeddings, or adaptive expansion. It carries forward the DIC v0.4 rule that irreducible ambiguity must be preserved rather than over-resolved.

The scope is deliberately narrower than general natural-language planning: exactly one directly lexical predicate obligation may be emitted. Synonyms, predicate ontologies, multi-intent decomposition, learned entity resolution, pronouns, and temporal language parsing remain out of scope.

### B — Structure and dependency direction

The final structure is sound after a first-pass fix moved lexical normalization into `_lexical.py`. The pure requirement planner no longer imports `candidates.py` and therefore no longer inherits its SQLite dependency transitively.

Domain/derived contracts remain in `context.models`; SQLite-specific orchestration remains outside them. No schema change or new canonical materialization is introduced.

### C — Correctness and invariants

Verified by source tracing and tests:

- `CandidateSet` carries the exact source-request fingerprint;
- `lexical-v0.2` computes all lexical matches before `limit`, so it can report whether top-k truncation occurred;
- a truncated candidate set causes planner abstention before identity resolution;
- v0.1 refuses candidate sets from generators whose exhaustiveness universe it does not understand;
- direct predicate lexical evidence is required; value-only relevance cannot infer a predicate;
- multiple directly matching predicates cause abstention rather than guessed decomposition;
- subject collisions are resolved only by a discriminating subject token in the query;
- retrieval rank never breaks unresolved subject ambiguity;
- equivalent timezone-offset representations fingerprint to the same UTC semantic time;
- non-resolved plans cannot carry hard requirements;
- a resolved v0.1 plan must contain exactly one requirement/selected candidate at derivation time;
- the derived request must use a new UUID and preserves budgets, goal/task, labels, and temporal selectors;
- coverage compilation independently verifies support and persists only the derived request/projection.

### D — Failure and concurrency

The planner has no write transaction and cannot leave partial canonical state on interruption.

Candidate discovery retains PR #9's one-snapshot WAL behavior. Planning consumes that immutable candidate receipt without further store reads. Semantic state may change after the candidate snapshot; this does not rewrite the historical planning interpretation. Later coverage compilation opens its own pinned snapshot and revalidates the selected exact key.

This means v0.1 does **not** prove that identity remains uniquely resolvable at a later frontier. That limitation is explicit and non-blocking for a snapshot-bound interpretation slice.

### E — Security and trust

No new authentication, authorization, provider, tool, command execution, network, deserialization, or secret surface is introduced.

`request_fingerprint` is deterministic integrity metadata, not authentication. `generator_version` and `is_exhaustive` are public-data fields and are not safe self-attestation from an untrusted model/tool. The current in-process planner assumes candidate receipts are produced by the trusted runtime path.

That assumption does not grant a new semantic-admission capability: code able to fabricate arbitrary planner inputs could already construct an exact `ContextRequest`; canonical claim admission remains elsewhere.

### F — Operability and provenance

Derived artifacts carry enough ephemeral provenance to identify:

- source request semantics;
- candidate snapshot/frontier;
- generator version;
- planner version;
- selected or ambiguous claim references;
- abstention reason.

However, `RequirementPlan` itself is not persisted, and the derived `ContextRequest` does not persist parent-plan/candidate lineage. Durable audit/replay of automatic planning decisions is therefore explicitly deferred.

### G — Maintainability and compatibility

Compatibility is conservative:

- old/custom `CandidateSet` construction defaults `request_fingerprint=""` and `is_exhaustive=False`;
- such values cannot accidentally cross the planner hard-constraint boundary;
- `lexical-v0.2` is a justified version bump because receipt semantics changed even though ranking weights did not;
- the planner's generator pin is intentionally explicit rather than pretending heterogeneous exhaustiveness semantics are interchangeable.

The controlled planner is small and deterministic. The O(N) lexical scan remains a correctness baseline, not a production indexing strategy.

### H — Evidence review

Direct evidence:

- exact-head CI run `35538903034` on implementation head `a2493e56...`;
- Python 3.12, 3.13, and 3.14 all passed;
- Python 3.13 reported **130 passed**;
- end-to-end test proves resolved planning -> new request -> `CoverageContextCompiler` -> COMPLETE projection;
- ambiguity, truncation, incompatible generator, value-only relevance, multi-predicate uncertainty, request mismatch, timezone normalization, forged multi-obligation plan, and rank-vs-ambiguity cases are covered.

Strongly inferred / not benchmarked:

- exact-token planning will have low recall for realistic paraphrases/synonyms;
- O(N) candidate discovery will not scale to large semantic-key cardinality;
- future heterogeneous retrievers need an explicit planner/retriever compatibility contract rather than raw score/exhaustiveness interchange.

## First-pass findings register

### FP10-P2-01 — Generator-relative exhaustiveness was treated as universal

**Area:** semantic safety / compatibility

**Finding:** Initial planner logic accepted any `CandidateSet` with `is_exhaustive=True`. Exhaustiveness is defined relative to the generator's own matching/search universe, so a custom/vector retriever could honestly mark itself exhaustive while omitting keys required by v0.1's lexical uniqueness proof.

**Impact:** Could over-resolve a subject and emit a hard exact requirement from an incompatible candidate universe.

**Disposition:** **ACCEPTED / FIXED.** `controlled-requirement-v0.1` now supports only `lexical-v0.2`; other generator versions abstain with `unsupported-candidate-generator`. A regression covers an exhaustive custom generator.

### FP10-P3-02 — Multiple predicate matches were mislabeled as proven multi-intent

**Area:** semantic interpretation / diagnostics

**Finding:** Initial reason `unsupported-multi-predicate-intent` claimed more than the parser knew. Multiple directly matching predicate keys may indicate genuine multi-intent or lexical predicate ambiguity.

**Impact:** Misleading diagnostic semantics could later drive inappropriate routing behavior.

**Disposition:** **ACCEPTED / FIXED.** Reason is now `predicate-ambiguous-or-multi-intent`; docs explicitly state v0.1 does not distinguish the two.

### FP10-P2-03 — Request fingerprint encoded timezone representation rather than semantic instant

**Area:** provenance / determinism

**Finding:** Initial fingerprint used raw `datetime.isoformat()`, making equal instants with different timezone offsets produce different request fingerprints.

**Impact:** Semantically equivalent temporal requests could be incorrectly rejected as mismatched provenance.

**Disposition:** **ACCEPTED / FIXED.** Temporal selectors normalize to UTC before hashing; regression proves equivalent offsets fingerprint equally.

### FP10-P3-04 — Derived request ID lacked runtime UUID validation

**Area:** public boundary validation

**Finding:** `derive_request()` relied on the type annotation and only checked equality with the source ID.

**Impact:** Invalid identifier types could flow farther than intended before failing in unrelated persistence logic.

**Disposition:** **ACCEPTED / FIXED.** Explicit UUID validation and regression added.

### FP10-P2-05 — Pure planner depended transitively on SQLite

**Area:** architecture / dependency direction

**Finding:** Initial `planning.py` imported lexical tokenization from `candidates.py`, which imports `SQLiteCanonicalStore`.

**Impact:** A storage-neutral planner unnecessarily inherited adapter coupling and risked future circular/deployment constraints.

**Disposition:** **ACCEPTED / FIXED.** Lexical normalization moved to internal storage-neutral `_lexical.py`, shared by retrieval and planning.

### FP10-P2-06 — Derivation trusted a forgeable same-version plan shape too broadly

**Area:** trust boundary / defensive validation

**Finding:** `RequirementPlan` is a public derived dataclass. Its generic invariant permits multiple exact requirements so future planners can evolve, but `derive_request()` initially accepted any `RESOLVED` plan that merely claimed `controlled-requirement-v0.1`.

**Impact:** A manually constructed same-version plan could bypass v0.1's advertised one-obligation contract through the convenience derivation path.

**Disposition:** **ACCEPTED / FIXED.** `derive_request()` revalidates the supported candidate generator and exactly-one-obligation/selected-candidate shape. Regression constructs a forged two-obligation v0.1 plan and verifies rejection.

## Open questions / accepted limitations

1. **Planning freshness.** A plan is resolved against its candidate snapshot, not every later frontier. A new matching subject admitted later can make a fresh re-plan ambiguous even though the old plan remains historically `RESOLVED`. Current coverage compilation validates the selected key, not renewed identity uniqueness.
2. **Durable planning provenance.** Candidate sets and requirement plans are ephemeral. Persisted derived requests/projections do not currently retain parent-plan/candidate receipt lineage.
3. **Authenticity.** Fingerprints bind semantics but do not authenticate the producer. Future cross-process/untrusted planning inputs would need a stronger trusted-receipt/capability design.
4. **Historical memory lifecycle.** Candidate eligibility still uses present materialized memory lifecycle even when epistemic `known_at` is historical, inherited from existing context compilers.
5. **Retriever/planner compatibility.** Future semantic/vector retrievers need a formal compatibility or fusion contract before they can feed hard-constraint planning.
6. **General NLP.** Controlled exact-token parsing cannot support production natural-language coverage planning without predicate ontology, entity resolution, decomposition, and better ambiguity semantics.

## Missing evidence

- corpus-level planner precision/recall and abstention quality;
- multilingual/tokenization benchmarks;
- large-cardinality candidate/planner latency;
- multi-intent and synonym benchmark suites;
- current-frontier replanning/freshness design;
- durable plan-receipt/replay schema;
- heterogeneous retriever compatibility/calibration.

These omissions limit claims about NLP quality, scale, and durable audit. They do not invalidate the narrow correctness boundary proven by this slice.

## Areas reviewed with no issue found

- planning creates no canonical semantic writes;
- candidate/planner execution emits no `SEEN` or `USED`;
- rank preference is not used as semantic certainty;
- exact requirement persistence still occurs only through later projection registration;
- request-ID collision invariant remains intact because planning derives a new ID;
- coverage remains an independent pinned-snapshot operation;
- no provider/model/tool dependency enters the planner;
- no schema migration is introduced;
- unsupported generator semantics fail closed by abstention;
- legacy/custom candidate values fail closed because exhaustiveness/request binding defaults are conservative;
- storage dependency direction is clean after lexical-helper extraction;
- temporal request fingerprinting is deterministic by semantic instant;
- documentation distinguishes candidate exhaustiveness from perfect retrieval recall;
- documentation does not claim a resolved plan is a current-frontier identity fence.

## Frozen first-pass state

```text
FIRST-PASS REVIEW COMPLETE

Corrected findings:
  FP10-P2-01 generator-relative exhaustiveness was treated as universal.
  FP10-P3-02 predicate multiplicity diagnostic overclaimed multi-intent.
  FP10-P2-03 temporal fingerprinting encoded offset representation.
  FP10-P3-04 derived request ID lacked runtime UUID validation.
  FP10-P2-05 pure planner depended transitively on SQLite.
  FP10-P2-06 derive_request trusted a forgeable same-version plan too broadly.

Blocking findings remaining:
  None.

Accepted limitations:
  snapshot-bound planning freshness; ephemeral/non-authenticated planning receipts;
  inherited present-state memory lifecycle; controlled lexical NLP scope; no
  heterogeneous retriever compatibility yet.

Exact reviewed/tested head:
  a2493e56e0450b7403fe4badf099ff016e1b5d20

CI:
  run 35538903034 — Python 3.12/3.13/3.14 green; 130 tests on 3.13.
```

Codex must review PR #10 independently from this frozen baseline. This document must remain off the PR branch/review surface until the second-review cycle is complete.
