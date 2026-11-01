# Market settings prerequisite fix: verification

The verified source is `34673c269e80ecdc2f9a707e77b22df2fe28e0f2` on
`codex/fix-market-settings`, based on `afc45ea`. Product changes are limited to
MarketDataPanel's enum conversion and disabled-state display, and the empty
chart's message position. This final evidence commit changes documents and
captures only; product, tests, theme and tools remain byte-identical to that
source head. It does not implement M2-1 or enable any order operation.

## Focused and static verification

Five new actual-Qt tests passed after reproducing each installed defect before
its fix. They cover both environment selections through the real save button,
disabled/error and enabled connection states, all twelve alert enum choices,
and eighteen empty/error chart scenarios across fonts and sizes. Twelve related
existing modules passed: 117 existing plus five new tests, 122 total. The four
original R7 chart captures, painter-stack counts and eight result snapshots
passed unchanged. With the 29 repository-layout and eight document-layering
checks, focused verification was 159 tests in fifteen actual modules.

Ruff check/format, Python 3.11 syntax and credential/static checks passed. The
attempted `tools/prepush.ps1 -Tests -Base origin/main` itself **failed** before
running the selected tests: its unchanged PowerShell single-module selector
splats a scalar module name into characters, causing unittest's Empty module
name error. The five explicitly selected tests passed independently. The
complete serial discovery below is separate evidence; the failed prepush
command is not reported as passing. Existing tools and assertions were retained.

## Complete discovery and cause comparison

The coordinator ran the complete suite on the frozen source:

| Run | Tests | Seconds | Result |
|---|---:|---:|---|
| Unchanged main 0453136 | 3,888 | 1,968.015 | 10 failures, 27 errors, 42 skips |
| Market fix 34673c2 | 3,893 | 2,094.353 | 10 failures, 27 errors, 42 skips |

The local complete run is **nonzero**, not a pass. Its37 traceback occurrences
contain the same 36 preexisting failure IDs and zero new IDs. Thirty-six of 37
occurrences match ordered frame locations and exception-type chains; the
remaining existing native retained-handle test fails at a different native
assertion. E06 also has a different secondary cleanup error. See the bounded
[failure comparison](failure-comparison.md); identical failure identity is not
presented as proof of identical cause. No skip, timeout or assertion was changed.

Main log SHA-256:
`9de08cc417a5927ce1b0c9fc868a2bfc1fef06fb07032892a969ae22b27f5fc3`.
Market log SHA-256:
`229b39a17ffb7d193a006f6a87aa2a977d99b4fbf4e315a0f6c4d52af2cfdd87`.
The coordinator retained the complete logs and raw 37-block review separately.

## Actual application startup

These runs used the actual TradingWindow constructor and runtime composition
at 34673c2, not the screenshot facade. They exercised a visible window, seven
embedded research pages and 2,726 widgets, with real run_window returning 0.

| Environment | Seconds | SDK use | Shutdown |
|---|---:|---|---|
| LOCAL | 12.183 | Real SDK not imported | Engine and research released cleanly |
| BROKER_SIMULATION | 6.173 | Fake only: 1 login, 1 logout, 2 subscriptions, 0 order constructors, 0 orders | Engine and research released cleanly |

The simulator check used a real authenticated named-pipe host in an owned
thread with injected fake broker data; it is not a real broker login or an
owner account verification. Financial facts remained unknown in that broker
run. Exact results are [LOCAL](startup-local.json) and
[fake broker simulation](startup-broker-simulation.json). Separately, the
complete-suite-owned wrapper 153036/native 230124 fixture was normally and
authenticatedly shut down; both exited. No user process was stopped.

## UI evidence and section 10 checklist

The new [UI guidelines section 10](https://github.com/yostar77612/mark-auto/blob/66275d5092c24d6cf408bdc19f4e4e29efcbe13c/docs/design/ui-guidelines.md#10-檢查清單每個-ui-pr-附在說明)
was read from origin/main without merging it into this frozen branch. These
are real widgets rendered offline with a fake read model, Fusion, the existing
scoped application/terminal theme and Microsoft JhengHei UI. Native-screen DPI
or broker permissions are not certified by these logical-size captures.

| Page | 1366×768 | 1920×1080 |
|---|---|---|
| Market connection settings | [Screenshot](settings-1366x768.png) | [Screenshot](settings-1920x1080.png) |
| Empty market chart | [Screenshot](empty-chart-1366x768.png) | [Screenshot](empty-chart-1920x1080.png) |

Compact chart details expose the original 90px-height collision condition:
[1366-monitor capture](empty-chart-compact-1366x90.png) and
[1920-monitor capture](empty-chart-compact-1920x90.png). These file names identify
the parent logical monitor; actual chart sizes are 699×90 and 1,032×90. The normal
chart sizes are 699×272 and 1,032×490. The empty explanation and legend remain
separate in the inspected captures.

The settings captures deliberately apply disabled settings with a stale
CONNECTED value and old error. Both still display 未連線. No UI command is sent.
[Capture metrics](capture-metrics.json) retain exact client sizes, visible
controls, focus traversal and scroll observations.

| Section 10 item | Checked scope and result |
|---|---|
| Layout, primary action and dangerous-action confirmation | No page/action/layout was introduced. Existing settings and terminal layouts are retained; the changed settings group has zero primary-role buttons, so no additional primary action. Dangerous-action behavior is unchanged. This is not a claim that all old pages conform to the new global layout rules. |
| Styles | No theme or inline-style code changed. Captures use the existing theme functions. |
| Empty explanation and next step | Existing Chinese no-data explanation is retained, with existing history refresh and settings navigation available. This patch does not add or claim a redesigned central empty-state action. |
| Both sizes, clipping and scrolling | All four whole-window captures were inspected. Changed controls and chart text are readable with no overlap or truncation; settings has no visible horizontal scrollbar at either size. Existing vertical settings scrolling is retained. |
| User-facing wording and time | No new string, internal environment code or UTC timestamp was added. Existing instrument identifiers and the explicitly reference-only credential name remain visible as before. |
| Keyboard and accessibility | Actual Tab traversal is environment→key reference→save→test connection→disconnect at both sizes. Both inputs have labels and accessible names; all three buttons have accessible names. No unlabeled input was reported for the changed group. |

The capture harness explicitly rejected subprocess launches and recorded
zero commands, zero child processes and no real SDK import. It did not run
desktop startup, resolve credentials, log in, activate CA or construct orders.
No tracked Python capture tool or new test/theme change accompanies these files.

## Delivery status

Source graph review was complete before implementation commits; the shared
chart impact was MEDIUM, and UNKNOWN Qt callback results were confirmed through
bindings/source and tested. Final layout/document checks passed: 37 tests in
4.645s. Offline index refresh completed; graph change detection covered all
12 evidence files, reporting 10 document symbols, LOW risk and no partial or
truncation flag. Index flow-cap warnings remain limits of graph navigation,
not proof that an omitted path is unused. Remote PR CI is
pending at this evidence commit and must be green independently. No automatic
main merge is authorized. M2-1/M2-2 start only after this fix PR has green CI,
under the owner's subsequent instruction to use dependent branches.
