# M2-1 backend verification

This slice implements reference-only explicit connection, account discovery,
selection/CAS, shared callbacks/subscriptions, M1 session adoption, generated
resources, optional CA references and stable host routing. It does not establish
real broker readiness or enable order submission/automatic strategy cycles.

Focused fake tests cover inert startup, one native login/logout, masked stable
aliases, accepted selection persistence, stale intent rejection, timeout/late
result rejection, adoption failure cleanup, optional fake CA, immutable factory
environment, callback isolation, shared quote leases, resource provenance and
exact calendar boundaries. In-process integration uses real runtime bundles and
server request dispatch, preserving LOCAL money/book fields and requiring an
explicit SIM account navigation. It verifies logout ordering and unknown
cleanup retry barriers. No child engine/full discovery is part of this evidence.

The coordinator owns complete suites, real window/IPC fake startup, push, PR and
remote CI. These remain separate gates; no remote-green/full-suite claim is made
by this focused backend handoff. Fake tests use no installed/imported SDK,
real credentials, real certificate activation or broker orders.

Focused validation: 132 tests passed in 26.296s, covering all new backend modules
plus existing adapters, M1 market/alerts, context navigation/CLI, metadata-only
registry/cleanup and strict trading architecture tests. Log:
`.tmp-m2-backend-final-focused.log`. A final protocol capability addition then
passed 10 targeted metadata/navigation tests in 0.031s
(`.tmp-m2-port-focused.log`). Ruff check and formatting pass for changed Python
files. Final integration cases include unknown legacy logout refusal on retry.

Precommit graph refresh: 19,953 nodes and 640 reported flows. Complete detection
reported 130 changed symbols /29 files /608 affected flows with CRITICAL risk and no
partial/truncated flags. Existing desktop.py parse_args has one empty UID;
source/CLI tests cover it independently. Absent graph flows are not treated as
unused code; index candidate/flow caps remain explicit limitations.

Documentation and repository-layout checks passed 37 tests in 2.075s. Static
quality gate reports zero findings. Provisioned Python 3.11 compilation passed.
Module registration is a separate precise inventory commit; original test
assertions, historical producer fixtures and protected files are unchanged.

## Resource authorities and coverage

- [TWSE annual schedule](https://www.twse.com.tw/rwd/zh/holidaySchedule/holidaySchedule?date=20260101&response=json)
  and [TAIFEX calendar](https://www.taifex.com.tw/file/taifex/CHINESE/4/2026Calendar.pdf).
- [TAIFEX July10 closure](https://www.taifex.com.tw/cht/11/newsDetail?idx=17137&newsType=1).
  Annual 243 scheduled candidates become 242 after this known override. This does
  not claim exhaustive unscheduled closures or actual exchange-open evidence.
- [TMF specifications](https://www.taifex.com.tw/cht/2/tMF): the application
  common manual window 09:00–before 13:30 deliberately narrows full TMF hours.
- Calendar positive ISO-date lines with trailing LF hash:
  d3c732424aec69876919d1ead875db629ccc10348d146414014ba1727811c96c.
  Coverage ends 2026-12-31; no usable official 2027 data was acquired.
- [Public ISIN classification](https://isin.twse.com.tw/isin/e_C_public.jsp?strMode=2)
  observed 2026-11-01: full 10,186,180 byte BIG5 response, SHA256
  de68b53f834f4b17dab7a9125f932c4a270c202ec9deed7e672d564ddf170e54.
  Offline parsing of those exact bytes confirmed 2330/TW0002330008/ESVUFR and
  source publication 2026-11-01. This public-data check is not broker login.
- [TAIFEX margin table](https://www.taifex.com.tw/cht/5/indexMarging): TMF initial
  35050 TWD, update 2026-08-12, independently captured by the coordinator. It is
  exchange reference data; estimated fees and margin do not become broker cash.

CA simulation applicability follows official documentation only. Owner real-SIM
testing remains outstanding; no credential store or CA was accessed by an agent.

## M2-1 connection UI verification

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

## Post-review direct startup and LIVE CA corrections

Explicit profile-free broker startup now reuses a registered unified alias's
stable environment host; it does not create another UNCONFIGURED book. Legacy
unregistered aliases keep their original fallback. The metadata regression was
RED for both SIM and LIVE before correction; three metadata cases then passed
in 0.072s without Qt or host startup.

LIVE unified CA requests are refused at the command owner and independently at
the executor before password/native activation. Existing production_orders_disabled
guidance is reused for disabled path/picker/reference/activation controls and
formal-readonly status/tooltips. No catalogue keys/order changed. The optional
fake SIM CA test remains intact. Both new backend/widget cases were RED first;
the updated fake/small-widget/metadata group passed23 tests in0.558s. BrokerPanel
remains292 lines; legacy CA behavior is unchanged.

These are new source changes after integrated90bdda8. Prior96 focused results
remain attributed to that earlier source, not relabeled as updated verification.
Full/startup/CI remain coordinator-owned. Updated1366/1920 LIVE-only captures
will be recorded against the separate new source commit; other scenes are kept.

Graph chronology is explicit in m2-decisions: the documentation merge used clean
staged evidence while all-scope still had an empty UID. Offline forced rebuild
restored identities and exact committed doc comparison was completed afterward;
that retrospective check is not claimed as precommit. Separate source commit
requires complete all/staged detection with zero empty IDs and no truncation.
