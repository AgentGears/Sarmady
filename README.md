# Sarmady

Sarmady is an experimental, model-agnostic cognitive runtime for persistent intelligent systems.

The project separates **canonical semantic state** from **derived cognitive computation**. Models, retrieval systems, reasoners, decision models, storage engines, and tool providers are replaceable machinery. Durable identity, evidence, claims, memory admission, authority, commitments, effects, and recovery semantics belong to the runtime.

## Status

Sarmady is at **Canonical Ontology v0.1**. The current code is intentionally small: it defines the first semantic contracts and executable invariants before importing larger mechanisms from the source research projects.

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

See `docs/constitution.md`, `docs/ontology.md`, `docs/architecture.md`, and `docs/code-survival.md` before adding runtime behavior.
