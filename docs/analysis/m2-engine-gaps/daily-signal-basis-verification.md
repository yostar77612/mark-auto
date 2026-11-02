# Official daily signal/research basis

Scope: first independent `codex/m2-engine-gaps` PR, based on main f0e974f.
Engine lane only. Full CI and Claude review are required before merge. No LIVE
submission, credentials, CA, desktop changes or cost-model changes are included.

## Conservative policy

Typed stock `1d` strategies in BROKER_SIMULATION use `OFFICIAL_STOCK_DAILY_V1`,
`EXCHANGE_REPORTED_DAILY_V1`, and the existing M2-9 `ADJUSTMENT_METHOD`. Each
decision rebuilds at most20 actual official daily bars, adjusting the entire
window only for events whose ex-date is on or before that completed decision day.
Research evaluates the previous completed day and executes on a later raw bar.
Actual orders, sizing and account valuation keep their raw-price authorities and
FeeSchedule. A position held across an ex-date cannot produce research PnL without
known entitlements: `stock_entitlement_unknown` remains a refusal.

The read-only runtime provider requires the requested day to precede the current
Taipei civil date. This is an operational waiting rule, not a claim that public
monthly data is immutable or final at a particular hour. The TWSE paid data product
describes14:00 ordinary data,15:30 additions for odd-lot/after-hours data, and17:30
block-trade additions. Those times do not certify the public monthly endpoint's
finality. [TWSE official product description](https://eshop.twse.com.tw/zh/product/detail/cfec9a1470e448ec91bfde006db361e8)
The official open-data catalogue lists the public monthly stock resource and its
daily update frequency. [Government open-data catalogue](https://data.gov.tw/dataset/11549)

Every expected calendar DAY in the requested range needs an actual official row.
No zero-volume padding, prior-close carry, or minute aggregation can substitute.
Sparse intraday trading therefore does not discard a valid official day. Unknown
official-day coverage, unknown negative corporate-action coverage, missing raw
payloads, mismatched hashes, unsupported endpoints/schemas, or late arrival after
the next opening keep the new signal unavailable. Late data never create an
opening catch-up signal. TMF, minute and LOCAL paths retain their existing rules.

## Provenance and publication

The provider re-parses immutable cached exchange payloads and binds every stored
OHLCV row and action to them. SHA verification alone would not bind a forged
cached row to the payload. Source URLs must identify the exchange, endpoint,
instrument and range actually understood by the parser. The TWT49U global
range response uses `資料日期`; it is parsed separately from the existing legacy
TWT48U response. All global rows must validate before absence of the target stock
can prove a negative action range. No response fields are renamed to imitate a
different schema.

Overlapping expanded-range refreshes can attest the same action at two URLs.
Deduplicate identical event facts while retaining each current row's exact
URL/digest proof and the full audit digest. Contradictory facts or a removed
historical positive remain refusals. Actual SQLite regression covers normal
expansion, conflicts, missing positives, borrowed provenance and a genuine
same-interval correction that invalidates the old research basis.

No download, SDK query or database mutation is added. The existing cache import
interface can store these verified payloads. The existing legacy stock-history
downloader is not changed into a TWT49U producer by this PR: caches lacking a
valid complete daily/action range remain unavailable. The public monthly source
also has a broader reported volume scope than ordinary DAY-only minute bars;
the policy names that scope explicitly rather than asserting equivalence.

Research receives one immutable typed history through the real worker boundary;
the parent checks returned basis, dataset and fingerprint, then rechecks semantic
source compatibility and publication CAS. Strategy form/definition/parameters,
calendar, fees, producer profile, lifecycle and source/owner identity must still
match. Blocking history reads and research run outside the writer lock.

Training provenance contains canonical raw OHLCV and action facts. Transport
payload bytes are retained for audit but may change when the next month refresh
adds observations: unchanged prior facts remain compatible. A changed old price,
volume, ex-date, previous close or reference price invalidates the evidence.
Every saved daily intent additionally binds its own complete signal window and
policy. Both bindings are saved atomically with `daily_signals_saved` and checked
again at final dispatch/commit admission. A post-training correction is therefore
also detected. Old unattested intents remain readable but cannot dispatch.

The new `ResearchResult.daily_basis` is keyword-only. Its absent value is omitted
only for the exact ResearchResult/MinuteResearchResult wire types, preserving
the existing minute settings/result/receipt byte hashes. Nonempty daily basis
is serialized; unrelated null fields remain present. Old payload defaults still
decode. Existing evidence hashes are not repinned.

## UI contract

First contract commit: `72f896d`.

- `AutomaticView.daily_signal_data: tuple[DailySignalDataView, ...] = ()`.
- Row: strategy_id, version, instrument_id, status (`VERIFIED`/`UNVERIFIED`),
  source, price_mode, adjustment_method, trade_date, available_at, source_digest,
  reason. Absent status defaults to UNVERIFIED. Snapshot uses cached facts only;
  it never triggers database/network reads. Evidence/source replacement drops
  prior verified cache authority.
- No new UiAction. Existing RESEARCH and server-driven evaluation use the
  server-owned source; a client cannot supply authoritative prices or a source.
- New error codes: `daily_signal_source_unverified`,
  `daily_signal_basis_mismatch`, `daily_signal_not_available`.

## Recorded fixtures

`tests/fixtures/daily_signal_data/manifest.json` records source URLs, retrieval
timestamps and exact byte digests. Tests recheck those digests. Fixtures are
public exchange responses; synthetic minute examples and helper histories are
explicitly labelled and are not described as real exchange tapes.

- TWSE6225,2025-06-27: seven reported transactions,11000 reported shares, close
  11.40. Its official daily row remains usable despite missing intraday minutes.
- TWSE2330,2025-06-11→12: raw closes1065→1045; the official ex-date reference
  1060.49 adjusts the preceding close to1060.49 only once the ex-date is known.
  The raw gap20 and adjusted gap15.49 are source comparisons, not trading PnL.
- Recorded TWT49U2025-06-11..12 validates both actual action facts and complete
  negative target coverage. Malformed unrelated rows cannot prove no action.

## Local verification

Related modules are selected with `tools/affected_tests.py`; full discovery is
reserved for CI. Native storage/spawn checks use the project's Python3.13 runtime
and installed dependencies. Restricted Windows named-pipe/temp permissions are
handled by rerunning the same offline tests with normal native access, not by
weakening storage ownership or assertions.

- New domain31, provider37 plus actual SQLite refresh6, research27, admission23,
  actual worker2 tests.
- Existing daily commit/native/runtime55 tests pass. Existing assertions are
  retained; fake histories now explicitly provide the required official source.
  The positive official training label is now OFFICIAL_DAILY_TRAINING; an added
  legacy positive still asserts LOCAL_SYNTHETIC_TRAINING without an official source.
- Related engine/research regression226 tests found one legacy minute wire-hash
  regression; the precise absent-field compatibility fix preserves its original
  expected hashes. The original failing method, all27 research tests and67
  directly related risk tests then pass95/95 in10.663s. After the final source
  fix, the55 daily integration tests, two actual workers and original fixed-hash
  method pass58/58 in52.214s.
- Real `_run_window` LOCAL and BROKER_SIMULATION fake-SDK windows both open and
  close normally; no real SDK import, owned endpoints removed, research released.
- Layers, quality gate, Ruff lint/format and syntax checks pass. The generic
  prepush directory walk encountered Windows inaccessible temp directories and a
  Ruff panic; equivalent checks over all1207 tracked/added Python files pass with
  configured excludes preserved. No product/test change bypasses these checks.

Mutation verification runs each case in a fresh process, first proving the same
single test passes, then deleting/replacing one guard without editing disk source:

| Area | Case/test pairs killed | Result classification |
| --- | ---: | --- |
| Daily policy/domain |58/58|54 test-body assertion failures;4 test-body exceptions|
| Official cache/parser/refresh |47/47|43 test-body assertion failures;4 test-body exceptions|
| Research/publication/worker admission |36/36|Test-body assertion failures|
| Source/intent admission and cross-module wiring |32/32|28 distinct edits;4 rechecked through an additional entry test; all assertion failures|
| Exact absent-basis wire compatibility |4/4|Test-body assertion failures|

No setup/cleanup error, skip, changed disk-source hash, or unrelated failure is
counted as a killed guard. Domain temporal/source/policy/semantic corrections,
cache/raw/action negative proof, research CAS, dispatch source enforcement, and
both saved intent hashes each have independently killing cases. Cross-module
tests exercise the actual engine evidence call, actual CLAIMED dispatch check,
and official observation/PIT/hash assignment calls rather than only helper tests.

GitNexus impact reports AutomaticView CRITICAL112, engine HIGH96,
evidence/observe/dispatch call sites CRITICAL220–251, and codec `_encode`
CRITICAL251 (164 direct,34 affected processes). Dynamic receiver omissions are
reported as incomplete graph knowledge and checked against source callers.
Final complete graph change checks and generated baseline verification are
recorded before commit. The complete all-scope check reports52 changed symbols,
652 affected flows and CRITICAL risk, with no partial/truncated result. The
repin tool changes only five module registrations and mechanical observer pins;
its own verification passes. This report does not claim CI or Claude review passed.

## Main synchronization

Normal merge `0dcedbd` incorporates main66f8b7f, including PR155 recovery/retention
and PR156 presentation. Conflicts preserve both appended contracts/decisions,
inventory sets, and registry modules. Relative to that main, desktop_app/,
workflow, costs, SDK pin, PROJECT_STATE and layer rules have no lane changes.
The main workflow update is incoming PR157, not an engine-lane workflow edit.

Merged source:181/181 direct daily/source/research/worker tests pass42.838s;
77/77 incoming PR155 tests pass35.180s. The latter retain every old assertion;
only the review-guard fixture is given explicit official input and saved hashes.
The initial four fixture failures are preserved in local evidence. Real merged
LOCAL8.348s and fake SIM5.072s windows are visible, return0, release research and
remove owned resources. Ruff and Python3.11 syntax cover1219 Python files, with
no findings; layers/quality pass and repin dry-run is entirely up to date.

The graph is refreshed on this tree. Complete compare reports are saved both
against fixed merged main66f8b7f and the advancing origin/main; the latter can
include differences from concurrent main deliveries and is not a lane ownership
list. Whole-flow/candidate caps in index construction remain acknowledged:
missing flows do not prove absence of callers. No partial/truncated change
report is accepted. Full CI must validate the final PR head/merge candidate.

PR161 was opened against the concurrently advanced main d77a893. A second normal
merge preserves appended M3 contracts/inventory and automatically merged observer
pins; no engine product conflict or lane policy change was needed. Incoming M3
has no engine hooks and retains TMF-only candidate intake. Its five application
modules and the two market-connection modules pass125/125 direct tests in3.800s.
Daily native/actual-worker/LIVE guard integration then passes26/26 in20.161s;
LOCAL9.176s and fake SIM6.308s real windows and cleanup pass. Ruff/Python3.11
checks cover1229 Python files; quality and the final repin dry-run pass. These
new source-profile inputs were validated after synchronization; no baseline was
rewritten and original mutation source functions remain unchanged.
