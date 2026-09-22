# Context-Need Fulfillment Decision Contract v0.1

This document establishes the first governed transition from a persisted model-produced `ContextNeedProposal` to a durable host decision. It deliberately stops before retrieval, requirement planning, projection compilation, or model continuation.

## Forcing function

`ContextNeedProposal` solved the first control problem: a model can state that it needs additional information without ordinary generated text being interpreted as an executable request.

That left a second gap. A persisted proposal survived restart, but there was no durable, auditable boundary that could say whether the host accepted or rejected that proposal and, if accepted, which request identity and resource bounds were created from it.

The minimum next mechanism is therefore:

```text
ContextNeedProposal          model-produced, non-authoritative
        |
        v
ContextNeedDecision          explicit host decision
        |
        +---- REJECTED ----> no child request
        |
        +---- ACCEPTED ----> fresh child ContextRequest
                              |
                              v
                       future governed fulfillment
```

The final arrow is still outside this slice.

## Governing distinctions

```text
ContextNeedProposal
    != ContextNeedDecision
    != ContextRequest
    != retrieval / requirement planning
    != ContextProjection
    != permission to continue cognition
```

Acceptance authorizes creation of one bounded child `ContextRequest`. It does not authorize or perform the later operations represented by that request.

## Decision contract

`ContextNeedDecision` records:

- its own durable UUID;
- the persisted `context-need:v1` artifact being decided;
- `ACCEPTED` or `REJECTED`;
- decision time;
- decision reason;
- `decision_source`, a caller-supplied audit label;
- parent model invocation;
- parent cognitive request;
- parent context projection;
- parent context request;
- optional child context request ID for accepted decisions.

An accepted decision must carry a child request ID. A rejected decision must not.

`decision_source` is intentionally **not** an authentication or authorization primitive. It does not prove a `Principal`, `PermissionGrant`, or capability. In this executable slice, trust comes from which host code is allowed to call the coordinator/store boundary. Principal-bound authorization is a later control layer and must not be inferred from the label.

## Persisted-provenance gate

The decision store does not accept a free-floating in-memory proposal as provenance. Before recording a decision it re-establishes the complete durable chain inside the write transaction:

```text
GeneratedArtifact(kind=context-need:v1)
    -> ModelInvocation
    -> CognitiveRequest
    -> ContextProjection
    -> parent ContextRequest
```

The boundary requires:

- the artifact exists in the store;
- its artifact kind is exactly `context-need:v1`;
- its payload passes strict versioned deserialization;
- the artifact references the recorded parent invocation;
- the invocation completed successfully and has no error;
- invocation → cognitive-request lineage matches;
- cognitive-request → projection lineage matches;
- projection → parent-request lineage matches;
- the decision time does not precede the completed proposal;
- the artifact has not already received another decision.

The store reconstructs decision and child-request values through their public invariants before writing, so post-construction mutation of a nominally frozen dataclass cannot bypass the durable boundary.

## Acceptance

`ContextNeedCoordinator.accept()` creates a new child `ContextRequest` from the accepted proposal. The child is constrained as follows:

- it receives a **fresh** request UUID; pre-existing request identities cannot be adopted retroactively as the child;
- its query is exactly the proposal query;
- its descriptive coverage labels are exactly the proposal labels;
- it receives no exact `(subject, predicate)` requirements directly from the model proposal;
- it inherits the parent request's `goal_ref`, `task_ref`, `known_at`, and `valid_at` selectors;
- its token budget is a positive integer no greater than the parent request's token budget;
- when the parent has a positive latency budget, the child cannot remove or increase that bound;
- supplied Boolean values are rejected as budgets rather than being accepted through Python's `bool <: int` relationship.

If the caller does not supply child budgets, the current v0.1 policy inherits the parent's bounds.

### Budget claim ceiling

This slice establishes **per-child non-amplification**, not a cumulative resource ledger. `child_budget <= parent_budget` prevents one accepted child from widening the parent's declared bounds, but it does not subtract already consumed model or context work and does not prove a total multi-step budget across a future reasoning loop.

Therefore:

```text
non-amplifying child bound != remaining-budget accounting
```

Cumulative accounting remains a separate forcing function because the present runtime does not yet have an authoritative cross-step consumption ledger from which a meaningful remainder could be derived.

## Freshness fence

Acceptance is fail-closed when the source `ContextProjection` is already stale. The stale check is repeated while holding the SQLite write lock used to persist the decision, so a relevant semantic write cannot race between acceptance validation and commit.

Rejection does not create work and is allowed even when the source projection has since become stale. The rejection remains an auditable historical decision about the persisted proposal.

Acceptance does not guarantee that the parent remains fresh forever. A later continuation boundary must revalidate current state before using any newly compiled projection to continue cognition.

## Atomicity and uniqueness

For an accepted proposal, the child request and decision are written in one SQLite transaction. If either insertion fails, neither survives.

The schema and store enforce:

- one decision per context-need artifact;
- one accepted decision owner per child request;
- child request identity distinct from parent request identity;
- a newly created child request rather than aliasing an existing request;
- accepted/rejected child-nullability consistency.

This makes retries observable rather than silently duplicating fulfillment state. A caller that retries after a committed decision receives an explicit already-decided failure and can reload the durable decision.

## What acceptance still does not do

An accepted child `ContextRequest` is durable operational intent for future context work. Acceptance does **not** automatically:

- run `LexicalCandidateGenerator` or another retriever;
- call `ControlledRequirementPlanner`;
- convert descriptive labels into exact semantic addresses;
- compile a `ContextProjection`;
- combine or replace the parent projection;
- mutate, restore, archive, or strengthen memory;
- allocate a new model invocation;
- continue the previous model invocation;
- grant an external action capability or permission.

Those transitions remain explicit so that model output cannot acquire execution authority merely by being accepted as an information need.

## Persistence and schema

SQLite schema v7 adds `context_need_decisions`. The record retains the complete parent lineage and optional child request reference. Context-need decisions are durable operational control records; creating one does not advance the semantic frontier because it does not by itself change epistemic truth.

Existing schema upgrades remain in-place and idempotent. The earlier v6 projection-lineage migration still runs before the schema version is advanced when opening pre-v6 stores.

## Deliberate limitations

This slice does not yet implement:

- `Principal`/`PermissionGrant` authorization for who may accept or reject proposals;
- cumulative remaining-budget accounting across a chain of cognitive steps;
- automatic retrieval or requirement-plan execution for an accepted child request;
- projection augmentation/replacement semantics;
- parent/child projection and continuation records beyond the request/decision lineage captured here;
- loop/step limits, repeated-need detection, or cycle prevention;
- current-frontier revalidation immediately before a later continuation;
- cancellation/revocation of a previously accepted child request;
- provider-specific streaming or tool-call representations.

These limitations prevent this slice from claiming general iterative reasoning. It establishes only the durable decision and request-creation boundary required before such a loop can be designed safely.
