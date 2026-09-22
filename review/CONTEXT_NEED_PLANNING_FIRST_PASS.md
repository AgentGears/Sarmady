# Exhaustive First-Pass Review — Accepted Context-Need Planning Receipts

## Freeze record

- Repository: `AgentGears/Sarmady`
- Base: `main` at `915a7ed96514207a16ead8b07386145f4bc3d5de`
- Candidate branch: `m2/context-need-planning-receipts`
- **Exact candidate head reviewed and frozen:** `07ec6327d1ad75012ca477ad40ff7c469e467be4`
- CI run: `35792467900`
- CI matrix: Python 3.12 / 3.13 / 3.14 — all green
- Test suite: 181 tests on the final candidate line
- Review status: **first pass complete; no unresolved merge-blocking findings**

This report is intentionally frozen on a separate review branch. It must not be used to seed an independent second review before that review has produced its own findings.

## Forcing function reviewed

The slice is constrained to one new control boundary after an already persisted `ACCEPTED` `ContextNeedDecision`:

```text
accepted ContextNeedDecision
    -> accepted child ContextRequest
    -> snapshot-bound lexical candidate discovery
    -> controlled requirement planning
    -> durable ContextNeedPlanningReceipt
       -> RESOLVED  -> fresh exact ContextRequest
       -> AMBIGUOUS -> no exact request
       -> ABSTAINED -> no exact request
```

The slice deliberately stops before automatic projection compilation or model continuation.

## Review surfaces

The first pass independently reconstructed and inspected the complete `main...m2/context-need-planning-receipts` change surface, including:

- domain/control contracts:
  - `src/sarmady/context/planning_receipt.py`
  - `src/sarmady/context/fulfillment_planning.py`
  - `src/sarmady/context/__init__.py`
- durable persistence and freshness:
  - `src/sarmady/storage/sqlite/context_need_planning_store.py`
  - `src/sarmady/storage/sqlite/context_need_planning_fence.py`
  - `src/sarmady/storage/sqlite/context_need_store.py`
  - `src/sarmady/storage/sqlite/store.py`
  - `src/sarmady/storage/sqlite/schema.py`
- existing contracts relied upon by the slice:
  - `src/sarmady/context/candidates.py`
  - `src/sarmady/context/planning.py`
  - `src/sarmady/context/coverage.py`
  - `src/sarmady/storage/sqlite/projection_store.py`
  - `src/sarmady/storage/sqlite/cognitive_store.py`
  - semantic dependency and temporal-resolution paths used by candidate validation
- tests:
  - `tests/test_context_need_planning_receipts.py`
  - `tests/test_context_need_planning_projection_fence.py`
  - `tests/test_context_need_planning_schema_upgrade.py`
  - `tests/test_context_need_planning_store_invariants.py`
  - modified fulfillment compatibility/recovery tests
- documentation/claims:
  - `README.md`
  - `docs/architecture.md`
  - `docs/ontology.md`
  - `docs/milestones.md`
  - `docs/context-need-planning.md`
  - `docs/context-fulfillment.md`
  - `docs/context-iteration.md`
  - `docs/requirement-planning.md`
  - model-runtime and coverage contracts where they define downstream authority/freshness behavior.

## Findings discovered and corrected before freeze

### FP-01 — schema-version compatibility regression — high — fixed

**Problem:** advancing SQLite to schema v8 initially left an older fulfillment recovery test asserting `PRAGMA user_version == 7`, causing the suite to fail even though the upgrade itself was intentional.

**Correction:** compatibility assertions now bind to `SCHEMA_VERSION`; a dedicated physical v7→v8 upgrade test verifies the planning table is created while existing v7 context-need decisions remain readable and usable.

**Verification:** final CI is green across Python 3.12, 3.13, and 3.14.

### FP-02 — planning freshness initially stopped at receipt persistence — high — fixed

**Problem:** a plan could be current when persisted and used to create a projection, then become semantically obsolete because later state changed lexical uniqueness/ambiguity while the exact projected key itself remained unchanged. The ordinary exact-key projection dependency set would not necessarily express that upstream planning invalidation.

**Correction:** planning provenance now participates in the store's full projection-freshness contract. A projection derived from a planning receipt dynamically becomes stale when the receipt's candidate frontier is invalidated, with reason `context-need-planning-receipt-stale`.

