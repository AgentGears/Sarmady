# Architecture v0.1

Sarmady is organized around a semantic kernel and replaceable cognitive machinery.

```text
INPUT / WORLD
     |
   Event
     |
  Evidence
     |
claim proposals
     |
semantic admission
     v
   Claims <---- ClaimRelations
     |
     +----> ResolvedState (derived)
     +----> MemoryEntry ----> MemoryLifecycleEvent
     |
ContextRequest
     |
Context Engine
 candidate discovery · requirement planning · resolve exact obligations · coverage control
     v
ContextProjection (immutable snapshot)
     |
CognitiveRequest ----> ReasoningPolicy (immutable semantic contract)
     |
+----+----------+-----------+
|               |           |
Reasoner      Choice      Generator
|               |           |
+----+----------+-----------+
     v
GeneratedArtifact / ChoiceResult
     |
     +---- context-need:v1 ----> ContextNeedDecision
     |                              |
     |                              +-- REJECTED
     |                              |
     |                              +-- ACCEPTED --> fresh child ContextRequest
     |
Executive / governed adoption
     v
DecisionRecord / ActionIntent
     |
permission + action-bound approval + pre-dispatch fence
     v
ExecutionAttempt
     |
    WORLD
     |
EffectEvidence
     +-----------------------> Event
```

The accepted context-need branch stops at the child request in the current slice. It does not automatically loop back through retrieval, projection compilation, or cognition.

## Logical planes

The **semantic kernel** owns durable identity, epistemic admission boundaries, authority, commitments, action/effect semantics, and presentation truth. The **memory system** controls admission into long-term recall, lifecycle, consolidation, and usage telemetry. The **context system** discovers candidate semantic keys, plans explicit information obligations, compiles a bounded working set from canonical and materialized state, and now owns the first request-creation service for an explicitly accepted context need. Candidate discovery is derived relevance computation, not semantic admission and not proof of sufficiency. Requirement planning is a second derived boundary: it may resolve, preserve ambiguity, or abstain, and rank preference alone cannot create a hard semantic constraint. Coverage remains the independent sufficiency contract: a resolved requirement still must be re-resolved and supported inside the compiler's pinned snapshot. The **cognitive runtime** invokes reasoning, decision, generation, and verification models. A cognitive model may emit a typed `ContextNeedProposal`, but that proposal remains non-authoritative generated output. A separate host/context boundary may persist an `ACCEPTED` or `REJECTED` `ContextNeedDecision`; acceptance may create one fresh bounded child `ContextRequest`, but it still does not grant retrieval or continuation authority. The **executive** selects what computation or work happens next. The **runtime adapters** connect models, tools, providers, and user surfaces.

These are logical responsibilities, not mandatory microservices. A deployment may combine them in one process while preserving their contracts.

## Canonical versus materialized state

Canonical history is append-oriented. Materializations may be destroyed and rebuilt.

In M1:

- `claim_heads` is rebuilt from canonical claim/relation history;
- `memory_entries.lifecycle` is rebuilt from canonical memory lifecycle events;
- projection staleness/dependency indexes are disposable derived state.

Candidate sets and requirement plans are also derived state. The current lexical generator returns immutable ephemeral snapshot-bound candidate values, and the controlled planner returns immutable ephemeral plan values. Neither is canonical truth and neither is persisted by the kernel in M2 v0.1.

A materialization must never become the only surviving source of a semantic fact.

## Context planning discipline

The context path preserves three different claims:

```text
candidate relevance != planned obligation != coverage sufficiency
```

A `CandidateSet` can be used for hard-constraint planning only when it is bound to the exact source request semantics and the generator reports that no additional match under its own rule was truncated. This does not turn generator exhaustiveness into perfect recall; it only prevents a top-k result from masquerading as a unique semantic answer.

`RequirementPlan` makes uncertainty explicit. Non-resolved plans are structurally unable to carry exact requirements. A resolved plan may derive a new `ContextRequest` with exact obligations, but it cannot mutate or reuse the source request ID. The derived request is then compiled normally, so the coverage engine—not the planner—determines whether support is complete, partial, or insufficient.

