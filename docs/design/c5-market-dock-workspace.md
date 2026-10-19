# C5: Market overview dock workspace

Status: PROPOSED / NOT IMPLEMENTED. Design verification: NOT RUN.
Requirement: Shioaji borrowing list, second part, section 1.3 row C5;
global constraints in sections 0 and 0.1 apply. C5 is upcoming work.

## Problem

[MarketDashboard](../../desktop_market.py) builds instrument cards above a
horizontal main_splitter containing the watchlist, chart area and side controls.
[CandlestickChart](../../desktop_charts.py) supplies the existing chart widget.
C5 calls for rearrangeable panels and named layouts rather than this fixed
composition. This proposal makes no measured-improvement claim.

## Goals/Non-goals

- Allow chart, instrument-card and watchlist panels to be dragged and collapsed.
- Offer three presets: overview, chart-focused and watchlist-focused.
- Support named layout save/restore and reset to the overview preset.
- Automatically fall back to overview when a saved layout is corrupt.
- Keep layout persistence outside research data and all research hashes.
- Preserve existing market data flow; exclude orders, AI and C10 popout windows.

## Design

Proposed files to touch (all already exist):

| File | Existing seam and proposed responsibility |
| --- | --- |
| [desktop_market.py](../../desktop_market.py) | MarketDashboard owns cards, watchlist, chart and main_splitter; replace their layout composition with dock panels while retaining widget references and signals. |
| [desktop_charts.py](../../desktop_charts.py) | CandlestickChart.set_series and set_overlays remain the chart API; adapt size/focus behavior only if docking requires it. |
| [desktop_pages/market.py](../../desktop_pages/market.py) | MarketPage wires refresh_requested and preferences_changed; integrate separate display-layout loading/saving without changing refresh_market, load_market_cache or bind_result_layers data semantics. |
| [desktop_pages/host.py](../../desktop_pages/host.py) | PageHost exposes mount_market and window_geometry; preserve this shell boundary, adding a narrowly scoped display callback only if necessary. |
| [desktop_strings.py](../../desktop_strings.py) | Add preset names, layout actions and accessible descriptions through literal ui_text keys. |
| [desktop_theme.py](../../desktop_theme.py) | Style dock headers and focus through existing theme conventions. |

Use a page-local dock container with QDockWidget-style panels, stable panel IDs
and one instance of each existing content widget. Keep the safety/source status
visible outside collapsible panels. Provide keyboard actions to move, collapse,
reopen and reset panels; dragging must not be the only way to rearrange them.
Preserve existing objectNames, chart identity, selected instrument, timeframe,
watchlist and signal connections when changing layouts. Do not fetch, recompute
observations or start jobs on dock moves, preset switches or layout restoration.

MarketPage currently places DrawingStore under a display_profile directory next
to its settings path. Propose a separate versioned layout file in that display
profile, never in dataset/cache/result payloads or their hash inputs. Treat its
contents as untrusted display metadata: bounded names/counts, known panel IDs,
allowed positions, schema version and validated sizes only. Store no observations,
research content or executable values. Use atomic replacement for saves.
Missing, malformed, unsupported or incomplete state must restore the overview
preset; failed writes must leave the prior saved layout intact and show a B1
[ERROR_TABLE](../../quantlab/errors.py) message without exception text.
Never restore an arbitrary file path from a layout name. If settings/path is
unavailable on a minimal host, use presets in memory without persistence.

Keep MarketPage.refresh_market's consent/start_job path and load_market_cache's
existing source loading unchanged. Layout restoration must not emit refresh
intent or replace data; MarketDashboard.set_market_series and chart rendering
continue to receive the same inputs through the existing flow.

## Safety constraints (live trading disabled, G3, OOS/budget)

Live trading stays permanently disabled; no real order path is proposed.
Keep all eight G3 files and protected profile blocks in
[quantlab/saved_candidate_pool.py](../../quantlab/saved_candidate_pool.py)
untouched. The [contributor guide](../CONTRIBUTING.md) lists protected sources;
any need to edit them requires owner approval first in a separate task.
No gate, OOS one-time consumption, irreversible budget or timeout changes:
Paper 30 s, smoke 40 s and 15 min per job remain fixed. OOS/final-holdout data
must never enter AI conversations, tool returns or prompts. No ChatGPT credential
reading, storage or display; no eval/exec/new Function or dynamic execution.
Existing AST validation and Decimal money arithmetic remain authoritative.

## Test plan

All checks below are future requirements; design verification is NOT RUN.

- Add cheap offline cases for each preset, named save/restore, missing settings,
  corrupt/version-mismatched/unknown-panel layouts, failed atomic saves and reset.
  Use synthetic metadata, injected failures and temporary display profiles;
  assert research artifacts/hashes and market inputs remain unchanged and no
  refresh/job is triggered. No network, sleeps or subprocesses in new cases.
- Run the [accessibility walk](../../tests/test_accessibility_walk.py) for panel
  names, keyboard rearrangement, collapse/reopen/reset and visible focus; inspect
  both themes and enlarged fonts without relying on color alone.
- Compare snapshots using [tools/ui_snapshot.py](../../tools/ui_snapshot.py)
  and [existing baselines](../../tests/fixtures/desktop_pages_before/), including
  1366x768 presets and fallback. Use platform-independent text/control assertions.
  Only intended market-page layout baselines should need a controller refresh
  in a separate fixture-only commit; identify exact files during implementation.
- Follow [contributor verification commands](../CONTRIBUTING.md) for docs
  layering/layout, lint, compile and quality gate; run the existing market and
  desktop startup smoke modules when implementing the UI change.
- Real-App visual check is the user's final confirmation: drag and keyboard
  rearrangement, all presets, named restore, corrupt-layout fallback and chart
  continuity. Offscreen checks cannot close this requirement.

## Rollout/Verification status

Implementation: NOT IMPLEMENTED. Automated design verification: NOT RUN.
Real-App visual check: PENDING USER FINAL CONFIRMATION.
Review before a separate C5 implementation task; this document supplies no UI.
Rollback would restore the prior composition and ignore saved layout metadata,
leaving research data and settings unrelated to layouts intact.
No acceptance score change, Release or tag is proposed.
