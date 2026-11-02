# M2-5 engine verification

Scope: account risk, daily preflight and existing stop-new/cancel-entry semantics.
The UI is a separate lane; no desktop_app source or strings are changed.

## Contract and behavior

The first commit declares CHECK_PREFLIGHT and SAVE_ACCOUNT_RISK, the optional
UiCommand.account_risk, UiState.account_risks/preflight and immutable
AccountRiskLimits/AccountRiskView/PreflightView. Defaults are a 3% loss limit,
1000000 TWD order-notional limit and five simultaneous instrument/side scopes.
The latter two defaults are local product decisions because M2 specifies no
numeric default. Saving limits adopts the account, as does any typed strategy
version, including a deleted version. All entry owners then share its limits.

An account mark includes manual, active, retired and closed strategy lots,
actual entry costs and executable liquidation costs through the existing
FeeSchedule. UNKNOWN/CANCEL_PENDING entries still reserve position slots.
Loss is latched for the trading day even without a signal. Resume cannot clear
it, fabricate a baseline or reset virtual capital. Reductions remain legal.

Account baselines accept exact sorted per-account prior-close evidence through
the existing attested evidence interface. A single-account legacy total is
unambiguous; a multi-account total never invents a split. Existing history cannot
be reset to zero by enabling a version. Only a genuinely empty ledger, or the
confirmed same-day SIM book with known canceled zero-fill diagnostic orders,
can seed its initial zero mark. LOCAL day advancement records the prior marks
and collects the next day's preflight as part of the explicit STEP action.

CHECK_PREFLIGHT accepts an account reference, never caller-provided facts. The
runtime reads the current connection owner, generation/revision, selected signed
account, confirmed virtual book, successful current-generation diagnostic,
fresh SHIOAJI quotes, service calendar and complete cached reconciliation facts.
It performs no broker balance, snapshot or refresh query. LOCAL/SIM CA is
NOT_REQUIRED and is never activated. Failed/unknown checks latch that day's
automatic-entry block; later successful checks preserve the original reasons.
The keep-awake reminder is a DTO flag and does not change system power settings.
The runtime rechecks lifecycle, engine/public version and connection owner stamp
under bundle → engine → owner locks before recording the result.

Existing STOP_NEW continues to stop entries and cancel entry orders while
retaining protective exits. LIVE remains hard-disabled at existing entry and
execution boundaries; no production submission path or enabling switch exists.

## Evidence

Relevant selection uses tools/affected_tests.py (168 modules identified). Local
verification runs the changed modules and nearby runtime/manual/LIVE guards;
full discovery is delegated to CI. Individual mutation evidence removes one
guard per fresh process without modifying product files. Exact results and
startup details accompany this report in m2-5-engine-verification.json.

Final focused run: 189/189 in 87.324s (account risk37, baseline36, preflight23,
integration28, strategy management36, existing application29). An informational
20s traceback sampled the existing synthetic-history/calendar setup; execution
continued and passed. It was not a test timeout. Runtime preflight69 also passes.
Previously validated nearby application/session/coordinator57 and existing
manual/recovery/scope/LIVE96 pass. Static quality and layer gates each report0;
Python3.11 tracked syntax reports1104 files with0 failures before final staging.
Prepush exits1 solely on the unchanged main M3 document code-fence CRLF format
noise at line155; lint, syntax and quality checks pass. CI remains authoritative.

Original trading_runtime._run_window checks: LOCAL 5.509s and fake-SIM 3.167s,
both return0, visible TradingWindow, attached/released research, normal owned
host cleanup and endpoint removal. SIM is connected/unallocated; this does not
claim a live automatic strategy account. No real SDK import, credentials or CA.

The initial final-run command omitted explicit embedded-Python module paths;
it was interrupted and replaced with the project-native interpreter plus explicit
root/tests/site-packages paths. No test assertion or timeout was changed.

## Risk and remaining work

GitNexus reports CRITICAL shared DTO/engine/runtime impact; UNKNOWN receiver
edges were confirmed in source. The graph is a navigation aid, not acceptance.
Graph analysis and checks must be repeated on the final committed source before
push. No FTS extension repair or download is performed.

M2-3 supplies completed-bar scheduling, explicit automatic resume, disconnection
recovery and forced exits after this PR merges. M2-7/9 evidence/cost extensions
and all UI remain other lanes. Broker account close evidence still requires the
existing trusted provider; no financial fact is synthesized from an aggregate.
CI status is read from the final PR checks, not inferred from local tests.

Independent review additionally reproduced a SELL amendment bypass: one TMF
entry at25000 fits a250000 notional cap, but changing its price to25001 used
to pass the older stop-risk-only check. Amendments now apply the same account
admission before journal/native amendment. Exact-cap entry and protective-exit
amendments retain their legal behavior. New regression module3/3, nearby
manual/recovery/risk/LIVE96 and three isolated amendment guard mutants pass.
Ruff check/format pass. This raises actual-source killed mutants to227/227.
