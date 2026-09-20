# Pull Request Review Gate

Sarmady treats automated review as an input to maintainer review, not as a passive notification.

A pull request is mergeable only after all of the following are true:

1. The implementation has received a maintainer self-review against the relevant architectural contracts and invariants.
2. CI passes on the supported Python matrix at the final candidate head.
3. The Codex review for that head has been read by the maintainer.
4. Every concrete Codex finding is explicitly dispositioned as one of:
   - **accepted/fixed** — repaired with regression coverage;
   - **already fixed** — demonstrably resolved by code already on the PR head;
   - **rejected** — retained with a written technical rationale.
5. Any fix made after automated review triggers CI again, and a fresh Codex review is requested when the reviewed commit changed materially.
6. No blocking review thread remains unresolved at merge time.

The maintainer remains responsible for the merge decision. Passing CI is necessary but not sufficient, and an automated review comment is never considered handled merely because a later change happens to address it.

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
