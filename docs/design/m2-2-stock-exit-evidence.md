# Manual settled-stock evidence, observed 2026-11-01

The pinned, hash-verified Shioaji 1.7.9 `_core.pyi` declares StockPosition
quantity, yd_quantity, direction, cond and financing/collateral fields, but no
general native free-share field. The [official position reference](https://sinotrade.github.io/tutor/accounting/position/)
defines quantity units and yesterday inventory. Neither field alone certifies
sellability. `stock_reserve_summary.available_share` is reservation capacity for
the reserve workflow, not general available-to-sell inventory; see the
[official reserve reference](https://github.com/Sinotrade/Shioaji/blob/master/plugins/shioaji/skills/shioaji/references/RESERVE.md).
No reserve/earmark mutation or CA operation is used.

The [broker's settlement explanation](https://www.sinotrade.com.tw/richclub/invest/guide/stock-order)
describes T+2 settlement and the distinction between selling and receiving cash.
Our existing explicit trading calendar, rather than inferred weekdays, supplies
the two-session count. The [broker's order/inventory guide](https://www.sinotrade.com.tw/ec/eleader1/8896.pdf)
also distinguishes inventory from outstanding successful orders. These sources
do not claim a globally atomic API inventory/free-share certificate.

The owner therefore selected a narrower app-derived rule for the new manual
book, whose genesis requires complete fresh empty-account reconciliation:
only its own persisted cash-long fill tranches, matured under the verified
calendar, may become exit-eligible. Fresh typed positions must exactly match
the owned book, cash/no-financing evidence must be present, and every working
order must be mapped and understood. Pending owned exits are subtracted once
by the existing ExitCoordinator. The source is explicitly app-derived; a
broker rejection remains possible and is handled without resubmission.

Same-day eligibility, outside holdings, pledged/financed stock and missing
dates are not inferred. Cumulative historical fills use their observation
session as a conservative latest possible date. Acquisitions and sale
receivables are included in the same durable fill event, so interruption cannot
release unsettled funds through a missing second append. Automatic strategy
availability and automatic previous-close/OOS rules are unchanged.
