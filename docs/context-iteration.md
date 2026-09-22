# Context-Need Proposal Contract v0.1

This document establishes the first executable boundary for iterative context acquisition during cognition without granting a model retrieval authority.

## Forcing function

Sarmady already gives a model an immutable `ContextProjection` with explicit coverage status, gaps, omissions, conflicts, and reasoning policy. A model can therefore discover during computation that the supplied projection is insufficient for the current operation.

Before this slice, the adapter had only one structured outcome: a terminal `ModelResponse`. A model that needed more information could only express that need inside ordinary generated text. Treating such text as control would collapse several architectural distinctions:

```text
model statement != context request
context need != retrieval authority
retrieval relevance != coverage sufficiency
```

The minimum missing mechanism is therefore a typed, durable, non-authoritative proposal that says what information is needed while leaving fulfillment to a later governed/context-engine boundary.

## Contract

`ContextNeedProposal` carries only:

```text
query
reason
coverage_requirements[]
```

It deliberately does **not** carry:

- a `ContextRequest` ID;
- token or latency allocation;
- exact `(subject, predicate)` obligations;
- temporal selectors;
- a candidate-generator choice;
- a retrieval limit;
- permission to restore/archive/strengthen memory;
- permission to continue model execution.

Those remain host/context/executive concerns.

## One-step runtime path

`CognitiveRuntime.invoke_step()` accepts a `StepModelAdapter`. The adapter may return either:

- `ModelResponse` — the step is terminal and produces an ordinary `GeneratedArtifact`; or
- `ContextNeedProposal` — the step is non-terminal from the caller's perspective and produces a durable `GeneratedArtifact` of kind `context-need:v1`.

```text
ContextProjection
      |
      v
   ModelInput
      |
      v
StepModelAdapter
      |
      +----> ModelResponse ---------> GeneratedArtifact
      |
      +----> ContextNeedProposal ---> GeneratedArtifact(kind=context-need:v1)
                                      |
                                      v
                              future governed fulfillment
```

`invoke_step()` does not itself perform the final arrow.

The `context-need:v1` artifact kind is reserved for the typed proposal path. A terminal `ModelResponse` cannot claim that kind and thereby smuggle ordinary text into the structured continuation channel.

## Durability and replay

The proposal is serialized into a canonical versioned JSON payload inside the existing non-authoritative `GeneratedArtifact` record. This avoids introducing a second truth store or a new canonical table merely to retain a model-produced proposal.

`context_need_from_artifact()` strictly rehydrates only `context-need:v1` artifacts. The payload contract is exact: unexpected fields or an unsupported contract version are rejected rather than silently interpreted. Serialization reconstructs the proposal through its public constructor so post-construction mutation of a frozen dataclass cannot bypass the durable validation boundary.

Durable recording matters because a process can fail after the model has emitted a need but before a host decides whether or how to fulfill it. The proposal can be inspected after restart without pretending that a follow-up request was already authorized.

Strict kind/payload validation is not an authenticity primitive. A caller that constructs an arbitrary `GeneratedArtifact` in memory has not thereby proven that the artifact came from Sarmady's trusted runtime/store path. Future fulfillment logic must establish provenance before treating a proposal as eligible input.

## Authority boundary

A persisted context need is still model output. It is not canonical epistemic truth and it is not an executable request.

The runtime therefore does not automatically:

- create a new `ContextRequest`;
- run candidate generation;
- call `ControlledRequirementPlanner`;
- compile a new projection;
- mutate or strengthen memory;
- allocate additional compute;
- invoke the model again.

This preserves the constitutional rule that model output may propose but does not govern semantic or execution transitions by itself.

## Backward compatibility

The existing `CognitiveRuntime.invoke()` contract remains terminal-only and continues to require `ModelResponse`. Existing adapters and callers are unchanged.

`invoke_step()` is opt-in. A terminal adapter can also be used through the step API because returning `ModelResponse` remains a valid step outcome.

## Failure semantics

A valid context-need proposal completes the `ModelInvocation` successfully because the provider/model call itself succeeded and returned a recognized cognitive outcome. Malformed or unsupported step outputs fail the invocation using the same durable terminal failure semantics as malformed terminal adapter responses.

## Deliberate limitations

This slice does not yet implement a full iterative reasoning loop. In particular it does not define:

- who is allowed to accept or reject a context need;
- how a proposal becomes a request-bound `ContextRequest`;
- parent/child lineage across context requests, projections, cognitive requests, and invocations;
- how a new projection is combined with or replaces the previous projection;
- remaining-budget accounting across steps;
- loop/step limits or repeated-need detection;
- current-frontier revalidation immediately before each continuation;
- automatic fulfillment of ambiguous or abstained requirement plans;
- provider-specific streaming/tool-call representations of a context need.

Those are the next control boundaries required before Sarmady can claim general iterative context acquisition during reasoning.

## Governing invariant

```text
ContextNeedProposal != ContextRequest != ContextProjection != permission to continue
```

The purpose of v0.1 is to make the first transition explicit rather than smuggling it through generated text.
