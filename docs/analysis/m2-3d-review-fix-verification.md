# M2-3d review-fix verification

Scope: `codex/m2-3d-daily-basis-fixes`, based on main `6387968`.
Integrated main `4867549` in `49d7064`, preserving both contract sections and keeping desktop bytes identical to main.
First contract commit: `e763bdb`. This report records focused local evidence,
not complete CI or the required independent Claude review. Those gates remain
pending. Original failures and superseded measurements remain in ignored
`.gitnexus/verification/`; the adjacent JSON records the aggregate status.

## Contract and boundaries

`DailySignalDataView` appends `verified_at` and `expires_at`, both optional
datetimes with `None` defaults. There is no new UiAction, IPC operation, error
code, client proof authority, financial action or LIVE opt-in. Existing registry
initialization already registers this contract. The new `OfficialStockManifest`
is a local storage-port return value, with no journal, research-worker or IPC
serialization path. ResearchResult, research fingerprints and legacy codec
omission rules are unchanged in this branch.

The reviewed diff does not change desktop sources, G3 locked sources, SDK pins,
PROJECT_STATE, costs, workflow or layer configuration. Generated inventory and
observer fixtures are separate baseline work. Existing test assertions remain;
fixture changes supply trusted import clocks, the added keyword contract, exact
revision-probe SQL allowances and an explicitly partial-overlap source range.

## F1–F6 behavior

| Item | Implemented behavior and limit |
| --- | --- |
| F1 | Durable cursor/intent checks precede reconstruction. Native prewarming occurs outside bundle/engine/owner locks; locked admission accepts only a warmed same-revision history. LRU limit is 128 histories, with the full immutable calendar in the key. Each revision requires complete payload/provenance verification. |
| F1 storage | Active manifests and selected distinct sources each have a 242 limit; a manifest is limited to 128 KiB, each payload to 8 MiB and selected payloads to 64 MiB. Count/byte metadata is checked before loading payload BLOBs, including UTF-8 TEXT stored in a corrupted BLOB column. An over-limit publication rolls back atomically. |
| F2 | Ordinary source read/parser failures become typed refusals at the boundary. They neither admit a signal nor permanently mark the financial journal failed. |
| F3 | Explicit offline-manifest import and per-invocation consented download feed the real SQLite/source/ManualRuntime assembly. Runtime pumps and views never download. Tests use recorded public responses and fake SDKs. |
| F4 | **DEFERRED:** runtime history still requires complete research-to-signal coverage. The port does not distinguish a separately admissible live signal range from training coverage. Relaxing it here could silently shorten research. A gap outside the last 20 signal bars can therefore still block automation. |
| F5 | Relevant corporate actions must agree with the immediately preceding verified RAW DAY close within 0.005. No predecessor is invented for an action that cannot adjust an earlier in-snapshot row. RAW fills and entitlement-unknown refusals remain. |
| F6 | VERIFIED presentation expires after 30 seconds; dispatch-source refusal invalidates its view immediately. Snapshot projection reads cached rows without source IO. Presentation freshness does not authorize an order. |

Arrival comes from the trusted store clock in the atomic import, not the manifest
or a later history read. Every relevant raw payload must have arrived after its
own verified DAY close and no later than the current clock; a later event
response cannot mask an early raw response. Legacy missing arrival stays unknown.
Reimport is a new actual arrival, not proof of earlier availability. Neither an
arrival timestamp nor an official URL proves exchange endpoint finality.

Superseded active rows are archived before deletion in the same transaction.
The archive retains the full original instrument/range/source references/arrival
and canonical digest, including legacy rows with unknown arrival. Every raw
payload and immutable manifest archive is retained: **archive growth is
intentionally unbounded**. `official_manifest_archive(source_digest)` resolves an
individual archived source set; an arbitrary history union digest cannot be
inverted without explicit references or an operator-selected archive set.
History and archive reads do not write or reconstruct current authority.

## Regression found by selected tests

