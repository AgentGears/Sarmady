# Exhaustive First-Pass Review — Context-Need Fulfillment Decision Boundary

**Review state:** FROZEN BEFORE SECOND REVIEW  
**Reviewed repository:** `AgentGears/Sarmady`  
**Feature branch:** `m2/context-need-fulfillment`  
**Exact reviewed head:** `6c8e5a636360e38f78eed29324f35d8e1c301439`  
**Base / merge base:** `0b1570b62dc52fc509af8fe5a1ad4c5039c7405d`  
**Latest exact-head CI reviewed:** run `35717597284`  
**Validation:** Python 3.12 / 3.13 / 3.14 green; Python 3.13 reports **166 passed**.

This record freezes the maintainer first-pass review before any Codex/independent second-review findings are consulted. Later second-review findings must be recorded separately and must not rewrite this baseline.

## 1. Intended behavioral boundary

The slice introduces the first governed transition from a persisted model-produced `ContextNeedProposal` to an explicit durable host decision while preserving the following inequality:

```text
ContextNeedProposal
    != ContextNeedDecision
    != ContextRequest
    != retrieval / requirement planning
    != ContextProjection
    != permission to continue cognition
```

The intended executable behavior is deliberately narrow:

- a persisted `context-need:v1` artifact may be explicitly **ACCEPTED** or **REJECTED**;
- rejection creates no follow-up request;
- acceptance creates exactly one **fresh** child `ContextRequest`;
- the child carries the proposal query and descriptive coverage labels, inherits parent task/goal/temporal lineage, and carries no model-authored exact semantic addresses;
- child token/latency bounds are non-amplifying relative to the parent request;
- acceptance does not run retrieval, requirement planning, projection compilation, memory mutation, or another model invocation;
- `decision_source` is an audit label only, not authentication, principal identity, permission, or capability.

The implementation explicitly does **not** claim cumulative remaining-budget accounting, principal-bound authorization, general iterative cognition, projection augmentation/replacement, loop control, or continuation freshness.

## 2. Independently reconstructed review surface

The first pass reviewed the change as a control/authority boundary rather than merely as a persistence feature. The review surface included:

### Intent and authority

- model output cannot directly create executable work;
- proposal acceptance is distinguishable from proposal generation;
- acceptance creates request intent only, not retrieval or continuation authority;
- exact semantic addresses cannot be smuggled from the model proposal into the accepted child;
- the audit label is not overstated as authorization.

### Architecture and ownership

- `ContextNeedDecision` domain contract placement and exports;
- `ContextNeedCoordinator` ownership of the host/context transition;
- SQLite store mixin dependency direction and import-cycle risk;
- compatibility with existing model-runtime and context-engine boundaries;
- absence of provider/model-specific machinery in the kernel contract.

### Persistence, lineage, and migrations

- durable chain `GeneratedArtifact -> ModelInvocation -> CognitiveRequest -> ContextProjection -> parent ContextRequest`;
- strict `context-need:v1` kind and payload validation;
- successful-invocation requirement;
- decision temporal causality;
- source-projection freshness for acceptance;
- schema-v7 table constraints and indexes;
- v6->v7 upgrade from a database genuinely missing the new table;
- preservation of the older v5->v6 projection-lineage migration and retry behavior;
- close/reopen rehydration of accepted/rejected decisions and child requests.

### Concurrency, atomicity, retry, and recovery

- final acceptance freshness check under the same SQLite write lock used for persistence;
- child request and decision written in one transaction;
- rollback if decision insertion fails after child insertion;
- one decision per context-need artifact;
- no retroactive adoption of a pre-existing request as the accepted child;
- one decision owner per non-null child request;
- explicit already-decided behavior rather than silent duplicate creation.

### Data and type invariants

- UUID identity fields;
- accepted/rejected child-nullability relation;
- child != parent;
- nonblank audit fields;
- positive integer resource bounds;
- Python `bool <: int` edge cases;
- parent goal/task/temporal inheritance;
- child query/coverage equality with the proposal;
- prohibition on exact requirements at acceptance.

### Security and trust

- arbitrary ordinary generated artifacts cannot be reinterpreted as context needs;
- malformed persisted proposal payloads fail closed;
- failed model invocations cannot become eligible proposal provenance;
- post-construction mutation of frozen values is revalidated at the durable boundary;
- no credential, principal, capability, or external-action authority is introduced.

### Performance and operability

