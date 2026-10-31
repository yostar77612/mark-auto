# M1 autonomous implementation report

Date: 2026-11-01, Asia/Taipei. Status: **all four implementation PRs opened;
offline functional acceptance completed; external/native owner checks pending**.
No PR was merged into main. CI/review results were not awaited or represented as passed.

## Delivery and branch order

| Work | PR | Head branch | Base | Result |
|---|---|---|---|---|
| M1-1 market connection/history | [#118](https://github.com/yostar77612/mark-auto/pull/118) | codex/m1-1-market-history | main | Implemented, fake SDK/store/history/runtime tests and settings screenshot |
| M1-2 terminal | [#120](https://github.com/yostar77612/mark-auto/pull/120) | codex/m1-2-terminal-layout | codex/m1-1-market-history | Implemented, search/subscriptions/C5/chart/UI tests and two sizes |
| M1-3 alerts | [#121](https://github.com/yostar77612/mark-auto/pull/121) | codex/m1-3-alerts | codex/m1-2-terminal-layout | Implemented, twelve kinds/scanners/persistence/typed IPC/async UI |
| M1-U U1–U13 | [#119](https://github.com/yostar77612/mark-auto/pull/119) | codex/m1-u-ui-defects | main | Implemented, seven research pages before/after plus compact v2 header |

Combined source and this report are on `codex/m1-integration`, using ordinary
merges without rewriting history. This branch is the final runnable workspace;
it also resolves the independent branches' string registrations and appended
contracts together. Only `codex/m1-*` branches were pushed. `origin/main`
remained `ba597b5`; design/tool base was `origin/claude/m1-terminal-design`.
The uncommitted previous attempt was inspected and usable work completed rather
than discarded. Originals and borrowed dependency copies remain under ignored
`.tmp-m1-originals` / `.tmp-m1-borrowed`. Root AGENTS.md, CLAUDE.md, handoffs,
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
  chart area grows from 699×326 to 1032×545. Header details remain accessible
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

Two presentation tests were updated equivalently for intentional requirements:
partial progress now stays visible, and original detailed-label assertions run
after opening the details dialog. Their dismissal/height/content assertions
remain; no safety assertions, thresholds, timeouts or fixtures were weakened.

## Verification results and remaining failures

Environment: provisioned `.venv/Scripts/python.exe` (Python 3.13.11, patched
SQLite), Ruff 0.16.10; Python 3.11 for syntax compilation. Offline Qt uses
`QT_QPA_PLATFORM=offscreen`, `PYTHONUTF8=1`, `PYTHONPATH=<repo>/tests;<repo>`.
Only one comprehensive prepush ran at a time. Phase module commands/counts are
in the linked verification files and U notes.

| Stage | `powershell -File tools/prepush.ps1 -Tests` | Interpretation |
|---|---|---|
| M1-1 | 140 tests, exit 1 | Three baseline Windows handle cases; unchanged ADR formatting |
| M1-2 | 205 tests, exit 1 | Same three handle cases plus redirector startup PID error; one original platform skip |
| M1-3 final | 249 tests, exit 1 | Same native limits; lint/format/syntax/static/layers passed |
| M1-U final | 290 tests, exit 1 | Three baseline symlink-privilege errors and three handle cases; remaining 284 passed |
| Combined | 456 tests in 115.325s, exit 1 | Three handle failures, three symlink errors, one startup error, one original skip |

The combined prepush passed Ruff lint, Python 3.11 syntax for 1032 tracked files
and the static gate. Its format failure is only the unchanged documented
`docs/adr/0006-strategy-intent-pipeline.md` formatting case. After the final
U13 import correction, both `tools/check_layers.py` and
`tools/check_trading_architecture.py` exit 0. Targeted lint/format pass.
`tests.test_m1_ui_defects`, `test_trading_ui`, `test_market_terminal_ui` and
`test_trading_architecture` together ran 58 tests, all passed.

Host failures were reproduced on unchanged origin/main `ba597b5`. The venv
Python redirector's launcher PID differs from its engine child PID, so existing
identity guards correctly refuse startup. The original twelve
`tests.test_trading_runtime` tests pass on the combined source with the actual
base interpreter and unchanged assertions. Exact supplementary command:

```powershell
& 'C:/Users/Mark/Desktop/Mark auto/.runtime-sqlite/python.exe' -S -c "import sys,unittest; sys.path[:0]=[r'C:/Users/Mark/Desktop/Mark auto',r'C:/Users/Mark/Desktop/Mark auto/tests',r'C:/Users/Mark/Desktop/Mark auto/.venv/Lib/site-packages']; result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_trading_runtime')); sys.exit(not result.wasSuccessful())"
```

Result: 12 passed in 13.705s, exit 0. Alternative base-interpreter attempts for
the three retained-handle fixtures encountered a pre-existing installed `tests`
package shadowing child-process imports. WinError1314 symlink cases require
host privileges absent here. No permission escalation, timeout changes, new
skips or altered assertions were used to report these as successful. Explicitly
identified failed-test LOCAL engines were gracefully stopped through the normal
shutdown protocol, preserving files and other user processes.

## §11 delivery checklist disposition

| Required item | All four PRs |
|---|---|
| Impact before edits; HIGH/CRITICAL called out | Done; shared runtime/contracts/charts/UI remain high risk, dynamic UNKNOWN references checked in source |
| Prepush, individual relevant tests, layers | Executed; feature tests/layers pass, baseline host/ADR failures disclosed above and in each PR |
| Complete precommit graph detection | Done per phase; M1-1 279 symbols/20 flows, M1-2 420/36, M1-3 630/52, U57/13; none partial/truncated |
| Contracts and design status | Appended each phase, merged both append sets; IMPLEMENTED means offline implementation, not real-account acceptance |
| Locked files and existing safety | Reviewed unchanged; G3, PROJECT_STATE, SDK pin, saved profiles, acceptance score, OOS/budgets/timeouts untouched |
| SDK safety | Fake-only tests; no actual key login, CA/account/order operations |
| Screenshots and human acceptance | Attached/linked; native owner visual/DPI check explicitly pending |

Graph indexing used GitNexus only and did not download FTS/vector extensions.
Large shared-flow/dispatch limitations remain lower bounds, not evidence of
zero impact. Passing tests do not waive CRITICAL aggregate graph risk.
The final merged-workspace precommit detection lists all 39 changed symbols
across 63 files and 603 affected indexed flows, CRITICAL, with neither partial
nor truncated. This covers the pending U merge relative to M1-3, rather than
recounting the already committed history/alerts. The broad shared disclosure/UI
process memberships were reviewed alongside the preserved presentation-only
diff and UI regressions; analyzer process-budget/type-resolution warnings remain
explicit limitations. Final index: 19,548 nodes, 51,698 edges, 627 flows.

## Pending owner checks / incomplete external verification

There are no deliberately unfinished M1 source features. These checks require
the owner or a suitable Windows/market environment and have not been claimed:

1. Real broker environment/reference login, quote/index/scanner callback fields,
   latency, reconnect, full directory info performance and actual subscription
   limit (configured 20), real usage/quota updates and 13:35 correction.
2. Real sparse/illiquid ticks under the existing fail-closed incomplete-minute
   policy. This policy was retained rather than relaxed for cosmetic continuity.
3. Native app visual review of all seven research pages and market terminal at
   both sizes/DPI; keyboard/screen reader and OS local notification behavior.
4. Original Windows symlink and retained-handle test prerequisites above; full
   prepush is consequently **not green**. CI/review remain external results.

No true key login, CA or financial operation was performed. No user data was
deleted, no history rewritten, and no locked file change was attempted. M1-4
five-depth/order details/sector ranking/futures are explicitly outside M1.

## Decision highlights

[m1-decisions.md](m1-decisions.md) records autonomous choices, affected files and
reasons: independent settings/session; official-over-live/holiday coverage;
strict UI module boundaries; no duplicate subscriptions; safe IO lock order;
queued-history alert suppression; asynchronous notification-safe UI; archive
before retention; preserved originals; equivalent presentation test updates;
and honest host-test limitations. Temporary tool/approval failures were resolved
through backups and clean worktree evidence; none blocks delivery.
