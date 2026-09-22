# PR #11 Exhaustive First-Pass Review — Frozen Baseline

**Candidate reviewed:** `f938a508ef3f31327ee70665a9aa073717748881`  
**Base:** `bb6e703000bd75004cf6fe5a56262afa9554d46c` (`main`)  
**CI:** run `35690458976` — success on Python 3.12 / 3.13 / 3.14; 142 tests passed on Python 3.13.  
**Review mode:** maintainer exhaustive first pass, completed before requesting any Codex review.

## Review objective

Review the proposed M2 context-need slice as an authority/control boundary, not merely as a new return type. The change must allow cognition to say that additional information is needed without granting a model permission to create context requests, choose exact semantic addresses, mutate memory, allocate additional compute, or continue execution automatically.

## Review surface

- forcing function and fit with the M2 milestone;
- compatibility with the constitutional `model output != authority` rule;
- domain ownership and dependency direction;
- `ContextNeedProposal` type invariants and deep-immutability boundary;
- deterministic/versioned proposal serialization and strict rehydration;
- artifact-kind namespace and typed-channel separation;
- terminal `invoke()` compatibility after runtime refactoring;
- opt-in `invoke_step()` outcome semantics;
- cognitive-request / model-invocation / artifact persistence ordering;
- stale-projection fences before request admission and invocation start;
- failure behavior for malformed/forged/mutated adapter output;
- absence of implicit `ContextRequest`, retrieval, memory, frontier, or second-invocation effects;
- crash/restart durability and replay of the proposal;
- reasoning-policy path preservation through shared invocation setup;
- storage/schema impact and migration requirements;
- trust/provenance limitations of a versioned artifact payload;
- documentation, public exports, tests, and milestone/non-goal accuracy.

## First-pass findings

### FP-01 — Durable serialization initially trusted a nominally frozen proposal

**Area:** value integrity / durable boundary  
**Severity:** material  
**Confidence:** high  
**Disposition:** fixed before freeze

A frozen dataclass can still be modified with `object.__setattr__`. The initial serializer copied fields directly from the supplied `ContextNeedProposal`, so post-construction mutation could bypass constructor validation and be persisted as if it were a valid typed proposal.

**Correction:** `serialize_context_need_proposal()` now reconstructs the proposal through its public constructor before serialization. A regression mutates `query` after construction and verifies serialization fails before artifact persistence.

### FP-02 — Generic terminal output could initially impersonate the structured context-need channel

**Area:** control-channel integrity  
**Severity:** material  
**Confidence:** high  
**Disposition:** fixed before freeze

Without a reserved artifact kind, an ordinary `ModelResponse` could claim `artifact_kind="context-need:v1"`. A later consumer that dispatched by artifact kind could then mistake arbitrary terminal text for a typed continuation proposal.

**Correction:** `ModelResponse` now rejects the reserved `context-need:v1` kind. Only the typed `ContextNeedProposal` branch of `invoke_step()` can create that artifact kind. Regression coverage verifies the reservation.

### FP-03 — Step-result invariants were initially weaker than the persisted payload contract

**Area:** result integrity  
**Severity:** material  
**Confidence:** high  
**Disposition:** fixed before freeze

The first `CognitiveStepResult` form did not prove that a `NEEDS_CONTEXT` result's typed proposal matched the versioned artifact payload, and did not forbid a `COMPLETED` result from carrying the reserved kind.

**Correction:** the result now validates status type, artifact type, status/kind pairing, required proposal type, and exact proposal/payload equivalence. A mismatch regression is included.

### FP-04 — Durable-replay claim lacked a restart proof

**Area:** recovery / operability  
**Severity:** test gap  
**Confidence:** high  
**Disposition:** fixed before freeze

The design intentionally persists context needs so a process can recover them after failure, but the initial tests reloaded the artifact only within the same store lifetime.

**Correction:** a regression now closes and reopens SQLite, reloads the exact artifact, reconstructs the same proposal, and verifies that no implicit follow-up `ContextRequest` appeared across restart.

### FP-05 — Versioned payload validation could be mistaken for provenance authentication