- decision registration is bounded to indexed point lookups/inserts over the lineage chain;
- no global semantic scan or retrieval occurs;
- the semantic frontier is not advanced merely by operational decision persistence;
- audit lineage remains queryable after restart;
- current scope does not introduce background work or an unbounded iteration loop.

### Maintainability and documentation

- public exports and package dependency direction;
- schema-version tests do not pin an obsolete literal;
- docs accurately distinguish non-amplifying child bounds from remaining-budget accounting;
- README, milestones, architecture, ontology, context-iteration, model-runtime, and the dedicated fulfillment contract agree on the slice boundary;
- deliberate limitations are represented as deferred forcing functions rather than hidden claims.

## 3. First-pass findings and dispositions

The following findings were produced during this first pass and fixed before this record was frozen.

### FP1 — Accepted child could alias a pre-existing `ContextRequest` identity

**Severity:** P1 architectural/provenance defect.  
**Status:** CONFIRMED / FIXED / REGRESSION-COVERED.

The first implementation used `INSERT OR IGNORE` for the child request and accepted a semantically equal row already present under that UUID. That could make a new acceptance decision claim lineage to operational intent that predated the decision rather than to a request actually created by the acceptance.

**Correction:** child request identity must be absent; the store now checks for pre-existence and uses a plain insert. The schema also gives non-null child request IDs a unique decision owner. Regression coverage verifies a pre-existing semantically equal request cannot be adopted as the child.

### FP2 — `ContextNeedDecision` identity fields lacked explicit UUID type invariants

**Severity:** P1 persistence/audit integrity defect.  
**Status:** CONFIRMED / FIXED / REGRESSION-COVERED.

Malformed non-UUID identity values could survive construction and become awkward or unreadable durable lineage values.

**Correction:** every decision identity field, including optional child ID when present, is explicitly required to be a `UUID`.

### FP3 — Boolean budget values could bypass the direct durable child boundary

**Severity:** P1 type/invariant defect at the new write boundary.  
**Status:** CONFIRMED / FIXED LOCALLY / REGRESSION-COVERED.

The coordinator rejected booleans, but direct store callers could construct a `ContextRequest` with `True` because Python treats `bool` as a subclass of `int`, and the pre-existing generic `ContextRequest` invariant does not reject that globally.

**Correction:** the context-need decision store independently rejects Boolean token and latency child budgets and requires positive integers.

**Claim ceiling:** the generic pre-existing `ContextRequest` Boolean-budget behavior is not globally fixed by this slice and remains inherited technical debt outside this boundary.

### FP4 — No decision temporal-causality fence

**Severity:** P1 audit/provenance defect.  
**Status:** CONFIRMED / FIXED / REGRESSION-COVERED.

A decision could originally be persisted with `decided_at` earlier than the artifact creation/invocation completion it purported to decide.

**Correction:** the durable store requires decision time to be at or after both artifact creation and successful invocation completion.

### FP5 — Schema constraints were weaker than the domain decision contract

**Severity:** P2 defense-in-depth/persistence integrity.  
**Status:** CONFIRMED / FIXED / REGRESSION-COVERED.

The initial table shape did not fully enforce blank audit fields, child-vs-parent distinction, or single ownership of a child request at the schema layer.

**Correction:** schema v7 adds nonblank checks for `reason` / `decision_source`, child != parent, accepted/rejected nullability consistency, unique proposal decision ownership, and a partial unique index over non-null child request IDs.

### FP6 — Upgrade tests hardcoded schema version 6

**Severity:** P1 regression/compatibility failure.  
**Status:** CONFIRMED / FIXED.

The first CI run after introducing schema v7 had two failures solely because older review tests asserted `PRAGMA user_version == 6`.

**Correction:** tests compare against `schema_module.SCHEMA_VERSION`, preserving the semantic migration checks without freezing an obsolete numeric version. Subsequent CI is green.

### FP7 — “bounded budget transfer” wording overclaimed actual accounting semantics

**Severity:** P1 architectural-claim defect.  
**Status:** CONFIRMED / FIXED IN CODE/DOCS.

The implementation proves only a per-child non-amplification rule (`child <= parent`). There is no authoritative consumption ledger, so it cannot derive a true remaining budget after earlier context/model work.

**Correction:** wording now consistently states **non-amplifying per-child resource bounds** and explicitly preserves:

```text
non-amplifying child bound != remaining-budget accounting
```

Cumulative accounting remains deferred.

### FP8 — Original test description implied non-context artifact coverage that did not exist

**Severity:** P2 test completeness.  
**Status:** CONFIRMED / FIXED / EXPANDED.

The original test name referred to both unknown and non-context artifacts but exercised only the unknown-artifact case.

