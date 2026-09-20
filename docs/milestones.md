# Milestones

## M0 — Constitutional kernel — complete

Canonical Ontology v0.1, constitutional invariants, initial immutable contracts, source-lineage survival map, packaging, and CI.

## M1 — Persistent cognition — in progress

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
- prevent forged snapshot labels and reject backdated revisions that would create impossible knowledge-time lineages.

Still deferred within/after M1:

- model adapter and model-swap continuity;
- general entity resolution and extraction;
- semantic/lexical retrieval and adaptive coverage expansion;
- scheduled future-valid claim activation.

The exact compiler remains deliberate: retrieval intelligence must not hide persistence, temporal, conflict, or recovery defects.

## M2 — Cognitive orchestration

Reasoning policies, model adapters, cognitive routing experiments, iterative context requests, and coverage expansion.

## M3 — Governed action

Generic capability, permission, action-bound approval, execution fencing, `UNKNOWN_EFFECT`, reconciliation, and crash-safe external mutation.

## M4 — Executive cognition

Goals, durable tasks, commitments, triggers, scheduling, interrupts, and long-running work recovery.

## M5 — Heterogeneous cognitive compute

Typed decision engines, multiple model classes, multimodal processors, and calibrated escalation.