**Verification:** tests cover a projection that is fresh at registration and becomes stale after a later semantic change, followed by cognition refusal.

### FP-03 — downstream acceptance could bypass transitive planning staleness — high — fixed

**Problem:** context-need acceptance originally inspected only the raw `context_projections.stale` materialized column. A planning-derived projection could therefore be dynamically stale through its expired planning proof while the row still contained `stale = 0`, allowing a new accepted need to be authorized from obsolete context.

**Correction:** acceptance now calls `projection_is_stale()` under the decision write lock, using the store's complete freshness contract rather than the raw column.

**Verification:** a regression test emits a second context need while the projection is current, invalidates the upstream planning proof, then confirms acceptance fails and no decision is persisted.

### FP-04 — candidate-generation → persistence race lacked a negative-space fence — high — fixed

**Problem:** lexical v0.2 uniqueness/ambiguity depends on the full visible semantic-key universe, including candidates that were absent. A semantic or non-telemetry memory-state change after candidate generation but before durable receipt persistence could invalidate the plan without changing the selected exact key.

**Correction:** receipt persistence fails closed under the SQLite write lock when any claim/relation or relevant memory-state dependency changed after the candidate frontier. Projection registration repeats the planning-freshness check under its own write transaction.

**Verification:** tests mutate the semantic universe between candidate generation and receipt persistence and between planning and projection registration; both paths fail atomically.

### FP-05 — planning attempt/retry identity and candidate-limit provenance were incomplete — high/medium — fixed

**Problem:** a response-lost retry at the same semantic frontier could silently persist a second planning receipt and fresh exact request. In addition, the lexical candidate `limit` materially affects exhaustiveness but was not retained in the durable receipt.

**Correction:** `candidate_limit` is validated and persisted. A planning attempt is uniquely identified by accepted decision, candidate frontier, candidate limit, generator version, and planner version. Repeating the same attempt fails explicitly; a caller may reload the durable receipt. Replanning remains possible after the frontier changes or when the host deliberately changes the candidate limit.

**Verification:** tests cover duplicate same-configuration rejection without partial writes and distinct same-frontier planning with a deliberately different candidate limit.

### FP-06 — persistence accepted broader plan shapes than the claimed planner version — medium — fixed

**Problem:** `RequirementPlan` is a generic future-facing domain value. The planning store initially accepted shapes that satisfy generic dataclass invariants but could not have been emitted by `controlled-requirement-v0.1`, weakening the meaning of persisted `planner_version` provenance.

**Correction:** the durable boundary now validates the v0.1 output grammar: one exact obligation/selected claim for `RESOLVED`; the exact ambiguity reason and at least two ambiguity candidates for `AMBIGUOUS`; and only supported one-reason abstentions for `ABSTAINED`. Candidate frontier spelling is also canonicalized/fenced.

**Verification:** adversarial tests reject impossible multi-obligation v0.1 receipts and noncanonical frontier labels.

### FP-07 — documentation made stale claims after the new boundary existed — medium — fixed

**Problem:** earlier requirement-planning and fulfillment documentation still described plans as exclusively ephemeral, stated that durable planning receipts/current-frontier planning fences did not exist, or referred to schema v7 as though it were still the current overall schema.

**Correction:** documentation now distinguishes the pure planner from the optional durable accepted-need orchestration boundary, explains schema v8, candidate-limit provenance, retry identity, negative-space freshness, and transitive projection staleness, while preserving the statement that acceptance itself does not automatically retrieve/plan/compile/continue.

## Invariants verified

### Provenance and lineage

- Planning starts from a persisted `ACCEPTED` context-need decision, never from free-floating model text.
- The plan source request must be exactly the accepted decision's child request.
- The source request fingerprint is revalidated at durable write time.
- Receipt planning time cannot predate the accepted decision.
- Resolved derived request identity must be fresh and distinct from the source request.
- Candidate snapshot ID must exactly match the canonical candidate frontier.
- Generator and planner versions are explicit and version-specific semantics are enforced.

### Authority separation

