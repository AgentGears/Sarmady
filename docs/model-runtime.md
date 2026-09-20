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

## Adapter boundary

A `ModelAdapter` receives only `ModelInput`: agent/request/projection identifiers, the pinned snapshot identifier, operation metadata, the structured immutable `ReasoningPolicy` (when selected) plus its fingerprint, structured context items, and conflict references. It does not receive the canonical store, credentials, authority objects, or mutation capabilities.

Provider-specific prompts, message arrays, tokenizers, temperatures, API clients, and response formats live behind the adapter.

## Freshness fence

A stale context projection cannot create a cognitive request. Freshness is checked again under the write lock immediately before a `ModelInvocation` starts. This closes the race where relevant canonical state changes after request admission but before model dispatch.

Once an invocation has started, its projection remains a historical immutable snapshot. If canonical state changes during the model call, the invocation is not rewritten; later adoption or consequential action must revalidate current state separately.

## Failure semantics

An invocation is persisted before the adapter call. Adapter exceptions and malformed adapter responses terminate the invocation with a durable error code and do not create a `GeneratedArtifact`. Successful responses atomically terminate the invocation and persist exactly one generated artifact for that completion path.

## Model-swap invariant

A process may close, reopen the same durable store, load the same agent and context projection, and invoke a different model binding. The model swap must not mutate the agent identity, canonical claims, admitted memories, or epistemic frontier.

## Non-goals

This contract does not define provider SDKs, prompt templates, streaming, adaptive model routing, token accounting, adoption of generated claims, or external actions. Reasoning-policy semantics are defined separately in `docs/reasoning-policy.md`; provider-specific rendering remains outside the kernel.
