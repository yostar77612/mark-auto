# M2 first-round independent source review

Review base:67249dc126423212bbcced2048992c4c50a1be48.
Reviewed composite:46665e514e49dd85d5d8680b198552d5e31aae57.
The code-review skill ran Standards and Spec as separate read-only agents in
independent detached worktrees. Both used the canonical source-equal GitNexus
index and read actual source. No tests, startup, broker operations, edits or
reindexing were performed by the reviewers. Empty concept search is explained
by disabled FTS; it was never treated as no impact. Source correction commit:
`a7a6738` (ordinary merge into the manual delivery branch).

## Standards

Documented-standard finding (P3): RuntimeBundle's three internal legacy lifecycle
flags were read using getattr fallbacks, without explicit initialization. This
contradicts CONTRIBUTING section4's prohibition on masking internal programming
errors. Initialize legacy_disconnected, legacy_disconnecting and
legacy_cleanup_unconfirmed, and use direct access while preserving refusal and
cleanup semantics.

Judgement smell (P3): the three execution methods in shared_session.py repeat
operations-lock -> owner-lock -> active-consumer validation. A small owner-owned
context manager could gather the sequence. This is a maintenance heuristic, not
a functional defect or required first-round change. Repeated safety checks and
explicit measured size exceptions were not treated as violations.

Follow-up on the actual correction: all three fields are explicitly initialized
and directly read; both old admission paths also check cleanup_unconfirmed.
The new exact public-entry/forbidden-call tests retain every old assertion. No
remaining concrete standard gap was found in that correction. Its measured
bootstrap/readability exceptions and narrow split plan must be in the independent
inventory baseline. The lock sequence is retained explicitly without adding a
new abstraction.

## Spec

Confirmed finding: old legacy commands could bypass an unconfirmed-logout latch.
The M2-1 requirement says to avoid two sessions for the same identity. Retirement
cleared the old market session but retained cleanup_unconfirmed=True, while old
CONNECT_MARKET_DATA and CONNECT_READ_ONLY admission only checked disconnecting/
disconnected. The market command could create a second session; profile read-only
login was also reachable when valid resources existed but no engine had yet
been created. Composite and authenticated dispatch had no additional latch.
Both admission paths must refuse the existing unknown-cleanup flag.

The reviewer separately traced manual preparation, canonical execution, LIVE
mutation guards, diagnostic cancellation proof, native reconciliation, durable
UNKNOWN and owned exits. FLATTEN checks accepted context/epoch, authenticated
account/environment, native generation/revision, confirmed book and lot ownership
under the writer lock, then uses canonical execution. No concrete omission was
found on those reviewed paths. Pending coordinator full/startup/CI and forbidden
real-broker acceptance were excluded from code-defect findings.

A further gateway-return hypothesis was rejected: ShioajiAdapter converts native
logout False into DomainError(outcome_unknown), ReadOnlyGatewayCache preserves
that exception, and ConnectionPort.disconnect has a None return contract. No
redundant internal fallback is added based on an invalid fake.

## Root resolution and validation

The lifecycle correction implements the explicit initialization and both unknown
admission refusals. Two exact fake regressions first failed with5 occurrences
(including3 market-action subtests), then passed in5.093s. The existing47-case
routing/readiness/market wiring/transport group passed40.057s. Ruff formatting
preserved the complete test AST. No native process, actual SDK, credential,
existing assertion, timeout, skip or risk rule changed. The source-corrected
complete discovery, actual startup and current-head CI are independent final
gates; they are not replaced by this read-only review or focused results.

Axis totals: Standards2 (worst: missing internal initialization, fixed; one
nonblocking lock-order heuristic retained). Spec1 (worst: legacy unknown-logout
re-entry through two old commands, fixed). These axes are not merged or reranked.
