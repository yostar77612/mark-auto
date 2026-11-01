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
