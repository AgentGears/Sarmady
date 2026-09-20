# Canonical Ontology v0.1

Sarmady separates three classes of state:

- **Canonical state** — durable semantic facts about observations, adopted claims, authority, commitments, actions, and effects.
- **Derived/materialized state** — reconstructible views such as current claim heads, memory lifecycle state, memory-health snapshots, and context-projection staleness.
- **Ephemeral compute** — prompts, retrieval candidates, KV caches, logits, scratch reasoning, and provider-specific request structures.

## Identity

`Person` is a human identity. `Agent` is a persistent artificial identity. `Principal` is an identity that can hold or exercise authority. `Relationship` connects durable identities. `Binding` maps an identity to an external account, surface, or provider endpoint.

An `Agent` is explicitly not a model, process, thread, provider, or surface.

## Epistemic state

`Event` records that something occurred or entered the system. `Evidence` is a captured observation/source artifact. `Claim` is a proposition derived from evidence, a person statement, a system operation, or other admitted source. `ClaimRelation` expresses `SUPPORTS`, `CORRECTS`, `SUPERSEDES`, `CONTRADICTS`, or `REFINES`.

`ResolvedState` is derived from canonical claims and relations and has an explicit status:

- `MISSING` — no operative claim can be resolved for the requested temporal scope;
- `RESOLVED` — one operative claim is available;
- `CONTESTED` — an operative claim exists but explicit counterclaims are unresolved.

Claims carry both world-valid time (`valid_from`, `valid_to`) and knowledge/record time (`recorded_at`). These clocks answer different questions:

- **as-known-at**: what had Sarmady learned/admitted by knowledge time `K`?
- **valid-at**: given the selected knowledge boundary, what claim applies at world time `V`?

`claim_heads` is a rebuildable performance materialization. Canonical truth/history remains in claims, relations, evidence, events, and their semantic ordering.

## Memory

`MemoryEntry` admits an existing durable artifact into long-term recall. The target may be a claim, event, evidence item, procedure, decision, or work outcome. It does not duplicate the target's epistemic content.

`MemoryLifecycleEvent` canonically records `CREATED`, `SEEN`, `USED`, `CONSOLIDATED`, `ARCHIVED`, `RESTORED`, `TOMBSTONED`, and `DELETED`. The mutable lifecycle column on a memory entry is a rebuildable materialization of that event history.

`SEEN` and `USED` are telemetry, not lifecycle-state transitions. Seeing a memory does not imply use, usefulness, or truth.

`MemoryHealthSnapshot` is derived policy output, not canonical truth. Epistemic confidence, memory health, retrieval relevance, utility, freshness, and trust remain distinct dimensions.

## Context

`ContextRequest` describes what a cognitive computation needs under task, policy, latency, temporal, and budget constraints. It may specify `known_at` and/or `valid_at`.

`ContextItem` references canonical artifacts. `ContextProjection` is an immutable, provenance-bearing, coverage-aware projection pinned to a transactionally consistent semantic snapshot/frontier.

A projection may later become **stale** when one of its recorded dependencies changes. Staleness is derived state; the projection itself remains immutable and auditable as a historical snapshot.

A `ContextProjection` is not a prompt. A model-specific renderer converts it into provider/model input.

## Cognition

`CognitiveRequest` requests computation over a context projection. `ReasoningPolicy` selects deliberation behavior. `ModelInvocation` records a particular computation. `GeneratedArtifact` is model-produced, non-authoritative output. `ChoiceResult` is a typed finite-choice distribution. `DecisionRecord` is a durable adopted decision and may reference one or more cognitive outputs.

## Executive state

`Goal` describes a desired state. `Task` is a bounded unit of work. `Commitment` is an accepted obligation. `WorkRun` is one execution instance of a task. `Trigger` is a condition that can make work eligible.

## Authority and action

`Capability` describes a class of possible operations. `CredentialBinding` binds a principal/provider identity to credentials without exposing credentials to cognition. `PermissionGrant` establishes standing authority. `Approval` authorizes a concrete action fingerprint/challenge. `ActionIntent` describes the desired external mutation. `ExecutionAttempt` records a dispatch attempt. `Effect` records the system's current effect state. `EffectEvidence` supports effect state. `ReconciliationRun` attempts to resolve ambiguous effects.

Important inequality:

```text
permission != approval != action intent != execution attempt != effect
```

## Presentation

`AdoptedOutput` is content the runtime accepts for user-facing expression. `PresentationAttempt` records an attempted delivery. `PresentationReceipt` records what the presentation surface confirmed.

```text
generated artifact != adopted output != presentation attempt != presentation receipt
```
