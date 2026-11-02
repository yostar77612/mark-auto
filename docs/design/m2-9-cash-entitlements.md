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
Neither bucket finances entries; existing static-allocation admission is not a
reinvestment or cash-liquidity ledger. Short-side distribution obligations are
outside this slice and fail closed at event crossings.

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
