# M1 Epistemic and Context Semantics

This document freezes the semantics exercised by the M1 persistence hardening slice.

## Two clocks

A claim has a knowledge/record time and may have world-valid bounds.

`as-known-at(K)` means: reconstruct the operative epistemic head using only claims and relations that Sarmady had recorded by knowledge time `K`.

`valid-at(V)` means: using the selected knowledge boundary (current knowledge when omitted), walk the canonical revision lineage and choose the claim whose world-valid interval contains `V`.

Using both means: "given only what we knew by `K`, what would we say was valid at world time `V`?"

The two queries must not be silently substituted for one another.

## Revision and contradiction

`CORRECTS` and `SUPERSEDES` are head-moving relations. They point from the new claim to the previously operative claim.

`CONTRADICTS` does not move the head. It creates a contested resolved state. The M1 compiler includes the operative claim, explicit counterclaim(s), supporting evidence, and conflict relation references when all required memories remain active.

Conflict propagation is intentionally explicit rather than transitive. A contradiction attached to an older claim is not automatically assumed to contradict every future successor.

## Current-head limitation

M1 does not implement scheduled future activation or wall-clock expiry. A claim whose `valid_from` is later than its `recorded_at` is rejected by the write service. `claim_heads` therefore represents latest operative adoption, not a scheduler.

Temporal queries can still resolve historical validity through `valid_from`/`valid_to` and revision lineage.

## Memory lifecycle

Every admitted memory has a canonical `CREATED` lifecycle event. `SEEN` and `USED` are separate append-only telemetry events. Archive/restore/tombstone/delete transitions append lifecycle events and update a rebuildable lifecycle materialization.

Retrieval exposure (`SEEN`) does not strengthen, restore, or otherwise change memory lifecycle state.

## Context snapshots

The exact M1 compiler is intentionally not a semantic retriever. It resolves one exact `(subject, predicate)` key inside a pinned read snapshot.

Each projection records dependencies on:

- the epistemic key;
- memory entries whose active state gates inclusion.

State-changing writes invalidate dependent projections. `SEEN`/`USED` telemetry does not invalidate them.

Archived or otherwise inactive memories are omitted from model context rather than merely flagged while still being supplied.

## Deferred work

M1 does not yet solve entity resolution, embeddings, semantic retrieval, arbitrary coverage planning, automatic temporal scheduling, transitive conflict inference, model invocation, or reasoning routing.
