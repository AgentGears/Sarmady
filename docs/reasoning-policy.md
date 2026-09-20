# Reasoning Policy Contract v0.1

This document freezes Sarmady's first executable reasoning-control boundary.

## Source lineage

The initial policy family is derived from `ElephantRock/Reasoning-Engine` at commit `71c69fcf0b5fc3d7b89497f98ddc1755ead5f6c2`.

The precursor `benchmark/pilot.py` defines:

- `COMPACT`: `Problem -> First Principle -> Mechanism -> Evidence -> Solution` plus epistemic, falsification, revision, uncertainty, constraint, and stopping obligations;
- `FULL`: `Observe -> Diagnose -> Derive -> Hypothesize -> Predict -> Test -> Revise -> Engineer` plus deeper causal, competing-hypothesis, discriminating-test, intervention-comparison, and feedback-loop obligations;
- `DIRECT` as a router mode for trivial, deterministic, or established tasks where deeper causal investigation adds no value.

The exact source prompt SHA-256 values are retained in Sarmady policy provenance:

- `DIRECT` router source: `66aaf0b5825eef6df78f9ab6d0d3d59ba0ee32f91b71a11503d6cc1c6542cfdc`;
- `COMPACT`: `8e9d66f50c4afaa10f0df58c5c2b11fd6c30d8600d7246c2a0aea63c71a83bd4`;
- `FULL`: `e5e5556dc09ae25b7b84aae05a3a4c921c24751645bd9e965cc506fc9e42df2d`.

The precursor held-out framework validation freezes `CONTROL`, `COMPACT`, and `FULL` as experimental conditions and records prompt hashes. It deliberately excludes adaptive routing from that primary framework-level validation. Sarmady therefore does not treat adaptive routing as established architecture in this slice.

## Policy is not a prompt

Sarmady represents a reasoning policy as an immutable semantic contract:

```text
ReasoningPolicy
  id
  version
  mode
  stages[]
  requirements[]
  source_ref
  source_sha256
  fingerprint
```

The policy contains no provider name, model name, tokenizer, temperature, message-array format, or API-specific instruction wrapper.

A provider adapter may render the same semantic contract differently for different models. That rendering is runtime/provider machinery, not canonical reasoning-policy state.

## Immutability

A registered policy ID may never be rebound to different semantics or provenance. Registration is idempotent only when the complete immutable definition and computed fingerprint match.

The fingerprint covers the policy ID, version, mode, ordered stages, ordered requirement definitions, and source lineage. Historical cognitive requests therefore remain auditable even if future Sarmady versions add new policy versions.

## Invocation provenance

A governed invocation follows:

```text
ReasoningPolicy
      |
      v
CognitiveRequest
      |
      v
ModelInput
      |
      v
ModelAdapter
```

`CognitiveRequest.reasoning_policy_id` identifies the registered immutable policy. `ModelInput` includes the full structured policy plus the same fingerprint. The adapter does not receive a hidden Sarmady prompt in place of that structure.

Reasoning-policy registration is operational configuration. It does not change claims, memories, or the epistemic frontier, and therefore does not stale an otherwise valid context projection.

## Initial policies

### `sarmady:reasoning:direct:v1`

No multi-stage protocol is imposed. The task should be answered directly when it is trivial, deterministic, or established and deeper investigation adds no decision value. This mode comes from the precursor router vocabulary; it is not represented as a separately validated framework condition.

### `sarmady:reasoning:compact:v1`

Stages:

```text
PROBLEM -> FIRST_PRINCIPLE -> MECHANISM -> EVIDENCE -> SOLUTION
```

Core obligations include problem definition, epistemic-role separation, invariant-style first principles, mechanism/evidence discipline, critical-assumption exposure, uncertainty preservation, disconfirming evidence, revision under contradiction, constrained engineering, and value-of-information stopping.

### `sarmady:reasoning:full:v1`

Stages:

```text
OBSERVE -> DIAGNOSE -> DERIVE -> HYPOTHESIZE
        -> PREDICT -> TEST -> REVISE -> ENGINEER
```

`FULL` includes the compact obligations and adds competing hypotheses under material ambiguity, causal-depth distinction, falsifiable predictions, discriminating tests, intervention comparison, and post-intervention feedback.

## Non-goals

This slice does not implement:

- adaptive selection among policies;
- a claim that one policy is universally superior;
- provider-specific prompt rendering;
- chain-of-thought persistence;
- model-specific reasoning-effort parameters;
- policy learning from outcomes;
- semantic retrieval or iterative context expansion.

Those remain separate M2 experiments or runtime concerns.
