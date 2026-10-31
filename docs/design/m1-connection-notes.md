# M1-1a connection implementation notes

2026-11-01 Asia/Taipei. Merge these decisions into `m1-decisions.md` in the
integration branch. This file records implementation evidence, not real broker
verification.

- Existing partial WatchInstrument, MarketDataSettings, SymbolDirectory and
  market-only facade methods were retained and completed. Existing code had no
  TPEX:/INDEX: conventions (`git grep` found none); use TPEX: and INDEX: as
  specified. Trading Catalog and InstrumentBinding remain unchanged.
- Independent `MarketSession` accepts only reference settings, injected pinned
  SDK module, resolver, clock and directory. Login disables trade reports; it
  never requests CA, account, position, order or accounting methods. SDK calls
  and exceptions stay within the adapter. No real login was attempted.
- `MarketConnection` persists `market_data_v1` alongside existing workspace
  settings through SettingsStore and creates the SDK only in an explicit
  background connect worker. Missing old settings default disabled. Existing
  CONNECT_READ_ONLY is unchanged. Reconnect logs out the old session first.
- The Shioaji skill's CONTRACTS/STREAMING/MARKET_DATA/CONCEPTS references were
  consulted. Contract V2 names are fetched once during directory refresh; names
  are never looked up during search. Cache refresh duration is measured in
  `refresh_seconds`; real full-market latency remains owner verification.
- Stock and ETF codes are retained, warrant/security codes excluded; all IND
  base contracts plus the two fixed fallback indices are included. Info cache
  files use atomic replace and preserve a malformed original on read failure.
- Historical numeric nanosecond timestamps encode Taipei wall-clock values.
  The new boundary attaches Taipei then converts to aware UTC and subtracts
  one minute for right-labelled K bars. Legacy trading converters are unchanged.
- Index subscriptions use QuoteType quote and typed QuoteIdxV1 callbacks; stock
  uses tick. Index quote values do not imply share volume; the index tick's
  internal volume contribution is zero and UI index turnover remains unknown.
- Incoming naive stock/index datetimes are localized explicitly at this market
  boundary. Watch-only DAY/date resolution is display evidence, never supplied
  to any trading calendar or risk/catalogue.
- BrokerPanel keeps existing objectNames and 12 reference fields, adds a
  separate market settings form and keeps trading configuration collapsed.
  New strings are phase 57, order 2900..2908.
- `UiAction`, `UiCommand`, `UiState` impact is CRITICAL (58 transitive/31 direct
  dependents in the original index); `MarketWatchView` CRITICAL (61/32 after
  root index refresh); registry.initialize HIGH (19/6). Changes are appended
  enum members and defaulted DTO fields, tested with old wire payload omission.
  Existing facade, broker and tickstream semantics are preserved.
- Other pre-edit graph results: ShioajiSDKFacade MEDIUM (15/7), RuntimeBundle
  LOW (9/2), BrokerPanel LOW (5/2), tickstream LOW (9/4). Constructor/property
  dispatch and new partial symbols were UNKNOWN; direct rg/source review
  confirmed the runtime, UI and tests. No UNKNOWN result was used as all-clear.
- Local test invocations need elevated execution for normal Windows temporary
  directory ACLs; the ordinary environment created unreadable temp directories.
  This was a test-environment failure, followed by the same tests passing with
  normal access. No assertion was weakened.

Verification at this slice: test_market_session 5 PASS; test_symbol_directory 2
PASS; test_market_connection 4 PASS; test_trading_sdk_facade 11 PASS;
test_shioaji_tick_stream 4 PASS (PYTHONPATH=tests); check_layers 0 findings;
offscreen BrokerPanel construction PASS. Full stage prepush and integrated UI
screenshots are owned by the M1 integration branch. Real account and visual
confirmation remain pending owner verification.
