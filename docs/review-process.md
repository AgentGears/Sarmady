# Pull Request Review Gate

Sarmady treats automated review as an input to maintainer review, not as a passive notification.

A pull request is mergeable only after all of the following are true:

1. The implementation has received a maintainer self-review against the relevant architectural contracts and invariants.
2. CI passes on the supported Python matrix at the final candidate head.
3. That exact head has received an independent second review. Codex is the preferred second reviewer. If Codex cannot run because its code-review quota is exhausted or the review service is unavailable, the maintainer must perform and publish a distinct substitute second review under the fallback rules below.
4. Every concrete second-review finding is explicitly dispositioned as one of:
   - **accepted/fixed** — repaired with regression coverage;
   - **already fixed** — demonstrably resolved by code already on the PR head;
   - **rejected** — retained with a written technical rationale.
5. Any material fix after the second review triggers CI again and a fresh exact-head second review. Use Codex when available; otherwise repeat the documented substitute review.
6. No blocking review thread or unresolved substitute-review finding remains at merge time.

The maintainer remains responsible for the merge decision. Passing CI is necessary but not sufficient, and a review finding is never considered handled merely because a later change happens to address it.

## Codex quota/service fallback

A Codex quota or service-availability failure is not a reason to skip independent scrutiny or leave work indefinitely blocked. It changes who performs the second-review role, not the review standard.

When Codex cannot review the final candidate head:

1. Preserve the already-frozen maintainer first-pass findings; do not rewrite them into the substitute review.
2. Start a distinct exact-head review from the diff, current contracts, adjacent implementation, tests, migrations, and CI evidence rather than from the first-pass findings list.
3. Reconstruct the review surface independently and challenge correctness, architecture, failure handling, concurrency, migrations, compatibility, security/trust boundaries, operability, maintainability, test adequacy, and documentation.
4. Publish the substitute review as a separate PR review or PR comment that names the exact reviewed commit and clearly identifies that Codex was quota/service blocked.
5. Treat every substitute-review finding exactly like a Codex finding: verify it, fix or reject it with rationale, add regression coverage for accepted defects, and rerun CI.
6. If the head changes materially, the substitute review is no longer the final gate; perform another exact-head second review.
7. Before merge, verify that the reviewed SHA is still the PR head, supported CI is green on that SHA, and no blocking findings remain.

A substitute review is not claimed to be statistically independent in the same sense as a different reviewer. The process compensates by separating it from the frozen first pass, rebuilding the review surface, explicitly recording provenance, and requiring exact-head re-review after fixes. Operationally, when Codex is quota- or service-blocked, the substitute review fulfills the same merge-gate role and is held to the same disposition and exact-head standards.

## 2026-09-20 reconciliation

PRs #1-#7 were self-reviewed and CI-gated, but Codex review comments were not systematically inspected before merge. A retrospective audit found 14 concrete findings.

Five were already resolved on current `main` by later hardening work:

- public export of `MemoryHealthSnapshot`;
- the package-level context/storage import cycle;
- projection reads that were not transactionally pinned to their advertised frontier;
- concurrent claim-head admission against an obsolete head;
- callers forging an old `snapshot_frontier` outside the matching pinned transaction.

Nine remained valid and are addressed by the review-debt hardening change:

- deep immutability of canonical claim/event values;
- deep immutability of action parameters bound to a fingerprint;
- dependency-aware rather than global-frontier projection staleness at registration;
- timestamp validation for every pre-existing evidence reference used by a claim;
- propagation of coverage/gap/omission metadata into `ModelInput`;
- rejection of non-string model response content;
- canonical lowercase SHA-256 provenance for reasoning policies;
- preservation of the pre-v5 positional `ContextRequest` constructor ordering;
- continued readability of legacy nonpositive latency values.

Regression coverage for these findings lives in `tests/test_review_debt.py` in addition to the existing concurrency and snapshot tests.