The first selected R8 batch ran 223 modules / 2,950 tests in 597.874 seconds and
reported eight failing modules. It is not an all-green result. Two launch-path
problems were resolved as harness issues without changing product assertions;
their final per-module counts remain to be appended. Five product regression
modules have subsequently passed unchanged (55 tests). The 15 new application
checks also pass after correcting their own fixture, for 70/70 in that rerun.
The installer module retains two host-precondition failures: an existing visible
application lifetime must not be disturbed. No assertion was skipped or weakened
to hide them. The two runner-path modules pass unchanged in the actual shared virtual environment (3 + 15 tests). Final results are listed in the JSON.

The real market snapshot regression was the strict nonblocking revision getter
being reused by ordinary market views while a normal history worker held the
store mutex. Ordinary `revision` now waits and reads a fresh version;
`verification_revision` retains nonblocking mutex/SQLite refusal for official
admission. Both use the same counter. An order never receives an old revision as
a busy fallback. The typed SIM discriminator remains independent of whether a
manual book exists, so missing owner/book proof cannot select generic admission.
The legacy SIM host pump stops new entries while preserving its exit work and
the existing generic fake-gateway engine contract.

## Local evidence

| Evidence | Result |
| --- | --- |
| Final store + unchanged KlineStore/stock-history modules | 68/68 PASS, 6.501 s; includes two new revision-seam tests |
| Store guard mutations | 40/40 killed, 10.632 s; all failures in the same test body, zero errors/skips/setup/cleanup kills |
| Source / previous-close, legacy-domain, deployment guard mutations | 81 + 58 + 33 = 172 killed; detailed assertion/boundary classification retained in raw reports |
| Root application guard mutations | 19/19 killed: 17 assertion failures and two boundary exceptions reached from the test body |
| Earlier admission guard mutations | 25/25 killed |
| Import/HTTP guard mutations | 21/21 killed |
| Independent quadratic-lookup mutation | 1/1 killed; original single-test baseline passes, restored quadratic lookup fails the unchanged lock threshold |
| Importer / existing HTTP tests | 30 + 3 PASS |
| Native connected assembly / large cache | Final strict-API rerun: 5/5 PASS, 36.976 s |
| Real LOCAL / fake-SIM startup | Final strict-API Windows Qt visible-window runs PASS, 8.070 s / 4.773 s; owned research/IPC/engine resources cleaned up |
| Static pre-push | Final post-main run PASS: Ruff (1,372 files), 1,260-file Python 3.11 syntax scan, zero static/layer/architecture findings |

The guard total is `40 + 172 + 19 + 25 + 21 + 1 = 278`, all recorded killed: 261 assertion failures and 17 boundary exceptions reached from the requested body.
These are a lower bound
on exercised guard counterexamples, not a proof that every possible fault or
cross-guard combination was covered. Boundary exceptions count only when the
requested test body exercises the changed boundary; loader/setup/cleanup errors
do not count as kills.

The explicit large fixture contains 1,553 synthetic verified DAY bars, 72 monthly
responses, 250 progressively enclosing refreshes, 573 raw archived payloads
(574 after extension), 73 active sources and one active manifest. Published
pre-split fresh samples recorded cold lock 0.09257/0.09411 s, three-hot maxima
0.02720/0.03105 s and revision lock 0.40285/0.44866 s against the unchanged
0.5-second bound. Three duplicate pumps add zero hashes, parses or payload reads;
a real revision revalidates bytes. These finite samples are not a latency
guarantee, exchange-calendar evidence or economic backtest.

See [import/native detail](m2-3d-official-daily-import-verification.md) and
[operator instructions](../design/m2-3d-official-daily-import.md). Baseline updates
were adjusted during pre-commit integration and must be isolated in the final
baseline commit; this report does not claim a single tool invocation or that
CI or Claude approval has completed.

Final strict-API native sample: cold pump 0.232492 s, cold lock 0.110958 s, three-hot maximum 0.034083 s, revision lock 0.429524 s, separate query/adoption lock 0.024565 s. The unchanged bound is 0.5 s. Full CI and Claude review remain required.

Post-main integration: 12 related modules / 236 tests PASS in 32.814 s, including unchanged LIVE and native automatic-entry tests plus baseline/layer/graph cases. The JSON lists every final module and result. Baseline generation keeps all original test assertions and applicability lists, registers three product modules and refreshes source-sensitive observer pins in one separate commit.
