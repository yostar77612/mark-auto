# M1 autonomous implementation report

Date: 2026-11-01, Asia/Taipei. CI repair verification is recorded below.
No PR was merged into main. Real broker and owner visual checks remain pending.

Verification completed: 2026-11-01 07:20+08:00.

## Delivery and branch order

| Work | PR | Head branch | Base | Result |
|---|---|---|---|---|
| M1-U U1–U13 | [#119](https://github.com/yostar77612/mark-auto/pull/119) | codex/m1-u-ui-defects | main | Implemented, seven research pages before/after plus compact v2 header |
| M1-1 market connection/history | [#118](https://github.com/yostar77612/mark-auto/pull/118) | codex/m1-1-market-history | codex/m1-u-ui-defects | Implemented, fake SDK/store/history/runtime tests and settings screenshot |
| M1-2 terminal | [#120](https://github.com/yostar77612/mark-auto/pull/120) | codex/m1-2-terminal-layout | codex/m1-1-market-history | Implemented, search/subscriptions/C5/chart/UI tests and two sizes |
| M1-3 alerts | [#121](https://github.com/yostar77612/mark-auto/pull/121) | codex/m1-3-alerts | codex/m1-2-terminal-layout | Implemented, twelve kinds/scanners/persistence/typed IPC/async UI |

Combined source and this report are on `codex/m1-integration`, using ordinary
merges without rewriting history. This branch is the final runnable workspace;
it also resolves the independent branches' string registrations and appended
contracts together. The repair stack is **M1-U → M1-1 → M1-2 → M1-3**;
the four string ranges are2608–2617,2618–2631,2632–2679,2680–2752. Only `codex/m1-*` branches were pushed. `origin/main`
remained `ba597b5`; design/tool base was `origin/claude/m1-terminal-design`.
The uncommitted previous attempt was inspected and usable work completed rather
than discarded. Root AGENTS.md, CLAUDE.md, handoffs,
reports and other original untracked material were not included in commits.

## Acceptance evidence

### M1-1 — specification §4.6

- Independent environment/reference-only settings and explicit market login work
  without any of the twelve trading connector references. Only SecretResolver
  resolves the selected reference; fake SDK asserts `subscribe_trade=False`
  and absence of CA, account and execution operations.
- WatchInstrument and cached full contract names do not need trade bindings.
  Fixed IX0001/IX0043 work before a downloaded directory. Actual refresh duration
  is measured; real full-market info latency remains an owner check.
- SQLite WAL stores Decimal strings, preserves corrupt DB/sidecars, merges
  coverage including empty holidays, and prioritizes official bars over live bars.
- History uses <=29-day chunks, <=40 requests/10s, priority/coalescing, annual
  watch/index history, 60-day browsing and annual daily charts; zero watches
  means zero stock backfills. Quota reserve, daily request cap, retry, cancellation,
  reconnect holes and 13:35 official correction are covered by fakes.
- Four visible periods preserve all seven existing API periods. Right-labelled
  SDK bars become minute starts in aware UTC, and screen times use Taipei.

Exact commands, individual module counts and known limitations:
[M1-1 verification](../analysis/m1-1-verification.md).

### M1-2 — specification §5.7

- Debounced/ranked/fullwidth-normalized search covers 2330, 台積 and ix0001,
  keyboard selection, offline cache and no implicit watch addition.
- Star/unstar, full-list explanation, temporary subscription release and
  promotion/demotion without duplicate subscriptions use fake count assertions.
- Six sortable quote columns, price precision/colors/unknowns, bounded Chinese
  status summaries, Taipei diagnostics, fixed index and latest selection work.
- Parameterized terminal LayoutStore preserves C5 defaults and file format;
  draggable/collapsible/named layouts, chart pan/zoom and old drawings/order-line
  behavior retain their regression tests.
- Combined TradingWindow screenshots show no outer scroll area at either size;
  chart area grows from 699×339 to 1032×558. Header details remain accessible
  by clicking the one-line context control.

Evidence: [M1-2 verification](../analysis/m1-2-verification.md),
[1366×768 combined window](../analysis/m1-final/window-1366x768.png),
[1920×1080 combined window](../analysis/m1-final/window-1920x1080.png),
[measured geometry](../analysis/m1-final/window-metrics.json).

### M1-3 — specification §6.5

- Exactly twelve ordered alert kinds and Decimal SMA/KD; fixtures cover
  formation exclusions, edges, cooldown/rearm and relevant scope filtering.
- Queued/backfilling or non-live data suppress tick alerts. Indicator seeds reset
  after history completion; closed-market heartbeat finalizes eligible bars.
- Rules persist atomically, corrupt originals are renamed/preserved, events are
  bounded in memory. Full original logs are archived before active retention;
  clear-view never deletes disk history.
- Enabled vendor rules alone control stock scanner subscriptions; disable/delete
  unsubscribes, and logout follows unsubscribe. Naive SDK times mean Taipei.
- Rule dialogs, event/chart focus and latest status are connected through typed
  serialized runtime IPC. FIFO background writes/coalesced polling keep the GUI
  responsive. Restored events do not replay notifications; new events honor the
  existing local notification setting.

Evidence: [M1-3 verification](../analysis/m1-3-verification.md),
[alert delivery notes](m1-alerts-notes.md), combined screenshots above.

### M1-U — specification §7.5

U1–U13 are mapped individually to before/after images and passing tests in
[m1-u-notes.md](m1-u-notes.md). The catalogue has a missing-glyph scan. Shared
native disclosure arrows, sidebar/progress identities, one help entry, passive
badge, comparison empty state/headers, full-row prerequisite, Chinese strategy,
single replay caption, page-title help, strategy tabs and one primary action
are implemented. The v2 context is <=48px with all original details retained.

The original partial-progress/detail tests were updated equivalently for the original U requirements:
partial progress now stays visible, and original detailed-label assertions run
after opening the details dialog. Their dismissal/height/content assertions
remain; no safety assertions, thresholds, timeouts or fixtures were weakened.

## CI repair and full-suite verification

The first delivery used changed-file prepush only. Its figures were insufficient
for complete acceptance. This repair runs full discovery on each branch and
checks the remote workflow independently; the earlier partial counts are not
represented as successful full verification.

The repaired stack uses ordinary merges, without rebase, force-push or a main
merge. #118 now targets the U branch. The final catalog contains2753 contiguous
records; each phase registers its additions inside an explicit Lane block.
Only actual new modules are appended to inventory §2.

Baseline changes are separate commits, following f05328b:

| PR | Baseline-only commits | Exact admitted changes |
|---|---|---|
| #119 | 30e8cee,3ad742c,f537fe5,b10ea42,e9c4905 | Ten catalog records, five historical text substitutions, actual U styling/text/names/tooltip inputs/table headers, precise R7 and observer deltas, U3/U4 presentation expectations |
| #118 | 4f81ab3 | Fourteen records, sixteen modules, three history-test observer rows |
| #120 | 4833324 | Forty-eight records, eight modules; source styling is a separate commit |
| #121 | e48d855 | Seventy-three unique records, eleven modules, exact observer positions/flag |

Original historical digests, provenance, r7_base, pixel/painter expectations and
eight result snapshots remain pinned. Safety assertions, class/interface limits, existing skips and timeout budgets
remain unchanged. Presentation expectations explicitly required by U3/U4/U13
were replaced with reviewed equivalent assertions, retaining original
dismissal, height and detail-content coverage. Four inline
styles move to scoped private theme functions with immediate appearance updates.

Full discovery uses the same provisioned Windows Python3.13.11 venv, patched
SQLite3.54.0 and Qt6.12.0. Per-worktree imports use that checkout and its tests first.
Only one full suite runs at a time:

```powershell
$env:QT_QPA_PLATFORM='offscreen'; $env:PYTHONUTF8='1'
& 'C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe' -m unittest discover -s tests -v
```

| Stage | Tested head | Complete discovery | Exit / difference from main |
|---|---|---|---|
| unchanged main | ba597b5 |3760 tests /1898.475s |1;10 failures,27 errors,42 original skips |
| U | `baaf503` |3769 tests /1464.224s |1; FAILED (failures=10, errors=27, skipped=42); **zero new failure identities** |
| M1-1 | `f71d1a0` |3821 tests /1485.703s |1; FAILED (failures=10, errors=27, skipped=42); **zero new failure identities** |
| M1-2 | `2b324f7` |3838 tests /1451.909s |1; FAILED (failures=10, errors=27, skipped=42); **zero new failure identities** |
| M1-3 | `b445db3` |3882 tests /1466.537s |1; FAILED (failures=10, errors=27, skipped=42); **zero new failure identities** |


The unchanged-main run failed with10 failures/27 errors/42 original skips.
The36 distinct identities and host causes are listed in
[m1-ci-main-baseline.md](../analysis/m1-ci-main-baseline.md). Full branch results
are checked against those identities and failure evidence; no local nonzero
exit is called a passing suite. Native Windows host failures were not waived
on CI: every mandatory remote check is checked separately.

Additional per-PR `pwsh -File tools/prepush.ps1 -Tests -Base <parent>` results:

| Stage | Changed-file tests | Exit / remaining host failures |
|---|---|---|
| U, parent origin/main |329 in60.256s |1; three existing symlink errors and three existing handle failures |
| M1-1, parent U |142 in30.937s |1; same three handle failures |
| M1-2, parent M1-1 |88 in35.963s |1; existing redirector startup class error, one original skip |
| M1-3, parent M1-2 |121 in35.254s |1; same existing redirector startup class error |

On all four branches Ruff check/format, the tracked-source Python3.11 syntax
scan and static credential gate pass. These partial test counts supplement,
rather than replace, the complete discovery results above.

| PR | Tested source | Workflow / attempt | CI |
|---|---|---|---|
| [#119](https://github.com/yostar77612/mark-auto/pull/119) | `baaf503` | [workflow](https://github.com/yostar77612/mark-auto/actions/runs/41243604116), attempt2 | **35/35 SUCCESS** |
| [#118](https://github.com/yostar77612/mark-auto/pull/118) | `f71d1a0` | [workflow](https://github.com/yostar77612/mark-auto/actions/runs/41246989363), attempt1 | **35/35 SUCCESS** |
| [#120](https://github.com/yostar77612/mark-auto/pull/120) | `2b324f7` | [workflow](https://github.com/yostar77612/mark-auto/actions/runs/41248844837), attempt1 | **35/35 SUCCESS** |
| [#121](https://github.com/yostar77612/mark-auto/pull/121) | `b445db3` | [workflow](https://github.com/yostar77612/mark-auto/actions/runs/41250590842), attempt1 | **35/35 SUCCESS** |


The U workflow initially reported a Windows3.11 native AV during settings-help
construction. It was not treated as a passing result or assigned a speculative
cause. On localPython3.11.3/Qt6.12, the exact case20 times and exact17-case prefix
passed with280/238 forced collections;33 predecessor/context tests also passed.
The prefix took49.858s. SeparatePython3.13.11 widget lifecycle probes passed
100 cycles. CI usedPython3.11.9; the native failure remains unreproduced locally. The entire workflow was rerun with `gh run rerun 41243604116`;
attempt2 completed successfully with all35 checks green; the first native AV
remains unreproduced, and no product fix is claimed for that event.
No dependency changes, product workarounds, test skips or reduced coverage were
introduced for this unreproduced native failure. One obsolete M1-1 full run was
stopped after checking its exact test-owned process chain, then restarted from
scratch; that incomplete log is excluded from all verification counts.

The resolved integration passed91 focused catalog/alias/layer/inventory/appearance,
privacy, no-inline-style, terminal and settings-help tests in22.205s. Layers and
trading architecture have zero findings. The first local integration run admitted
five task-created temporary Python helpers into the product scan; those helpers
were moved into an already ignored temporary directory, and the same91 tests
then passed. No inventory entry, exclusion rule or assertion was changed.

Integration lint, Python3.11 syntax and static credential checks pass. The root
repository-wide format check exits1 solely on the unchanged documented CRLF
checkout issue in docs/adr/0006-strategy-intent-pipeline.md. Its Git content is
identical to main; CONTRIBUTING explicitly says not to normalize it for this
item. Formatting checks on all26 changed source/document files pass. The four
PR worktrees' whole format checks also pass.

The final fake-facade/fixture-alert screenshot recapture passed at1366×768 and
1920×1080 with zero outer scroll areas. Current chart sizes are699×339 and
1032×558 after centralized terminal styles; images and measured JSON are linked
above. This is projected-monitor offline evidence, not physical-DPI or live
broker acceptance.

The additional root documentation/layout selection ran37 tests:36 passed and
one preexisting physical-workspace archive check failed. The ignored/untracked
`archives/legacy_autotrading/trader` directory dates from2026-10-19 (last
modified2026-10-31 23:12), before this work. The test is byte-identical to
origin/main; executing that original main case against the same physical root
reproduces the identical failure. The directory is preserved under the explicit
no-user-data-deletion stop line; no assertion, skip or path rule is changed.
This artifact is absent in the four clean worktrees and CI clones, where their
complete suites have the results above. It is not added to the36-identity
main-worktree failure allowance.

## Final delivery and remaining owner checks

All source phases retain their §4.6/5.7/6.5/7.5 acceptance evidence above.
Fresh GitNexus integration-merge precommit analysis: 68 changed symbols, 16 indexed flows, 38 files; **CRITICAL**, no partial/truncated result. Shared UI/theme/runtime callers remain an explicit risk, not a waiver based on unknown graph edges. Per-PR repair comparisons were U32/5 MEDIUM, M1-1 93/15 HIGH, M1-2 118/32 CRITICAL, M1-3 121/26 CRITICAL; all complete listings. No FTS/vector extension was downloaded.

The final integration source/fixtures/inventory match the fully tested M1-3
stack. Integration-only report/screenshots/contracts are retained. The30 G3
files, PROJECT_STATE, SDK pin, historical saved profiles and acceptance score
remain unchanged. No real key login, CA, account/financial operation, user-data
deletion or history rewrite occurred. Test-owned LOCAL engines left by the
baseline redirector startup failure were stopped through authenticated normal
shutdown after checking their exact fixture path and PID; user processes and
files were retained.

Pending owner checks remain actual broker quote/index/scanner fields and
latency, full-directory performance and real quotas, reconnect/13:35 correction,
sparse live ticks under the original incomplete-minute policy, both native
window sizes/DPI, keyboard/screen reader and OS notifications. M1-4 is outside
scope. Main remains ba597b5; merging any PR remains the owner’s task.

Autonomous decisions, including source/baseline separation and preserved
Windows safety guards, are recorded in [m1-decisions.md](m1-decisions.md).