**Correction:** adversarial coverage now exercises a real ordinary terminal artifact, malformed persisted context-need payload, failed/tampered invocation provenance, exact-requirement smuggling, task/temporal lineage substitution, and blank audit values.

### FP9 — Initial migration coverage did not prove a real v6 database could create the v7 table

**Severity:** P1 migration-test gap.  
**Status:** CONFIRMED / FIXED / REGRESSION-COVERED.

A legacy test changed only `user_version` on a database already containing the current schema. That did not prove upgrade from a real v6 physical shape without `context_need_decisions`.

**Correction:** a dedicated test seeds a durable proposal, drops the v7 decision table, sets `user_version=6`, reopens through current initialization, verifies table/version creation, and successfully decides the pre-v7 proposal.

## 4. Exact-head negative/adversarial evidence

At the frozen head, tests establish that:

- an ordinary generated answer cannot cross the decision boundary as a context need;
- a malformed persisted context-need payload fails closed;
- a failed invocation cannot supply an eligible proposal;
- a direct store caller cannot smuggle exact semantic requirements into the child;
- task/goal and temporal lineage cannot be substituted;
- Boolean resource values are rejected at the durable boundary;
- a stale source projection blocks acceptance inside the decision transaction;
- rejection remains recordable for a stale historical source and creates no work;
- a child request cannot reuse an existing request identity;
- child insertion is rolled back if subsequent decision persistence fails;
- a proposal receives at most one decision;
- accepted decisions and child requests rehydrate after restart;
- the v6->v7 physical upgrade path works for an already-persisted proposal;
- registering a decision does not advance the semantic frontier;
- acceptance creates no additional projection, cognitive request, or model invocation.

## 5. Residual risks and explicit deferred work

The following are **not blocking findings for this slice** because the implementation/docs do not claim to solve them, but they remain explicit forcing functions or maintenance debt.

### Deferred control boundaries

- No `Principal` / `PermissionGrant` policy authorizes who may call accept/reject. `decision_source` is an audit label only.
- No cumulative resource-consumption ledger or true remaining-budget calculation exists.
- No automatic retrieval, requirement planning, or projection compilation follows acceptance.
- No projection augmentation/replacement semantics exist.
- No multi-step loop budget, step cap, repeated-need detection, or cycle prevention exists.
- No current-frontier revalidation immediately before a later continuation exists.
- No cancellation/revocation semantics for an already accepted child request exist.
- No provider-specific streaming/tool-call representation is introduced.

### Maintainability debt

- `ContextNeedStoreMixin` currently duplicates the `ContextRequest` SQL/JSON persistence encoding also present in `ProjectionStoreMixin`. The formats are kept equivalent and exact round-trip checks/tests cover the new path, but a future generic `register_context_request()` boundary should remove this duplication.
- `ContextNeedCoordinator` currently accepts the store as `Any`; a future store protocol could make the dependency contract more explicit.
- `ContextNeedDecision` is exported from `sarmady.cognition` while the transition is host/context control. Existing cognition already owns durable decision-like records, so this is not currently inconsistent, but ownership should be revisited if executive/context-control contracts expand.
- Generic `ContextRequest` still has pre-existing Boolean-budget permissiveness; this slice fences only its own new durable child boundary.

## 6. Performance / concurrency conclusion

The new decision path performs a fixed chain of indexed primary/foreign-key point reads and bounded inserts. It introduces no semantic-key enumeration, vector search, global rebuild, polling, or iterative model loop. SQLite `BEGIN IMMEDIATE` serializes the final decision transition, and the source-projection stale fence is checked after obtaining that write lock. The accepted child and decision are committed atomically.

This review does not claim distributed/multi-writer correctness outside the existing SQLite single-store transaction model.

## 7. Documentation/claim audit

The executable behavior and documentation now agree on these claim ceilings:

```text
model proposal != host decision
host decision != retrieval
accepted child request != projection
child <= parent != remaining budget
source audit label != authenticated principal
accepted need != external-action permission
```

No reviewed document claims general iterative reasoning from this slice.

## 8. First-pass disposition

All first-pass blocking defects identified above were corrected before this freeze and have direct regression coverage where applicable. The exact reviewed head `6c8e5a636360e38f78eed29324f35d8e1c301439` is green on the CI Python matrix, with **166 tests passing on Python 3.13**.

**First-pass result:** no known blocking correctness, provenance, authority, migration, atomicity, trust, recovery, or operability issue remains on the frozen head. Proceed to an independent second review without seeding it with the findings above.
