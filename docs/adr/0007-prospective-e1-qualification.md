# ADR 0007: Prospective, host-owned E1 qualification

日期: 2026-11-03
狀態: Accepted (implementation under the owner's E1 and OOS-accounting authorization)

Supplements [ADR 0001](0001-oos-consumption-and-budget.md).

## 背景

Historical campaigns registered final holdout but did not completely register
OOS exposure. Walk-forward explicitly disclaims independent OOS, and its display
verdict can combine different fold winners. A new ledger, checksum, copied result,
manual source label or post-hoc verdict cannot prove those observations were unseen.

## 決策

The new `m3-prospective-e1-v1` protocol therefore qualifies only one candidate
frozen before a predeclared future observation window. Unknown historical exposure
remains unavailable. The protocol does not backfill or certify historical results.

- The host freezes the exact validated v1 DSL, behavioral fingerprint, campaign
  reference, contract, complete explicit future daily-session calendar, source
  endpoint, backtest costs/configuration, source-code identity and evaluation policy.
- The first version supports TMF official full DAY sessions only. Each report date
  must be after the freeze's Taiwan civil date, and the supplied timestamps must
  match that date and the existing official day-hours/expiry constants. Past
  report dates cannot be relabeled with invented future timestamps. No holidays
  or expiry dates are inferred; the complete calendar and expiry are explicit.
- The host commits the full conservative per-contract window into the SAME
  bootstrap `holdout-registry.sqlite3` used by research. Plan and reservation
  commit together. A post-commit clock observation must still precede the first
  session before the plan becomes admitted. Unknown initial commits stay consumed.
- Explicit later host capture calls fetch only the fixed TAIFEX daily-report HTTPS
  endpoint. Redirects, alternate endpoints, imported files, caller-supplied result
  objects and provider/model callbacks are not production source admission paths.
  The fetch uses the verified trust anchors, no proxies, a 10-second socket timeout, a
  30-second total deadline and an 8-MiB bound, makes one request and never retries
  implicitly (see "Review follow-up"). Immutable planned-session captures are local only.
  Conflicting revisions, unknown outcomes and write failures terminate the plan without
  releasing its window. An exclusive in-flight capture state prevents evaluation until
  acquisition is quiescent. Only sessions closed before request start can be captured.
- After ALL planned sessions have been captured, the exact dataset/capture/calendar
  hashes and a single evaluation-attempt marker commit before scoring. One bounded
  host subprocess runs the original backtest engine on the one frozen specification
  over the complete window. There is no fold-winner mixing or OOS-based reselection.
- The fixed policy uses existing daily-return statistics and verdict rules,
  5,000 deterministic bootstrap draws, seed 20261021, and at most 900 seconds.
  At least 30 observations and `statistical_edge` are required for admission.
  This is the specified engineering E1 gate, not a guarantee of profitability.
- Completion time is the host's actual UTC clock after the worker returns. A
  minimal receipt and terminal state commit atomically. Failure, cancellation,
  interruption, unknown state and write failure never authorize a retry/refund.

## 後果

### Compatibility and information boundary

New ordinary campaigns atomically reserve BOTH their OOS and holdout envelope
before evaluating either. The new immutable `E1_EXPOSURE_PROFILE_V1` recognizes
that union. All 30 historical producer profile literals remain byte-identical;
older saved-pool records retain their original holdout-only consistency semantics
and never become production E1 merely because the new accounting exists.

The E1 reader opens the explicit authority read-only. It verifies protocol,
current/startup source identity, frozen plan, exact reservation, capture metadata,
dataset binding, completion time and receipt hash. It never selects raw captured
payload columns. Only the existing fixed `CandidateEvidence` fields are projected.
Missing, malformed or ambiguous current evidence fails closed. Stale-source
receipts are ignored and terminal history never becomes current evidence. Synthetic
mode is explicitly non-market evidence and can never be returned as qualified.

No AI tool, prompt, AIContext field, broker action, LIVE permission or automatic
scheduler is added. Capture/evaluation operations return no OOS values. Tests use
synthetic sources, mock HTTPS responses and dynamic leak sentinels only; no real
OOS evaluation or external request is part of this implementation's verification.

### Trust and operational limits

The reviewed host code, OS clock/TLS trust and authoritative bootstrap store are
trusted. Hashes are consistency bindings, not signatures authenticating arbitrary
imported artifacts. A same-user compromise or coherent replacement/rollback of the
ENTIRE authority is not detected cryptographically. Ordinary workspace restore,
copy or deletion cannot reset the separate bootstrap control record. These limits
must never be presented as proof of untouched historical data.

The source endpoint publishes available reports, not a promised archival feed.
The owner must explicitly capture each declared session while it is available;
missing sessions cannot be imputed or omitted. No network capture, scheduling,
true-market acceptance or installer verification is claimed by synthetic tests.
Existing default catalog behavior stays unavailable unless trusted composition
supplies the explicit authoritative registry. Desktop action wiring and E2
execution-data admission remain separate integration responsibilities.

The owner's 2026-11-01 D1 decision is unchanged: production orders disabled by default.
This protocol neither enables orders nor changes LIVE authorization.

## Review follow-up (PR #171 cloud review)

Changed design decisions, all of which keep the window consumed and never refund it:

- **Transient acquisition failures are retryable.** `capture` still claims `capturing`
  before the request (exclusivity is unchanged). A fetch or projection failure writes
  nothing and its outcome is known, so the plan returns to its prior `reserved`/`captured`
  state and a later explicit host call may capture again. Previously every such failure
  made the plan terminal `failed`. Unchanged and still terminal: a conflicting revision of
  stored data, any write failure, a crash or restart (the plan stays `capturing`, which
  nothing resumes), and a shutdown request (`KeyboardInterrupt`/`SystemExit`: the
  `failed` accounting is recorded and the exception is re-raised, not converted).
- **Evaluation preconditions do not consume the plan.** Sessions still open, or planned
  captures incomplete, leave the plan `reserved`/`captured`. Captured rows that are present
  but inconsistent (digest, import or calendar validation) can never become valid because
  captures are immutable: they remain terminal. The single attempt is claimed
  (`evaluating`) only once the exact dataset is built, and everything after that
  (worker, timeout, outcome check, receipt write) stays terminal.
- **Registry lock contention is waited out.** Every E1 connection waits up to 10 seconds,
  like research `_reserve_holdout`, with the per-statement work budget starting after the
  lock is held. A lock timeout before a claim changes nothing; during the capture write it
  is a known, rolled-back outcome and retryable. Previously `timeout=0` turned any
  concurrent writer into an immediate failure.
- **The source request is built like `market_providers.fetch_official`:**
  `tls_trust.build_trust_context`, `ProxyHandler({})`, no redirects, and the shared total
  deadline handler. The response row bound is `market_providers.MAX_ROWS` (the endpoint
  returns all products, both sessions and spreads), not a TMF-sized limit; malformed TMF
  rows are still refused.
- The reader hashes the 22 source files once per listing; the outcome structure is one
  shared check in `e1_protocol`. Each module keeps its own `sample_count` rule: the
  evaluator requires `1..max_bars` and then equality with the dataset's trade days, the
  reader requires equality with the frozen calendar's trade days.
