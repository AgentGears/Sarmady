# Accepted Context-Need Planning Contract v0.1

This document defines the next explicit boundary after an `ACCEPTED` `ContextNeedDecision`. It allows the context system to perform one governed candidate-discovery / requirement-planning pass and to persist the planning outcome without automatically compiling a projection or continuing cognition.

## Forcing function

The fulfillment-decision slice deliberately stopped here:

```text
ContextNeedProposal
    -> ContextNeedDecision(ACCEPTED)
    -> fresh child ContextRequest
```

That child request is durable, but its descriptive query and coverage labels are not yet exact semantic obligations. Running candidate discovery and requirement planning only in memory creates a recovery gap: after process loss there is no durable record of which accepted need was planned, which candidate snapshot/frontier and retrieval bound informed the plan, whether the planner resolved, preserved ambiguity, or abstained, or which new exact request was derived.

The minimum next mechanism is therefore:

```text
accepted ContextNeedDecision
        |
        v
accepted child ContextRequest
        |
        v
LexicalCandidateGenerator       snapshot-bound relevance
        |
        v
ControlledRequirementPlanner    RESOLVED / AMBIGUOUS / ABSTAINED
        |
        v
ContextNeedPlanningReceipt      durable operational receipt
        |
        +---- AMBIGUOUS -------> no exact request
        |
        +---- ABSTAINED -------> no exact request
        |
        +---- RESOLVED --------> fresh exact ContextRequest
                                  |
                                  v
                           future projection compilation
```

The final arrow is not automatic in this slice.

## Governing distinctions

```text
accepted need != candidate relevance
candidate relevance != planned obligation
planned obligation != coverage sufficiency
planning receipt != ContextProjection
planning receipt != permission to continue cognition
```

A planning receipt is durable operational control state. The embedded `RequirementPlan` remains derived context computation; persisting it does not turn it into epistemic truth.

## Accepted-need planning coordinator

`ContextNeedPlanningCoordinator.plan_accepted()` accepts only the UUID of a persisted `ContextNeedDecision` whose decision is `ACCEPTED`. It reloads the decision and its accepted child request, runs the existing `LexicalCandidateGenerator`, then applies `ControlledRequirementPlanner`.

The coordinator does not accept a model-produced exact semantic address. Exact requirements can appear only through the host-controlled planner path.

For the current versions, planning is deliberately narrow:

- candidate generator: `lexical-v0.2`;
- planner: `controlled-requirement-v0.1`;
- an explicit positive candidate limit, defaulting to 20;
- one source request without pre-existing exact requirements;
- one exact obligation at most when `RESOLVED`;
- explicit `AMBIGUOUS` and `ABSTAINED` outcomes remain non-executable as exact requests.

A `RESOLVED` outcome derives a fresh `ContextRequest` ID. Query, token/latency bounds, goal/task lineage, descriptive coverage labels, and temporal selectors are preserved from the accepted child request; the planner's exact requirement is added. The source request is not mutated or reused.

## Durable receipt

`ContextNeedPlanningReceipt` records:

- its own durable UUID;
- the accepted `ContextNeedDecision` UUID;
- planning time;
- the source child request ID and request fingerprint through the embedded plan;
- candidate snapshot ID and canonical frontier;
- candidate limit;
- candidate-generator and planner versions;
- `RESOLVED`, `AMBIGUOUS`, or `ABSTAINED`;
- exact requirements and selected candidate claim references when resolved;
- ambiguous candidate claim references when ambiguity is preserved;
- planner reasons;
- optional derived exact-request ID.

The candidate limit is part of provenance because changing the limit can change whether `lexical-v0.2` is exhaustive and therefore whether `controlled-requirement-v0.1` may resolve or must abstain.

The store reconstructs the receipt and plan through public invariants before persistence. It re-establishes the accepted decision and source-child lineage, verifies the source request fingerprint, validates canonical snapshot/frontier spelling and the version-specific v0.1 planner output grammar, validates referenced candidate claims against the recorded frontier, and persists the receipt together with any derived exact request in one transaction.

The receipt is not a proof that an arbitrary external planner is trustworthy. It is the durable record of Sarmady's current host-controlled planning boundary and its validated provenance.

## Freshness and the negative-space problem

`lexical-v0.2` scans the visible semantic-key universe before applying its result limit. Its uniqueness and ambiguity judgments therefore depend not only on candidates that were selected, but also on candidates that did **not** exist at the captured frontier.

A later semantic or memory-state mutation can add, remove, replace, contest, archive, or restore a candidate and invalidate a previously correct planning outcome even when the selected exact semantic key itself did not change.

For that reason the current planning receipt uses a conservative freshness rule:

```text
any post-frontier claim/relation or non-telemetry memory-state change
    => planning receipt stale
```

`SEEN` and `USED` memory telemetry are excluded because they do not change active-memory eligibility.

### Persistence-time fence

Receipt persistence occurs under the SQLite write lock. If relevant semantic/memory state changed after the candidate frontier, the store refuses to persist the plan or derived exact request. This closes the candidate-generation → planner → durable-write race.

### Projection-registration fence

A derived exact request may be compiled only while its owning planning receipt remains current. Projection registration checks planning freshness under the same write transaction used to persist the projection. If the planning proof has expired, registration fails even if the compiler's exact-key reads themselves are internally consistent.

### Post-registration propagation

A projection successfully compiled from a current planning receipt is still a historical snapshot. If later state invalidates the planning receipt, the store's projection-freshness contract reports the projection as stale dynamically with reason `context-need-planning-receipt-stale`.

This matters because cognitive-request admission and model-invocation start already call the store's projection freshness contract. The planning proof therefore cannot expire after projection creation and then be bypassed by continuing cognition from the old projection.

The same full freshness contract is used when accepting a later model-produced context need. A new accepted child cannot be authorized from a projection whose upstream planning proof has expired.

## Atomicity, retry identity, and recovery

For a resolved plan, the derived exact request and planning receipt commit atomically. If either write fails, neither survives. `AMBIGUOUS` and `ABSTAINED` receipts persist without creating a derived request.

A planning attempt is identified by accepted decision, candidate frontier, candidate limit, candidate-generator version, and planner version. Repeating the same attempt is rejected explicitly rather than silently creating another exact request. A caller recovering from an uncertain response can reload the already persisted receipt. Replanning is allowed when the frontier changes or when the host deliberately changes the candidate limit.

Receipts and their derived requests survive close/reopen. SQLite schema v8 adds `context_need_planning_receipts`; existing v7 stores upgrade in place without rewriting existing context-need decisions.

Planning receipts do not advance the semantic frontier because they do not admit epistemic truth.

## What this slice still does not do

This boundary does **not** automatically:

- compile the resolved exact request into a `ContextProjection`;
- augment or replace the parent projection;
- create a new `CognitiveRequest`;
- invoke a model again;
- loop on repeated context needs;
- maintain cumulative remaining token/latency consumption across steps;
- grant principal-bound permission to perform planning;
- use semantic embeddings or learned entity resolution;
- generalize the planner beyond its current single-predicate contract;
- mutate or strengthen memory merely because a candidate was retrieved or selected.

Projection compilation remains a separate explicit operation, and coverage remains the authority on whether the exact obligations are actually satisfied.

## Governing invariant

```text
ContextNeedProposal
    != ContextNeedDecision
    != accepted child ContextRequest
    != ContextNeedPlanningReceipt
    != derived exact ContextRequest
    != ContextProjection
    != permission to continue cognition
```
