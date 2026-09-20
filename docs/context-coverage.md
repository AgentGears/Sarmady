# Context Coverage Contract v0.1

This document freezes Sarmady's first executable sufficiency layer for multi-fact context compilation.

## Source lineage

The design is derived from `ElephantRock/Durable-Infinite-Context` at commit `7720c2a89c1279387cb48ce3c81ca3c2420cfe9c`.

The precursor architecture separates candidate generation from **coverage control** and retains an important negative result: a relevant result is not necessarily a sufficient context. Its milestone history also records that explicit missing-output obligations were required to restore completeness when canonical growth could create absent derived outputs.

Sarmady adopts that distinction as a runtime contract rather than importing the precursor storage implementation.

## Relevance is not sufficiency

A retrieval system may return highly relevant material and still omit a fact, correction, contradiction, or dependency required for a justified computation.

Sarmady therefore treats coverage as an explicit obligation set:

```text
ContextRequest
  exact_requirements[]
      |
      v
one pinned semantic snapshot
      |
      v
resolve each required key
      |
      +--> operative claim
      +--> explicit competing claims
      +--> supporting evidence
      +--> active-memory gates
      |
      v
CoverageStatus
```

A future semantic retriever may propose candidates, but it cannot declare coverage complete merely because the candidates are relevant or highly ranked.

## Exact coverage requirement

`ExactCoverageRequirement` names one required semantic address:

```text
key
subject
predicate
role
```

`key` is a request-local stable identifier used in gap reporting. `subject` and `predicate` identify the exact epistemic key. `role` describes the operative claim's role in the compiled context.

Requirement keys must be unique within one `ContextRequest`.

## Coverage statuses

For the exact multi-key compiler:

- `COMPLETE` — every exact requirement is satisfied;
- `PARTIAL` — at least one, but not all, exact requirements are satisfied;
- `INSUFFICIENT` — none of the exact requirements are satisfied.

A requirement is not satisfied merely because an operative claim exists. Its required canonical material must survive context admission:

- the operative claim exists;
- the claim is admitted to active memory;
- required supporting evidence is addressable;
- if the resolved state is explicitly contested, every explicit competing claim and its evidence must also survive memory gating.

This makes contradiction closure part of sufficiency rather than an optional relevance enhancement.

## Snapshot discipline

All requirements in one `CoverageContextCompiler` call are resolved inside the same pinned SQLite WAL read snapshot. The projection therefore cannot combine one required fact from frontier `N` with another from `N+1` while claiming a single snapshot identity.

The resulting projection records dependencies for every required epistemic key and every memory entry that gated included claims. A later change to any dependency can stale the projection.

## Gap semantics

Unmet obligations are explicit and requirement-scoped, for example:

```text
coverage:os:missing-resolved-state
coverage:memory:claim-memory-not-active:<claim-id>
coverage:memory:missing-evidence:<evidence-id>
```

A caller can therefore distinguish "nothing useful was found" from "some required facts are present, but this specific obligation remains unresolved."

## Persistence compatibility

The existing `coverage_requirements` string labels remain supported for descriptive/request-level intent. Typed exact requirements are additive.

Schema v5 changes only the JSON encoding of `coverage_requirements_json`:

- pre-v5 list encodings remain readable;
- new writes use a tagged object containing both legacy labels and typed exact requirements.

No table rewrite or `ALTER TABLE` is required for the v4→v5 transition.

## Non-goals

This slice does not yet implement:

- semantic or lexical candidate generation;
- entity resolution;
- embedding/vector retrieval;
- automatic conversion of natural-language questions into exact requirements;
- adaptive expansion after a partial projection;
- token-cost estimation or budget-optimal packing;
- learned coverage prediction;
- transitive contradiction inference.

Those are later Context Engine layers. This slice establishes the sufficiency contract they must satisfy.