- `ContextNeedProposal` does not become retrieval authority.
- `ContextNeedDecision(ACCEPTED)` authorizes only creation of the bounded child request.
- Explicit planning may perform candidate discovery/planning but does not compile a projection or invoke a model.
- `RESOLVED` creates a new exact request; it does not claim coverage.
- `AMBIGUOUS` and `ABSTAINED` persist uncertainty without creating exact requests.
- Receipt persistence does not mutate epistemic truth or advance the semantic frontier.
- Candidate exposure/selection does not strengthen or restore memory.

### Snapshot and freshness discipline

- Candidate discovery remains transactionally snapshot-bound.
- Planning receipt records the exact candidate snapshot/frontier and candidate limit.
- Receipt persistence rejects post-frontier semantic/relevant memory changes.
- Planning freshness is rechecked at projection registration.
- Later planning invalidation propagates dynamically to persisted projection freshness.
- Cognitive-request admission and invocation start inherit that dynamic freshness through the existing `projection_is_stale()` boundary.
- Downstream context-need acceptance also uses the full freshness contract.
- `SEEN` / `USED` memory telemetry does not invalidate planning because it does not alter active-memory eligibility.

### Atomicity, replay, and failure semantics

- A resolved derived request and its planning receipt commit in one transaction.
- Failed receipt registration leaves no orphan exact request.
- Duplicate same-frontier/same-configuration attempts are explicit failures, not silent duplicate fulfillment.
- Receipts and derived requests rehydrate after close/reopen.
- v7 stores upgrade to v8 in place and retain existing decisions.
- Planning records do not advance the semantic frontier.

### Compatibility

- Existing context-need decision semantics remain intact.
- Existing terminal and step model-runtime APIs are unchanged by the planning coordinator.
- The planning slice introduces no provider SDK or model-specific contract.
- The existing pure `ControlledRequirementPlanner` remains usable independently; durable/freshness semantics are an orchestration layer around it rather than a semantic redefinition of every standalone plan.

## Validation evidence

Final exact candidate `07ec6327d1ad75012ca477ad40ff7c469e467be4` was validated by GitHub Actions run `35792467900`:

- Python 3.12: success
- Python 3.13: success
- Python 3.14: success
- install: success
- `compileall`: success
- `pytest`: success
- suite size on the candidate line: 181 tests

The review also explicitly exercised/inspected race windows, transaction boundaries, stale-state propagation, restart recovery, migration behavior, model-output authority boundaries, and documentation claims rather than treating green tests as sufficient evidence by themselves.

## Residual risks and deliberate non-goals

These are not represented as implemented guarantees:

1. **Principal-bound authorization is absent.** The coordinator/store boundary is trusted host code. `decision_source`, generator version, planner version, request fingerprints, and planning receipts are audit/integrity/provenance data, not authentication, signatures, capabilities, or `PermissionGrant`s.
2. **The store does not cryptographically prove or fully replay arbitrary external planner execution.** It validates persisted lineage, supported versions, concrete v0.1 plan grammar, candidate claim/frontier semantics, candidate-limit configuration, and freshness. The boundary assumes only trusted host code may submit the operational receipt. This claim ceiling is documented.
3. **Freshness is intentionally conservative.** Any post-frontier claim/relation or non-telemetry memory-state change expires a planning proof, even when a more selective future dependency model might prove the change irrelevant to the natural-language planning result.
4. **No cumulative resource ledger exists.** Per-request bounds remain non-amplifying caps, not remaining-budget accounting across a multi-step reasoning loop.
5. **No automatic projection or model continuation exists.** The resolved exact request is durable intent for a later explicit operation.
6. **No projection augmentation/replacement, loop/cycle control, repeated-need detection, or cancellation/revocation is introduced here.**
7. **The planner remains deliberately narrow.** No embeddings, learned entity resolution, synonym ontology, or general multi-intent decomposition is claimed.

## First-pass conclusion

The exact candidate head satisfies the scoped forcing function and preserves the project's principal distinctions:

```text
ContextNeedProposal
    != ContextNeedDecision
    != accepted child ContextRequest
    != ContextNeedPlanningReceipt
    != derived exact ContextRequest
    != ContextProjection
    != permission to continue cognition
```

No unresolved first-pass merge blocker remains at the frozen candidate SHA. The next mandatory step is an independent second review of the PR without supplying this report's findings to that reviewer first.
