# Exhaustive First-Pass Review R2 — Accepted Context-Need Planning Receipts

## Freeze record

- Repository: `AgentGears/Sarmady`
- Base: `main` at `915a7ed96514207a16ead8b07386145f4bc3d5de`
- Candidate branch: `m2/context-need-planning-receipts`
- **Exact candidate head:** `45a22ffe41de73c16f5d856fc6b039dc35c882ac`
- CI run: `35793233208`
- Python 3.12 / 3.13 / 3.14: success
- Pytest: **182 passed**
- Status: **first pass complete; zero unresolved merge blockers**

The earlier freeze for `07ec6327...` is superseded because a later independent review found a retry-identity defect and the implementation head changed. This R2 report is the authoritative first-pass freeze for the revised candidate. It is intentionally stored off the implementation branch.

## Scoped forcing function

```text
ACCEPTED ContextNeedDecision
  -> accepted child ContextRequest
  -> snapshot-bound lexical candidate discovery
  -> controlled requirement planning
  -> durable ContextNeedPlanningReceipt
       RESOLVED  -> one fresh exact ContextRequest
       AMBIGUOUS -> no exact request
       ABSTAINED -> no exact request
```

No automatic projection compilation or model continuation is introduced.

## Exhaustive review surface

The review reconstructed the full `main...m2/context-need-planning-receipts` diff and traced the contracts it composes with: candidate generation, controlled planning, request fingerprints, SQLite write/read snapshot behavior, projection registration/dependencies, cognitive-request and invocation freshness gates, context-need acceptance, memory lifecycle semantics, schema migration, restart rehydration, and all changed documentation/tests.

Primary implementation files reviewed:

- `src/sarmady/context/planning_receipt.py`
- `src/sarmady/context/fulfillment_planning.py`
- `src/sarmady/context/__init__.py`
- `src/sarmady/storage/sqlite/context_need_planning_store.py`
- `src/sarmady/storage/sqlite/context_need_planning_fence.py`
- `src/sarmady/storage/sqlite/context_need_store.py`
- `src/sarmady/storage/sqlite/schema.py`
- `src/sarmady/storage/sqlite/store.py`

Composed existing boundaries reviewed:

- `src/sarmady/context/candidates.py`
- `src/sarmady/context/planning.py`
- `src/sarmady/context/coverage.py`
- `src/sarmady/storage/sqlite/projection_store.py`
- `src/sarmady/storage/sqlite/cognitive_store.py`
- epistemic resolution and memory lifecycle logging/invalidation paths.

All new/modified planning, upgrade, adversarial, retry, projection-fence, and fulfillment compatibility tests were reviewed together with README/architecture/ontology/milestone/requirement-planning/context-fulfillment/context-need-planning documentation.

## Findings corrected before this freeze

### FP-01 — schema-version compatibility regression — high — fixed

The v8 schema advance initially left a fulfillment recovery assertion hard-coded to v7. Compatibility checks now use `SCHEMA_VERSION`, and a physical v7→v8 upgrade test proves existing decisions survive and become plannable.

### FP-02 — upstream planning freshness did not initially propagate to persisted projections — high — fixed

A projection could remain apparently fresh after later state invalidated the lexical uniqueness/ambiguity proof that created its exact request. Planning-derived projections now dynamically inherit planning-receipt staleness and report `context-need-planning-receipt-stale`.

### FP-03 — downstream context-need acceptance could bypass dynamic planning staleness — high — fixed

Acceptance previously inspected only the raw projection stale column. It now calls the store's full `projection_is_stale()` contract under the decision write lock, so an expired upstream planning proof cannot authorize another accepted need.

### FP-04 — candidate-generation → durable-write negative-space race — high — fixed

`lexical-v0.2` uniqueness depends on the full visible key universe. Receipt persistence now fails closed under the write lock when a claim/relation or non-telemetry memory-state change occurred after the candidate frontier. Projection registration repeats the planning freshness fence.

### FP-05 — incomplete candidate-limit provenance and exact retry identity — high/medium — fixed

The candidate limit now survives in the receipt because it can change exhaustiveness and planner outcome. Exact duplicate decision/frontier/limit/generator/planner attempts are schema- and store-fenced.

### FP-06 — persisted v0.1 plan shapes were broader than the claimed planner contract — medium — fixed

