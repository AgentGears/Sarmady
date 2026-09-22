# Milestones

## M0 — Constitutional kernel — complete

Canonical Ontology v0.1, constitutional invariants, initial immutable contracts, source-lineage survival map, packaging, and CI.

## M1 — Persistent cognition — complete

Completed slices:

- persist observation event, evidence, admitted claim, semantic memory admission, and materialized current head;
- reopen the store with no in-memory continuity and reconstruct current state;
- compile an immutable context projection pinned to a canonical frontier;
- admit correction/supersession as new claims without deleting old evidence;
- distinguish knowledge/record time from world-valid time;
- reconstruct current heads from canonical history after materialization loss;
- represent explicit contradiction as contested state and carry counterevidence into context;
- persist memory lifecycle events with `SEEN != USED` semantics and rebuild lifecycle materialization;
- pin context reads to a transactionally consistent SQLite snapshot;
- track context dependencies and invalidate stale projections after relevant epistemic or lifecycle changes;
- exercise concurrent reader/writer snapshot behavior and legacy schema upgrade;
- prevent forged snapshot labels and reject backdated revisions that would create impossible knowledge-time lineages;
- persist `Agent` identity independently of model/provider bindings;
- persist and rehydrate full context requests/projections across process restart;
- execute provider-neutral model adapters while persisting cognitive requests, invocation attempts, failures, and generated artifacts;
- swap model bindings across restart without changing agent identity, canonical memory, or epistemic state;
- revalidate projection freshness immediately before invocation start.

Deferred to later milestones:

- general entity resolution and extraction;
- semantic/lexical retrieval and adaptive coverage expansion;
- reasoning-policy execution and cognitive routing;
- scheduled future-valid claim activation.

The exact compiler remains deliberate: retrieval intelligence must not hide persistence, temporal, conflict, or recovery defects.

## M2 — Cognitive orchestration — in progress

Completed slices:

- immutable versioned reasoning-policy contracts with deterministic fingerprints;
- source lineage to the precursor Reasoning-Engine policy definitions;
- durable policy registration that cannot silently rebind a policy ID;
- structured policy delivery through `ModelInput`;
- cognitive-request provenance to the exact registered policy;
- policy registration without advancing or invalidating epistemic context;
- typed exact multi-key context requirements with one-snapshot compilation;
- explicit `COMPLETE` / `PARTIAL` / `INSUFFICIENT` coverage semantics;
- contradiction closure as a coverage obligation;
- dependency invalidation across every required epistemic key;
- backward-compatible persistence of pre-v5 label-only context requests;
- deterministic snapshot-bound lexical candidate discovery over semantic keys;
- temporal resolution and active-memory gating during lexical discovery;
- explicit preservation of candidate relevance ≠ context sufficiency and retrieval exposure ≠ memory strengthening;
- request-semantic fingerprints and explicit candidate-set exhaustiveness so truncated top-k retrieval cannot masquerade as uniqueness;
- controlled single-predicate natural-language requirement planning with `RESOLVED` / `AMBIGUOUS` / `ABSTAINED` outcomes;
- ambiguity-preserving subject resolution from discriminating query terms rather than raw rank preference;
- new-ID derivation of exact-requirement requests followed by independent coverage compilation;
- typed, durable, non-authoritative `ContextNeedProposal` outcomes for model steps without automatic retrieval or continuation authority;
- explicit durable `ACCEPTED` / `REJECTED` context-need decisions with full persisted lineage validation;
- fresh child `ContextRequest` creation for accepted needs with inherited task/temporal lineage, stale-source fencing, atomic persistence, and non-amplifying per-child token/latency bounds;
- rejection without child request creation, including durable replay after restart.

Still deferred within M2:

- adaptive reasoning-policy routing and routing validation;
- automatic retrieval/planning/compilation for accepted context needs, projection augmentation/replacement semantics, and multi-step iterative context acquisition;
- principal-bound authorization for who may accept/reject context needs;
- cumulative remaining-budget accounting, loop/step limits, repeated-need detection, and continuation freshness fencing;
- semantic embedding/vector candidate generation;
- general multi-intent natural-language requirement planning, predicate ontology/synonyms, and learned entity resolution;
- adaptive coverage expansion;
- provider-specific model renderers/adapters.

Adaptive routing remains experimental until separately validated. Provider-specific model adapters may be added without changing the M1 model-independence contract.

## M3 — Governed action

Generic capability, permission, action-bound approval, execution fencing, `UNKNOWN_EFFECT`, reconciliation, and crash-safe external mutation.

## M4 — Executive cognition

Goals, durable tasks, commitments, triggers, scheduling, interrupts, and long-running work recovery.

## M5 — Heterogeneous cognitive compute

Typed decision engines, multiple model classes, multimodal processors, and calibrated escalation.