A `ContextNeedProposal` sits on the other side of the projection boundary: it is a model-produced request for additional information, not a `ContextRequest`. Persisting it as generated output preserves the need across failure without allowing model output to allocate budget, select exact addresses, or initiate retrieval by assertion.

The fulfillment-decision boundary adds another explicit inequality:

```text
ContextNeedProposal != ContextNeedDecision != child ContextRequest != continuation
```

The decision store re-establishes artifact → invocation → cognitive request → projection → parent-request lineage before recording a decision. Acceptance is fenced against a stale source projection under the same write lock used for persistence. It creates a new child request with proposal query/labels, inherited task/temporal selectors, no model-authored exact requirements, and per-child token/latency bounds no greater than the parent. These are non-amplifying child caps, not cumulative remaining-budget accounting.

## Snapshot discipline

A context compiler must not read a frontier and then accidentally mix in later state. SQLite M1 uses an explicit WAL read transaction: the first frontier read pins the database snapshot, all claim/evidence/memory reads occur inside that snapshot, and only then is the immutable projection emitted.

Candidate discovery follows the same discipline. Semantic-key enumeration, temporal resolution, claim reads, and memory gating happen inside one `context_read_snapshot()`. Because enumerating the entire visible key space depends on absence as well as presence, the capture records the conservative `semantic:*` dependency; a later semantic write may introduce a new candidate that did not exist at the captured frontier.

Requirement planning in its current form performs no additional canonical reads. Its plan records the candidate snapshot/frontier and source-request fingerprint as provenance. The derived request does not assume that candidate state is still current: `CoverageContextCompiler` opens its own pinned read snapshot and independently resolves the exact semantic obligation. A resolved plan is therefore not a freshness authorization.

Projection registration occurs after the read transaction. The registration boundary binds the durable `snapshot_id` to the canonical SQLite frontier and, for captured lineage, verifies that projected items were successfully read inside that pinned snapshot. If the semantic frontier advances in the handoff window, proven dependency lineage distinguishes relevant changes from unrelated ones: a changed recorded dependency stales the projection, while an unrelated semantic write does not. A projection without proven lineage may register only at the current frontier and receives the conservative `semantic:*` dependency so any later semantic mutation invalidates it.

## Dependency discipline

Domain contracts must not import storage/services. Domain packages export semantic types; write/read services may depend on storage adapters. This prevents circular dependencies and keeps the ontology independent of SQLite.

## Model independence

The kernel must not know about system prompts, temperatures, tokenizers, OpenAI message arrays, or specific model names. A persisted `Agent` is independent of every model binding. A `ReasoningPolicy` is likewise provider-neutral: it expresses versioned stages and reasoning obligations rather than a provider prompt. The cognitive runtime reloads a durable `ContextProjection`, materializes a structured semantic `ModelInput` containing any selected policy and its fingerprint, and gives only that input to a provider-neutral `ModelAdapter`. The adapter has no canonical-store handle. Each attempt is durably recorded as a `ModelInvocation`; returned `GeneratedArtifact` objects are durable but remain non-authoritative until a governed adoption step.

The opt-in step interface extends that boundary without handing the adapter a store handle. `StepModelAdapter` may return either a terminal `ModelResponse` or a typed `ContextNeedProposal`. A valid proposal is serialized into a versioned `GeneratedArtifact`; no follow-up `ContextRequest`, retrieval, memory mutation, or second invocation is created automatically by the cognitive runtime.

A later `ContextNeedCoordinator` call is a separate host operation. Its `decision_source` is only an audit label; this slice does not claim principal-bound authentication or permission. An accepted decision creates a request record but does not call the model adapter or any retriever.

Freshness is fenced twice: when the cognitive request is admitted and again under the write lock immediately before invocation start. A later state change may make the historical projection stale while a model call is already running; that does not rewrite the invocation snapshot. The context-need acceptance boundary separately refuses an already-stale source projection, and any future model continuation must add its own current-frontier fence.

## Storage independence

The ontology is not the database schema. SQLite is the first implementation. Schema v7 uses WAL + `synchronous=FULL`, explicit write transactions, versioned schema metadata, canonical semantic sequencing, and a durable `context_need_decisions` control record. Those mechanisms may be replaced as long as the same invariants remain true.
