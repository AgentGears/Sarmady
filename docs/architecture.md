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

## Logical planes

The **semantic kernel** owns durable identity, epistemic admission boundaries, authority, commitments, action/effect semantics, and presentation truth. The **memory system** controls admission into long-term recall, lifecycle, consolidation, and usage telemetry. The **context system** compiles a bounded working set from canonical and materialized state. The **cognitive runtime** invokes reasoning, decision, generation, and verification models. The **executive** selects what computation or work happens next. The **runtime adapters** connect models, tools, providers, and user surfaces.

These are logical responsibilities, not mandatory microservices. A deployment may combine them in one process while preserving their contracts.

## Canonical versus materialized state

Canonical history is append-oriented. Materializations may be destroyed and rebuilt.

In M1:

- `claim_heads` is rebuilt from canonical claim/relation history;
- `memory_entries.lifecycle` is rebuilt from canonical memory lifecycle events;
- projection staleness/dependency indexes are disposable derived state.

A materialization must never become the only surviving source of a semantic fact.

## Snapshot discipline

A context compiler must not read a frontier and then accidentally mix in later state. SQLite M1 uses an explicit WAL read transaction: the first frontier read pins the database snapshot, all claim/evidence/memory reads occur inside that snapshot, and only then is the immutable projection emitted.

Projection dependency registration occurs after the read transaction. If the semantic frontier changed in that handoff window, registration conservatively marks the projection stale rather than pretending the snapshot is current.

## Dependency discipline

Domain contracts must not import storage/services. Domain packages export semantic types; write/read services may depend on storage adapters. This prevents circular dependencies and keeps the ontology independent of SQLite.

## Model independence

The kernel must not know about system prompts, temperatures, tokenizers, OpenAI message arrays, or specific model names. A persisted `Agent` is independent of every model binding. A `ReasoningPolicy` is likewise provider-neutral: it expresses versioned stages and reasoning obligations rather than a provider prompt. The cognitive runtime reloads a durable `ContextProjection`, materializes a structured semantic `ModelInput` containing any selected policy and its fingerprint, and gives only that input to a provider-neutral `ModelAdapter`. The adapter has no canonical-store handle. Each attempt is durably recorded as a `ModelInvocation`; returned `GeneratedArtifact` objects are durable but remain non-authoritative until a governed adoption step.

Freshness is fenced twice: when the cognitive request is admitted and again under the write lock immediately before invocation start. A later state change may make the historical projection stale while a model call is already running; that does not rewrite the invocation snapshot, and any consequential adoption must revalidate current state separately.

## Storage independence

The ontology is not the database schema. SQLite is the first implementation. Schema v4 uses WAL + `synchronous=FULL`, explicit write transactions, versioned schema metadata, and canonical semantic sequencing. Those mechanisms may be replaced as long as the same invariants remain true.
