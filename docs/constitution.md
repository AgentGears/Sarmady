# Sarmady Constitution

Status: **v0.1 / architectural baseline**

This document defines invariants that implementations must preserve. They are stronger than current storage schemas, prompts, provider APIs, or model choices.

## Constitutional invariants

1. **Model output is not canonical state.** A generated artifact can propose a claim, decision, memory admission, or action, but a governed transition must adopt it.
2. **Evidence is historical record, not mutable truth.** Corrections create new claims and relations; they do not rewrite away the evidence that caused earlier beliefs.
3. **World-valid time and knowledge time are independent.** The system must be able to represent when something was true separately from when it learned or recorded it.
4. **Current/resolved state is derived.** Materialized heads and resolved views must be reconstructible from canonical claims, relations, and evidence.
5. **Memory does not duplicate epistemic truth.** A memory entry admits a durable artifact into future recall; it references canonical state rather than becoming a second truth store.
6. **Seen is not used; used is not correct.** Retrieval exposure, cognitive use, utility, truth confidence, freshness, trust, and memory health remain separate dimensions.
7. **Context projections are immutable snapshots.** A model invocation receives a projection pinned to a semantic frontier/snapshot with provenance and coverage metadata.
8. **Semantic context is not prompt text.** Model-specific rendering is derived from a context projection and can be replaced without changing semantic state.
9. **Agent identity survives compute replacement.** An agent is not a model, process, provider, thread, surface, or context window.
10. **Permission is not approval.** Permission, approval, action intent, execution attempt, and external effect are separate objects with separate lifecycles.
11. **Unknown effect is not no effect.** An ambiguous external mutation may not be blindly retried. It must be reconciled or otherwise proven safe.
12. **Task is not commitment.** Goals, tasks, commitments, procedures, and work runs have different semantics and must not be collapsed.
13. **Generation is not presentation.** Generated output, adopted output, presentation attempt, and delivery receipt are separate states.
14. **Irreversible dispatch is fenced.** Authority and relevant semantic state must be revalidated immediately before consequential execution.
15. **Derived state carries lineage.** Every materialization must either retain enough dependency/provenance information for audit and invalidation or be deterministically reconstructible.

## Non-goals of the kernel

The semantic kernel does not own prompting, embeddings, ANN indexes, model-provider APIs, UI surfaces, tokenization, or a particular reasoning protocol. Those may implement cognitive functions, but they do not define what the persistent system can truthfully claim about itself or the world.
