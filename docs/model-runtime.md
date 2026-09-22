# Model Runtime Contract v0.1

This document freezes the first executable model-independence boundary.

## Identity

`Agent` is durable artificial identity. A model binding is metadata on one `ModelInvocation`; replacing `fake:model-a` with `fake:model-b`, or a future provider/model pair, does not create a new agent.

## Durable compute lineage

The runtime persists the chain:

```text
Agent
  -> ContextRequest
  -> ContextProjection
  -> CognitiveRequest
  -> ModelInvocation
  -> GeneratedArtifact
```

`ContextRequest` and the full immutable `ContextProjection` are rehydratable after process loss. `CognitiveRequest`, `ModelInvocation`, and `GeneratedArtifact` are durable operational records, but they do not become epistemic truth merely because they were persisted.

A typed `ContextNeedProposal` is model-produced non-authoritative output. When emitted through the step interface it is serialized into a versioned `GeneratedArtifact(kind=context-need:v1)` so the need survives restart without pretending that a follow-up `ContextRequest` has already been authorized.

## Adapter boundary

A `ModelAdapter` receives only `ModelInput`: agent/request/projection identifiers, the pinned snapshot identifier, operation metadata, the structured immutable `ReasoningPolicy` (when selected) plus its fingerprint, structured context items, and conflict references. It does not receive the canonical store, credentials, authority objects, or mutation capabilities.

Provider-specific prompts, message arrays, tokenizers, temperatures, API clients, and response formats live behind the adapter.

`CognitiveRuntime.invoke()` remains the terminal adapter contract and requires `ModelResponse`.

`CognitiveRuntime.invoke_step()` is an opt-in orchestration boundary. A `StepModelAdapter` may return either a terminal `ModelResponse` or a typed `ContextNeedProposal`. The latter completes the provider invocation successfully and records the proposal durably, but it does not create a new `ContextRequest`, perform retrieval, change memory, allocate more budget, or invoke the model again.

## Freshness fence

A stale context projection cannot create a cognitive request. Freshness is checked again under the write lock immediately before a `ModelInvocation` starts. This closes the race where relevant canonical state changes after request admission but before model dispatch.

Once an invocation has started, its projection remains a historical immutable snapshot. If canonical state changes during the model call, the invocation is not rewritten; later adoption, consequential action, or future context continuation must revalidate current state separately.

## Failure semantics

An invocation is persisted before the adapter call. Adapter exceptions and malformed adapter responses terminate the invocation with a durable error code and do not create a `GeneratedArtifact`. Successful terminal responses atomically terminate the invocation and persist exactly one generated artifact for that completion path.

A valid `ContextNeedProposal` is also a successful invocation outcome: exactly one versioned generated artifact is persisted, and `invoke_step()` returns `NEEDS_CONTEXT`. Unsupported step outputs are malformed adapter responses and use the same durable failure path.

## Context-need authority boundary

The step interface preserves:

```text
ContextNeedProposal != ContextRequest != ContextProjection
```

The model may say what information it needs and why. It may not, through this contract, choose exact canonical addresses, allocate token/latency budget, select a retriever, restore or strengthen memory, or authorize another invocation. Those transitions require separate context/executive logic.

## Model-swap invariant

A process may close, reopen the same durable store, load the same agent and context projection, and invoke a different model binding. The model swap must not mutate the agent identity, canonical claims, admitted memories, or epistemic frontier.

## Non-goals

This contract does not define provider SDKs, prompt templates, streaming, adaptive model routing, token accounting, adoption of generated claims, external actions, or automatic fulfillment/iteration of model-proposed context needs. Reasoning-policy semantics are defined separately in `docs/reasoning-policy.md`; context-need proposal semantics are defined in `docs/context-iteration.md`; provider-specific rendering remains outside the kernel.
