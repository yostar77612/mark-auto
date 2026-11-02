# U2 manual review and exit preview

Unknown manual submissions now expose the accepted broker-reference candidates,
an explicit selection and two Cancel-default confirmations. Adoption binds the
selected existing broker order; declaring not sent rejects the local request and
releases its reservation only when the backend accepts the latest evidence.
Neither recovery operation resends an order or automatically resumes the book.
The UI can request recovery while reconciliation is blocked by the unknown order;
the existing backend remains responsible for fresh observation validation.

The local unknown marker is discharged only after a matching known backend
RESOLVED request and evidence that the original request is no longer pending.
An empty projection alone never clears it. Requests are tracked independently;
another account's result cannot discharge the original nonce/scope.

Manual flatten now sends PREVIEW_MANUAL with exit_lot_id before presenting a
confirmation. The dialog shows the returned quantity, exact limit, bid/ask and
Taipei quote/expiry times. Confirmation submits the same request and preview ID
through SUBMIT_MANUAL, rather than using FLATTEN to recompute another order.
Expiration, scope/version/selection/capital changes prevent submission. Cancel
consumes the review without submitting. Entry preview and confirmation also show
bid/ask; price_deviation has an explicit Chinese 1% refusal and retry instruction.

## Scope and contract request

- Only desktop presentation, strings, tests and documentation changed. No
  quantlab, domain/application/IPC contract, G3, SDK, budget or timeout edits.
- New LIVE_ORDER_ACTIONS members are ADOPT_MANUAL_ORDER and
  DECLARE_MANUAL_NOT_SENT through the existing MANUAL_ACTIONS union. The exact
  pinned set and all programmatic/widget LIVE refusal checks are retained and
  extended. The quantity/price/scope assertions of the old flatten test now
  cover PREVIEW_MANUAL → confirmed SUBMIT_MANUAL with the same preview identity.
- The existing preview contract requires an explicit proposed quantity. The UI
  proposes min(held,sellable); if another exit already reserves part, the backend
  refuses the oversized proposal. OrderView does not identify each exit's lot,
  so the UI does not invent the remaining unreserved quantity. A follow-up engine
  contract could accept a lot-only exit preview or expose authoritative maximum
  exit quantity. Until then, confirm/finish the existing exit before retrying.
- New strings: phase 65, **2962–2974**, in
  `desktop_app/strings/manual_review.py`. New product modules:
  `manual_recovery.py`, `manual_exit_preview.py` under desktop trading. New test
  modules: `test_u2_manual_recovery_ui.py`, `test_u2_exit_preview_ui.py`.

## Local verification

Shared interpreter: `C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe`;
unit tests use QT_QPA_PLATFORM=offscreen, PYTHONUTF8=1.

- 84 passed in 7.283s: tests.test_u2_manual_recovery_ui,
  tests.test_u2_exit_preview_ui, tests.test_m2_manual_ui,
  tests.test_m2_trading_page, tests.test_m2_guidelines,
  tests.test_sinopac_panel_ui and tests.test_sinopac_window_ui.
- After bounding the candidate selector and hiding its controls outside SIM,
  its six recovery tests passed again in 0.465s. Full candidate identities remain
  in the selection/confirmation; the widget does not expand the small viewport.
- tools/affected_tests.py selected the broader catalog-dependent set. Only the
  relevant modules above ran locally; complete discovery belongs to CI.
- tools/repin_baselines.py --write generated 13 additive catalog values, the
  exact 2975-record count and three module registrations, then verified them.
  Existing stylesheet/observer baselines were current. Baselines are a separate
  commit; no old assertion, text, identity or historical producer pin is relaxed.
- Ruff lint, changed-file format, Python 3.11 compile, layer gate and static
  quality gate passed. Fast prepush has the same unchanged-main M3 Markdown CRLF
  fence formatting failure as U1; its other checks passed, including all 1147
  tracked Python files. U1's normal CI checkout already passed that formatter.

## Native windows and screenshots

The original _run_window path displayed real Windows Qt windows in LOCAL and
BROKER_SIMULATION. Both returned zero, released the research session and cleaned
up owned processes/IPC endpoints. SIM used the real authenticated IPC with one
fake login/logout; no real SDK import, credentials, CA or broker order occurred.
Results: [LOCAL](LOCAL.json), [fake SIM](BROKER_SIMULATION.json).

| Native startup | Small | Large |
| --- | --- | --- |
| LOCAL | [1366×768](LOCAL-1366x768.png) | [1920×1061](LOCAL-1920x1080.png) |
| fake SIM | [1366×768](BROKER_SIMULATION-1366x768.png) | [1920×1061](BROKER_SIMULATION-1920x1080.png) |

The 1920×1080 target is constrained to a 1920×1061 client area by the existing
screen-fit behavior. Exact 1080 client pixels remain a larger-display/owner
check. No font shrinking or screen-fit bypass was introduced.

Feature captures use explicit fake view facts/facade in a native TradingWindow
with the actual trading-page theme. Every screenshot confirmation is cancelled:
two PREVIEW_MANUAL requests and zero submits/adopts/declarations.

| Feature | Small | Large |
| --- | --- | --- |
| Candidate selection | [1366×768](recovery-1366x768.png) | [1920×1061](recovery-1920x1061.png) |
| Adopt confirmation | [capture](adopt-confirm-1366.png) | [capture](adopt-confirm-1920.png) |
| Actual exit preview | [capture](exit-preview-confirm-1366.png) | [capture](exit-preview-confirm-1920.png) |

Captures were visually inspected. Keyboard candidate selection, accessible names,
Cancel defaults, unknown preservation, stale confirmation and LIVE refusals are
covered by the focused tests. Remote checks remain the latest head's CI evidence;
no local result substitutes for a complete green CI attempt.