**Area:** trust boundary / documentation  
**Severity:** material documentation boundary  
**Confidence:** high  
**Disposition:** fixed before freeze

Kind + JSON-contract validation establishes structural integrity only. An arbitrary in-memory `GeneratedArtifact` can still be fabricated by a caller with object-construction access.

**Correction:** code/docstrings and `docs/context-iteration.md` explicitly state that parsing does not authenticate trusted runtime/store provenance. Future fulfillment must establish provenance before a proposal becomes eligible control input.

## Final-head verification

On `f938a508ef3f31327ee70665a9aa073717748881`:

- `ContextNeedProposal` contains information need only: query, reason, descriptive coverage labels.
- The proposal contains no context-request ID, exact semantic address, temporal selector, retrieval policy, budget grant, memory authority, or continuation authority.
- `CognitiveRuntime.invoke()` remains terminal-only and still requires `ModelResponse`.
- `invoke_step()` is opt-in and accepts only `ModelResponse` or `ContextNeedProposal`.
- Valid context need output produces exactly one non-authoritative `GeneratedArtifact` and a successful terminal `ModelInvocation`; it does not itself fulfill the need.
- Malformed or post-construction-mutated proposal output terminates the invocation with the existing durable adapter-error path and persists no artifact.
- The reserved artifact kind cannot be emitted through generic `ModelResponse`.
- `create_cognitive_request()` and `start_model_invocation()` retain the two existing stale-projection fences.
- No schema migration is required: the existing generic `generated_artifacts` table already durably stores kind/content/lineage.
- The context-need path does not advance the epistemic frontier.
- The proposal survives store close/reopen and remains parseable without creating a follow-up context request.
- Existing model/runtime, policy, context, persistence, and migration regressions remain green in the full matrix.

## Failure-mode review

Examined explicitly:

- blank/malformed/duplicate proposal fields;
- caller-owned collection mutation;
- `object.__setattr__` mutation after construction;
- malformed JSON and unknown contract version;
- unexpected payload fields;
- generic response spoofing the reserved artifact kind;
- unsupported adapter return type;
- mismatch between step status, artifact kind, and typed proposal;
- adapter failure before artifact completion;
- stale projection before cognitive-request admission;
- stale projection before invocation start;
- process restart after successful context-need persistence;
- forged in-memory artifact provenance (documented limitation, not silently trusted).

## Areas reviewed with no blocking issue found

- provider-neutrality and lack of provider SDK coupling;
- no new storage-to-domain dependency cycle;
- no canonical semantic writes from the proposal path;
- no memory `SEEN`/`USED` or lifecycle mutation caused by proposing a need;
- no automatic candidate generation/planning/coverage compilation;
- no implicit loop, recursive invocation, or budget replenishment;
- no weakening of existing `invoke()` model-swap/failure semantics found;
- no schema-version or migration requirement created by this slice;
- public exports align with the documented API;
- milestone text does not claim full iterative context acquisition is complete.

## Open questions / deliberately deferred boundaries

These are not implemented or claimed by this PR:

- provenance/eligibility gate for accepting a persisted proposal;
- proposal -> `ContextRequest` authorization and exact parent/child lineage;
- budget accounting across cognition/context iterations;
- projection augmentation versus replacement semantics;
- loop bounds, repeated-need detection, and no-progress termination;
- current-frontier revalidation immediately before continuation;
- handling `AMBIGUOUS` / `ABSTAINED` requirement plans during fulfillment;
- provider-specific streaming/tool-call representations;
- semantic/vector retrieval or general entity resolution.

These remain separate forcing-function decisions. Their absence must not be read as implicit authorization to implement them in this slice.

## Frozen first-pass state

**FIRST-PASS REVIEW COMPLETE**

Known findings: FP-01 through FP-05, all independently discovered and corrected before this freeze.  
Suspected unresolved findings: none.  
Blocking findings on reviewed exact head: none.  
Areas requiring independent second-review challenge: authority leakage, typed-channel spoofing, durable-boundary integrity, runtime-refactor compatibility, crash/replay semantics, and any hidden path that could turn a model proposal into execution authority.

This file is the immutable first-pass baseline. It must not be rewritten to agree with a later Codex/substitute review.