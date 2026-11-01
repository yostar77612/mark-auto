# M2-1 connection UI verification

This UI-only slice uses immutable fake connection facts and the real
TradingWindow widgets. It does not start a broker SDK, resolve credentials,
activate a certificate or submit financial operations. The shared runtime is a
separate owner; integrated full discovery, actual LOCAL/SIM startup and remote CI
remain pending until the coordinator runs the combined branch.

## Focused evidence

- 99 focused tests passed in 13.829s: 21 new panel/window tests, retained settings
  and TradingWindow regressions,10 M2-6 tests, the four-page keyboard-help case,
  four DTO/codec cases, centralized styles, architecture boundaries, reviewed
  stylesheet hashes and exact frozen page-service observer equality.
- The new tests first failed on the absent constructor/three-step boundary,
  then passed after implementation. They independently name the four connection
  intents, preserve LOCAL book/selector state while a held request runs, prove a
  GUI heartbeat during that request, and test connection revisions before
  same-book/market-only shortcuts. Refusals and transport failure cannot display
  accepted account selection or leaked vendor details. Certificate selection,
  native Cancel default, nested-dialog stale generation and dirty Decimal fee
  persistence are exercised. An inconsistent production READY DTO is blocked.
  A separate test first failed when discovered book choices changed without an
  engine version increment, then passed after presentation invalidation; the
  accepted LOCAL book, positions and dirty key draft remained unchanged.
- Existing actual Qt enum reconstruction and connection-status tests now target
  the unified form. Alert-kind and painter geometry assertions remain unchanged.
  Old metadata save/restart/readiness coverage remains on typed legacy commands;
  real IPC/engine integration tests were statically checked here and remain in
  coordinator full discovery, not run concurrently with its process suite.
- Ruff and syntax checks pass for touched files. Historical app/market stylesheet
  builders are unchanged. Observer projection comparison is empty for services,
  aliases, state copies and patch points; no historical observer fixture changes.

## Visual and guideline section10 checklist

- [x] One primary save-and-connect action in Settings; optional/advanced fields
  progressively disclosed. Disconnect is danger-role with native Cancel default.
- [x] No inline stylesheet; scoped semantic connection selectors live in theme.py.
- [x] Absent account data has an explanation and a keyboard-accessible return-to-
  connection action, without claiming the broker has zero accounts.
- [x] Exact1366×768 and1920×1080 captures below have horizontal scrollbar maximum0.
  The1366 view uses normal vertical Settings scrolling to reach all four reasons;
  the1920 view displays the whole default workflow. No text was shrunk to fit.
- [x] Connection phases, signed state and reason codes render Chinese text. Masked
  account labels and reference names are data, not leaked native identifiers.
- [x] Named controls have accessible labels; account Space selection, help Space,
  complete plain-text help and Escape close are tested. Help anchors stay in the
  title-right header.

| View |1366×768|1920×1080|
|---|---|---|
| Disconnected/next step | [capture](1366x768-disconnected.png) | [capture](1920x1080-disconnected.png) |
| Masked accounts/four facts | [capture](1366x768-connected.png) | [capture](1920x1080-connected.png) |
| Formal connection, orders disabled | [capture](1366x768-live.png) | [capture](1920x1080-live.png) |
| Explicit permission failure | [capture](1366x768-failure.png) | [capture](1920x1080-failure.png) |

[Complete connection help](connection-help.png) is selectable plain text. Captures
use fake fixtures, including a synthetic masked account, and were visually
inspected. They are not evidence of successful real broker login or CA activation.

## Exact baseline procedure for dependent UI work

Keep source and baseline commits separate. Measure the feature delta before
updating any fixture and preserve the fixed historical source identity.

1. Catalogue: use tools.refactor.split_ui_catalog_check.dump(vars(catalog));
   compare all existing locale/key values, alias mappings and their order first.
   Append only the new phase records and matching locale/lookups/key_order entries.
   Keep source_commit6b78239, aliases and alias_order unchanged. The utility's
   --write-baseline option retains an existing baseline; it does not regenerate it.
   This slice adds exactly72 keys at orders2806–2877, phase62; ordered record total
   becomes2878 because the inherited catalogue contains one historical duplicate.
   The independent record-count assertion is updated exactly, with no range cap.
2. Observer inventory: compare actual inventory() with reviewed_inventory() only
   after its frozen path/line/E6/M1 projections. Use Counter row differences and
   retain every identity/multiplicity. This UI slice's delta is empty; leave both
   page_services_inventory.json and download_auto_import_ui_delta.json untouched.
3. Theme: run the existing exact builder-byte test. Scoped _TRADING_PAGE_QSS does
   not change either historical builder; do not regenerate their hashes.
4. Widget/public-name fixtures: retain frozen historical lists unless the actual
   feature guard observes an authorized addition. Trading-only connection names
   require no update to the historical research widget/public API lists.
5. Inventory section2: register the new UI/text/test modules and note removal of
   obsolete MarketDataPanel. Backend sinopac_contracts.py belongs to the backend
   owner's separate inventory commit. Keep all thresholds unchanged. Window's
   inherited size has a narrow split plan: connection signal/render/receipt logic
   lives in sinopac_ui.py; later context-navigation extraction can reduce the
   remaining orchestration, without moving financial state validation into widgets.
6. Run complete GitNexus detect_changes before every commit. A partial/truncated
   response is not clean; keep the full raw result and verify changed-symbol
   count equals the returned list, then inspect tests and git diff separately.
