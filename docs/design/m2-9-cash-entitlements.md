# M2-9 bounded cash-entitlement continuation

## Scope and interface (2026-11-02)

This work implements offline TRAINING accounting for explicit, provenance-bound
**cash-only** events supplied by a trusted `OfficialStockSource`. It does not
complete native TWSE/TPEx entitlement ingestion. The native parser remains
unchanged: a reference-price ratio cannot establish cash/share entitlements.
No new network download, UI, broker, activation, OOS or G3 path is introduced.

`CashDividendAction` extends the existing official history `CorporateAction`
with positive gross issuer cash per share and a payment date on/after ex-date.
Its source adapter must establish cash-only status; ordinary unknown, share or
mixed events remain refused when a position crosses them. Existing event wire
fields and historical artifact bytes/hashes remain unchanged.

A distinct `CashStockResearchArtifact` carries `CashEntitlementSummary`, using
producer `markauto-official-stock-cash-training-1` and accounting method
`gross-issuer-cash-accrual-v1`. Standard `ResearchTrade.gross`,
`ResearchResult.net_pnl` and drawdown **remain raw-price-only**. The separate
cash-inclusive accrual total is not a total-return drawdown/performance feed.
The summary references event/trade indices, quantity and gross amount.

Ownership is entry date < ex-date <= exit date: sale on ex-date retains the
entitlement; purchase on ex-date does not earn it. Payment after sale retains a
receivable. The horizon is the final observed research date, not wall-clock time.
`gross_payable` means scheduled distribution by that horizon according to the
supplied payment date, NOT verified bank settlement. `gross_receivable` is the
remaining future scheduled amount. Gross issuer amounts exclude unknown personal
withholding and remittance fees; neither is silently assumed to be zero.
The gross arithmetic multiplies the supplied per-share amount exactly; it does
not invent issuer-specific rounding or promise the final credited amount.
Neither bucket finances entries; existing static-allocation admission is not a
reinvestment or cash-liquidity ledger. Short-side distribution obligations are
outside this slice and fail closed at event crossings.
The legacy daily runner still refuses typed `StrategyParameters`; its one-lot
static sizing and existing daily execution model are unchanged.

## Planned file scope

Existing source files only: `domain/stock_history.py` (cash subtype and digest),
`adapters/storage/daily_stock_store.py` (additive event storage),
`application/stock_research.py` (raw backtest admission and separate accounting),
`application/stock_research_service.py` (versioned publication/replay).
Paths are relative to `quantlab/trading/`. No new source-file inventory entries.
New test: `tests/test_m2_cash_entitlements.py`. Existing tests remain unchanged.
Behavior contract is appended to `docs/agent/IMPLEMENTATION_CONTRACTS.md` after
implementation. Shared baselines, if required, are a separate commit.

## Evidence and assumptions

- [TWSE investment Q&A](https://investoredu.twse.com.tw/Pages/TWSE_InvestmentQA.aspx?ID=1):
  entitlement depends on purchase before ex-date and survives sale on/after it.
- [TWSE reference-price explanation](https://investoredu.twse.com.tw/FileSystem/eBook/%E9%99%A4%E6%AC%8A%E6%81%AF%E5%8F%83%E8%80%83%E5%83%B9.pdf):
  reference-price adjustment is not evidence of the actual cash entitlement.
- [SFIPC distribution notice](https://www.sfipc.org.tw/News_Content.aspx?n=7542&s=3982&sms=12324):
  remittance fees can distinguish issuer distribution from credited cash.

References were checked by the coordinating agent without downloading market
observations. Tests use explicitly synthetic facts, not recorded official samples.
No real official compatibility, broker settlement or Windows-native verification
is claimed. Actual native field validation remains pending recorded source facts.

## Verification plan

Test ex-date ownership, payment after exit/horizon, duplicate/conflicting event
refusal, raw-price PnL separation, unknown/mixed/share refusal, original wire/hash
and journal replay preservation, new hash binding, storage rollback/provenance.
Run focused affected tests and repository static/layer gates. GitNexus impact was
attempted but `.gitnexus/run.cjs` is absent; targeted call-site inspection covers
stock history sync/store and stock research service/runtime. No full local suite.

## Local verification result

Implementation completed in this bounded scope; native official entitlement
mapping and share/mixed events remain incomplete. Standard result semantics and
historical event/artifact hashes are preserved by immutable golden assertions.
The actual `RuntimeBundle.research_stocks` path was exercised with its own store,
strategy, calendar and costs: cash accrual is durable, engine state unchanged,
and no additional download calls occur.

Using `/workspace/scratch/0551d866db25/markauto-m3/tools-venv/bin/python`
(Python 3.12) and its Ruff 0.16.10:

- `python -m unittest discover -s tests -p <module>.py`: **251 tests passed**
  across 18 focused modules: `test_m2_cash_entitlements` (23),
  `test_m2_stock_history` (17), `test_m2_stock_research` (15), `test_kline_store`
  (9), `test_m2_stock_maintenance` (13), `test_trading_domain` (44),
  `test_trading_application` (29), `test_trading_research_concurrency` (2),
  `test_trading_research_worker` (10), `test_trading_scope_guards` (6),
  `test_live_order_guard` (8), `test_product_ai_boundary` (13),
  `test_m3_candidate_catalog` (12), `test_m3_signal_identity` (5),
  `test_docs_layering` (8), `test_repo_layout` (29), `test_function_lengths` (2),
  `test_quality_gate_v2_boundaries` (6). Each module exit 0.
- Repository-wide `ruff check .`, `ruff format --check .`, compileall,
  Python-3.11 AST syntax parsing, `tools/check_layers.py`,
  `tools/check_trading_architecture.py`, `tools/quality_gate.py`, and
  `git diff --check`: exit 0.
- `tools/repin_baselines.py --only inventory`: exit 0, up-to-date; no baseline
  change required and no new source file to register.
- `tools/affected_tests.py --discover`: exit 0. Its transitive list also includes
  broad desktop/assistant consumers; the focused modules above were run locally,
  not the full transitive list. Full regression remains CI-owned.

**Unverified/blocked, not passed:** `test_trading_runtime` ran zero tests because
its real child server could not create a local AF_UNIX socket (`PermissionError:
Operation not permitted`). A narrow escalated test launch failed before executing
with an executor read-only-filesystem bootstrap error; no retry or workaround of
the denied path was attempted. The LOCAL actual-window startup likewise could
not start its independent IPC engine; the owned attempt was interrupted (130),
not counted as successful. No settings/trading UI changed, so a broker-mode UI
startup is not required by M2 section 0.2. No Windows-native check is claimed.
GitNexus impact/detect-changes exit 1 because `.gitnexus/run.cjs` is absent;
textual dependency inspection was used and is not represented as GitNexus success.
PowerShell/prepush is unavailable; its applicable static/syntax checks were run
individually. CI and owner acceptance are not established by this local report.
