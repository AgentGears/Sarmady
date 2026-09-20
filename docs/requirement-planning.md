# Requirement Planning v0.1

Sarmady treats requirement planning as a distinct derived stage between retrieval relevance and coverage sufficiency:

```text
ContextRequest
    |
    v
CandidateSet            relevance only
    |
    v
RequirementPlan         resolved / ambiguous / abstained
    |
    v
new ContextRequest      exact semantic obligations
    |
    v
CoverageContextCompiler actual support and sufficiency
```

A planner is not allowed to turn a retrieval score directly into a hard semantic constraint.

## Source lineage

This slice carries forward one result from `ElephantRock/Durable-Infinite-Context` v0.4: a deterministic non-oracle planner can use user-visible question text plus memory-derived profiles to resolve controlled identity/predicate/time cases, while preserving irreducible identity ambiguity rather than manufacturing a hard constraint.

The precursor benchmark was deliberately synthetic and controlled. Its important architectural rule survives here; its exact planner implementation does not become a runtime dependency:

> when the request does not contain enough information to resolve identity, preserve uncertainty rather than over-resolve.

Sarmady narrows the first executable port further. It does not yet implement the precursor predicate registry, profile-IDF resolver, temporal language parser, or multi-address retrieval plan. Instead it proves the planner boundary and abstention semantics over Sarmady's own candidate/coverage contracts.

## RequirementPlan contract

`RequirementPlan` is immutable, derived, and ephemeral. It carries:

- source `ContextRequest` ID;
- fingerprint of the exact source-request semantics;
- candidate snapshot/frontier;
- candidate-generator version;
- planner version;
- status;
- zero or more exact requirements;
- source candidate claim references;
- ambiguity references;
- machine-readable abstention reasons.

Statuses are:

- `RESOLVED` — exact obligations are safe to emit under this planner's contract;
- `AMBIGUOUS` — candidate evidence exposes an unresolved subject collision;
- `ABSTAINED` — the planner declines to create a hard constraint for another explicit reason.

A non-resolved plan is structurally forbidden from carrying exact requirements. This prevents downstream code from accidentally treating a partial/failed plan as usable hard constraints.

## Candidate preconditions

`ControlledRequirementPlanner` v0.1 requires:

1. the source request has no pre-existing exact requirements;
2. the candidate set references the same request ID;
3. the candidate set carries the exact source-request fingerprint;
4. the candidate set is exhaustive under its generator's matching rule.

The exhaustiveness requirement matters because candidate uniqueness is not meaningful after top-k truncation. If retrieval found five matching subjects but returned only the top one, the top result cannot safely be treated as uniquely identified.

`lexical-v0.2` therefore reports `is_exhaustive=False` whenever `limit` drops one or more lexical matches. The planner abstains before identity resolution in that case.

## Controlled v0.1 resolution rules

The first planner handles exactly one explicit predicate intent.

### Predicate

A candidate's predicate must share at least one direct lexical token with the query. Value-only relevance is insufficient to infer a hard predicate constraint.

Examples:

- query `primary memory` may identify predicate `memory_gb`;
- query `freebsd` may retrieve a claim whose value is `freebsd`, but v0.1 will not infer predicate `os` from that value alone.

If no predicate has direct lexical evidence, the planner abstains with `no-explicit-predicate-evidence`.

If more than one distinct predicate has direct lexical evidence, v0.1 abstains with `unsupported-multi-predicate-intent`. Multi-intent decomposition is deliberately deferred rather than approximated.

### Subject

If only one subject remains for the resolved predicate in an exhaustive candidate set, that subject is selected.

If several subjects remain, the planner considers only **discriminating subject tokens**: tokens appearing in one candidate subject but not the other subjects in the same predicate pool. A query such as `alpha machine memory` may therefore resolve `machine:alpha`, while `machine memory` remains ambiguous between `machine:alpha` and `machine:beta`.

A tied or absent discriminating subject produces `AMBIGUOUS` with the competing candidate claim references.

### Rank scores

`rank_score` is not consulted to break semantic ambiguity. A higher retrieval score is evidence of relevance, not authorization to manufacture identity certainty.

## Deriving an exact request

A resolved plan does not mutate its source request. `derive_request()` requires a new UUID and copies the source request's:

- query;
- token and latency budgets;
- goal/task references;
- legacy coverage labels;
- `known_at` and `valid_at` selectors.

It then adds the plan's exact requirements.

This new-ID rule is required by Sarmady's durable request semantics: once a `ContextRequest.id` is persisted, the ID may not be rebound to different request semantics. Planning changes semantics by adding hard obligations, so it must create a distinct request identity.

The derived request may then be passed to `CoverageContextCompiler`, which independently re-resolves the semantic key and determines actual `COMPLETE` / `PARTIAL` / `INSUFFICIENT` coverage. A resolved plan is therefore **not** a claim that coverage exists.

## Trust and write semantics

Planning performs no canonical writes and does not advance the epistemic frontier. It does not:

- admit claims;
- strengthen memory;
- persist candidate sets;
- persist requirement plans;
- persist the source request;
- mark coverage complete;
- invoke a model or provider.

Only a later context-projection registration persists the derived `ContextRequest` as part of its immutable projection lineage.

## Deliberate limitations

`controlled-requirement-v0.1` is a correctness boundary, not a production natural-language parser. It does not implement:

- synonyms or predicate ontologies (`RAM` does not yet imply `memory_gb`);
- stemming, spelling correction, or fuzzy matching;
- pronouns, ellipsis, or multi-turn reference resolution;
- learned entity resolution;
- multi-predicate/multi-intent decomposition;
- temporal phrase parsing beyond the temporal selectors already present on `ContextRequest`;
- LLM-based planning;
- semantic/vector candidate generation;
- adaptive retrieval expansion;
- durable plan receipts.

The next planner may be more capable, but it must preserve the same hard rule: uncertainty is an explicit output, and hard semantic constraints require evidence stronger than rank preference.
