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
     +----> MemoryEntry
     |
ContextRequest
     |
Context Engine
     v
ContextProjection (immutable snapshot)
     |
CognitiveRequest
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

## Model independence

The kernel must not know about system prompts, temperatures, tokenizers, OpenAI message arrays, or specific model names. Model adapters consume semantic `ContextProjection` objects and return non-authoritative cognitive artifacts.

## Storage independence

The ontology is not the database schema. The first implementation may use SQLite, but canonical types and invariants must survive a move to another storage engine. Materialized state may be database-specific as long as it remains reconstructible and auditable.
