# Sarmady

Sarmady is an experimental, model-agnostic cognitive runtime for persistent intelligent systems.

The project separates **canonical semantic state** from **derived cognitive computation**. Models, retrieval systems, reasoners, decision models, storage engines, and tool providers are replaceable machinery. Durable identity, evidence, claims, memory admission, authority, commitments, effects, and recovery semantics belong to the runtime.

## Status

Sarmady is at **Canonical Ontology v0.1 / M1 persistent cognition complete / M2 cognitive orchestration in progress**.

The current executable slice now proves:

- durable event → evidence → claim → memory admission;
- explicit correction/supersession without deleting prior evidence;
- separate world-valid time and knowledge/record time;
- canonical reconstruction of current heads after materialized-state loss;
- explicit contested state for contradictions;
- append-only memory lifecycle telemetry with `SEEN != USED`;
- transactionally pinned SQLite read snapshots;
- dependency-aware context-projection invalidation;
- store close/reopen recovery;
- durable agent identity independent of model binding;
- full context-request/projection rehydration across restart;
- provider-neutral model adapters with durable invocation/artifact records;
- model-swap continuity over the same persisted semantic context;
- stale-context fencing immediately before model invocation;
- immutable, versioned `DIRECT` / `COMPACT` / `FULL` reasoning-policy contracts with source provenance and fingerprints;
- structured reasoning policy delivery to model adapters without making provider prompts canonical state;
- typed multi-key context coverage with explicit `COMPLETE` / `PARTIAL` / `INSUFFICIENT` sufficiency and contradiction closure.

Semantic/lexical candidate generation, general entity resolution/extraction, adaptive coverage expansion, adaptive reasoning routing, and external action execution remain deliberately outside the current executable slice. Model invocation exists only through a provider-neutral adapter contract; no provider SDK is part of the kernel.

## Source lineage

Sarmady consolidates research from four sole-authored precursor projects:

- **AgentGears/Alsoul** — semantic integrity, identity, authority, durable work, effect and recovery semantics.
- **ElephantRock/Durable-Infinite-Context** — evidence/claim revision, temporal state, bounded context reconstruction, materialized current state.
- **AgentGears/Ola (Moneta)** — memory lifecycle, health telemetry, seen-vs-used semantics, consolidation and forgetting policies.
- **ElephantRock/Reasoning-Engine** — deliberation policies and evaluation methodology.

The precursor repositories are research sources, not runtime dependencies. Sarmady owns a new canonical ontology and ports only mechanisms that satisfy its invariants.

## Governing equation

Persistent state may grow while active model context remains bounded:

```text
C_t = F(q_t, M_t, W_t, B, P)
```

where `M_t` is durable state, `W_t` is current world/task state, `B` is the computation budget, `P` is policy, and `C_t` is an immutable context projection for a particular cognitive operation.

## Core rule

```text
canonical semantic state != derived cognitive computation
```

A model may propose. It does not directly make a claim true, admit a memory, grant authority, confirm an external effect, or declare an irreversible task complete.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
```

See `docs/constitution.md`, `docs/ontology.md`, `docs/architecture.md`, `docs/m1-semantics.md`, `docs/model-runtime.md`, `docs/reasoning-policy.md`, `docs/context-coverage.md`, and `docs/code-survival.md` before adding runtime behavior.