The store now validates canonical frontier spelling and the concrete `controlled-requirement-v0.1` status grammar rather than accepting every generic `RequirementPlan` shape.

### FP-07 — documentation drift — medium — fixed

Documentation now distinguishes the pure planner from the durable accepted-need orchestration layer; describes schema v8, planning freshness, candidate-limit provenance, atomic exact-request derivation, and transitive projection staleness; and continues to state that acceptance/planning do not automatically compile or continue cognition.

### FP-08 — telemetry-only frontier movement could defeat retry ownership — high/medium — fixed in revised candidate

**Problem:** the semantic log frontier advances for `SEEN` / `USED` memory telemetry, while the planning freshness model intentionally excludes those events because they cannot change candidate eligibility. Retry ownership was keyed to the raw candidate frontier. A response-lost retry after harmless telemetry could therefore appear to be a new planning attempt and silently create a second exact request even though the planning universe was still current and unchanged.

**Correction:** for the same accepted decision, candidate limit, generator version, and planner version, any existing **non-stale** receipt now owns that configuration even if the raw frontier advanced only through freshness-irrelevant telemetry. A repeat call fails explicitly. Replanning with the same configuration becomes eligible only after a relevant semantic/memory-state change makes the prior receipt stale. A deliberately different candidate limit remains a distinct host configuration.

**Verification:** a dedicated regression test records a `SEEN` event, proves the raw frontier advanced while the first receipt stayed non-stale, retries planning, and verifies that no second receipt or exact request is persisted.

## Invariants verified on revised head

### Lineage and integrity

- only persisted `ACCEPTED` decisions are plannable;
- source request must be exactly the accepted child;
- source-request fingerprint is revalidated at the durable boundary;
- receipt time cannot predate acceptance;
- generator/planner versions and candidate snapshot/frontier are explicit;
- candidate limit is positive, non-Boolean, persisted, and included in planning configuration;
- resolved derived request uses a fresh ID and preserves source query/budgets/goal/task/labels/temporal selectors;
- non-resolved results cannot carry a derived request.

### Authority separation

- model output cannot directly author exact semantic obligations through this path;
- planning may retrieve/plan only after an explicit accepted decision;
- `RESOLVED` creates request intent, not proof of coverage;
- `AMBIGUOUS` / `ABSTAINED` persist uncertainty without executable exact work;
- no projection, cognitive request, model invocation, action authority, or memory strengthening is automatically created by planning;
- planning receipts do not advance the epistemic semantic frontier.

### Freshness/races

- candidate discovery remains pinned to one SQLite snapshot;
- receipt persistence fences candidate-frontier changes under the write lock;
- the intentionally irrelevant `SEEN` / `USED` events neither stale a receipt nor create a new same-configuration retry owner;
- projection registration fences stale planning proofs;
- later planning invalidation propagates through projection freshness into cognitive admission, invocation-start checks, and later context-need acceptance.

### Atomicity/recovery/compatibility

- resolved exact request + receipt commit atomically;
- failed or duplicate planning leaves no orphan request;
- same current planning configuration is retry-owned by the existing receipt;
- relevant-state change permits legitimate replanning; deliberate limit change is a different configuration;
- receipts/derived requests rehydrate after restart;
- v7→v8 upgrade preserves existing context-need decisions;
- legacy context-need decision semantics remain intact.

## Residual claim ceilings / deliberate non-goals

No implementation claim is made for principal-bound authorization, cryptographic proof of planner execution, arbitrary untrusted receipt submission, cumulative remaining-budget accounting, automatic projection/model continuation, projection augmentation/replacement, loop/cycle/repeated-need control, semantic/vector retrieval, learned entity resolution, or general multi-intent planning.

The store validates supported versions, lineage, concrete v0.1 structural semantics, candidate references/frontier, configuration, and freshness, but does not claim to cryptographically attest that arbitrary external code executed the trusted planner. The boundary assumes trusted host code owns coordinator/store access. Freshness is intentionally conservative: any post-frontier claim/relation or non-telemetry memory-state change expires the proof even where a future finer dependency model might establish irrelevance.

## Final first-pass conclusion

Exact candidate `45a22ffe41de73c16f5d856fc6b039dc35c882ac` satisfies the scoped forcing function with no unresolved first-pass merge blocker. The next mandatory gate is a new independent second review of this revised head; findings from this report must not be supplied to that reviewer before its own review is complete.
