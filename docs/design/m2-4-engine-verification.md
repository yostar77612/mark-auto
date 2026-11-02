# M2-4 engine verification

Scope: typed strategy management, D6 product limits, isolated capital/risk,
whole-lot sizing and D10 near-month resolution. Desktop source/strings, G3,
BROKER_SDK_VERSION, PROJECT_STATE and FeeSchedule implementation are unchanged.

## Contract and implementation

First commit `e0befa9` defines the DTO/UiAction/error contract. The append-only
contract in IMPLEMENTATION_CONTRACTS documents final fields and defaults.
New files are the two test modules and this verification report/JSON; there are
no new product modules or layer rules. Existing StrategyForm and the legacy
research fingerprint material remain unchanged. Typed execution parameters join
only their own new research fingerprints; new versions require fresh evidence.

## Local checks

Shared interpreter/tool prefix: `C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/`.
Native Windows launch prefix: `.runtime-sqlite/python.exe -S`, adding this
worktree, its tests, and shared `.venv/Lib/site-packages` to sys.path.
Environment: `QT_QPA_PLATFORM=offscreen`, `PYTHONUTF8=1`.

- `python tools/affected_tests.py --list --quiet`: exit0, selected161 modules;
  engine-focused modules below executed locally; full discovery is reserved for CI.
- `python -m unittest discover -s tests -p test_m2_strategy_domain.py`:22 pass.
- `python -m unittest discover -s tests -p test_m2_strategy_management.py`:36 pass.
- Existing trading domain44, application29, selected coordinator/LIVE/draft/scope/
  execution-environment/valuation41 all pass.
- Independent lifecycle/performance/price43, runtime/UI44, research worker10,
  research concurrency2 pass. An initial concurrency case correctly refused a
  producer profile while files changed; stable-source rerun2/2 passes. Original
  failure retained; no assertion or timeout was changed.
- Ruff check/format of changed Python files pass; compileall passes.
- `python tools/quality_gate.py` and `python tools/check_layers.py`: exit0.
- `powershell -File tools/prepush.ps1`: exit1 solely on the unchanged main M3
  specification Python code-fence CRLF formatting at line155. Lint,1101-file
  Python3.11 syntax scan and quality pass. Exact M3 doc blob equals origin/main
  SHA1 `d2888a735e2528fdc4984f5b34f29fa1abd4e5bf`; no unrelated normalization.
- `python tools/repin_baselines.py`: exit0, all baselines current; no baseline
  mutation or separate empty baseline commit is required.

Real original `trading_runtime._run_window` checks: LOCAL returns0 in7.406s;
fake-SIM returns0 in4.812s. Both show a real TradingWindow and release research.
LOCAL exact-owned child exits normally0; SIM own authenticated server joins0,
fake login/logout once, endpoints removed. SIM is connected but unallocated,
not a claim of a running strategy account. No actual credentials/SDK/CA/order.

## Guard mutation evidence

[Machine-readable results](m2-4-engine-verification.json): domain30/30 and
management27/27 killed. Each runner compiles a single source replacement into a
fresh subprocess without rewriting product files. Domain JSON lists each mutant
and independently targeted test. Management cases include typed payloads,
research prerequisite/integrity, allocation cap, both fill-history sources,
pending-delete lock, full-lot and amount/count constraints, per-strategy cash,
pending risk, cumulative loss isolation and profit ceiling.

GitNexus pre-edit warns CRITICAL for shared UiAction/UiCommand/StrategyView/
UiState and HIGH for StrategyRecord/submit. UNKNOWN snapshot callers were
confirmed from LocalFacade source. Final detect_changes(all) reports85 changed
symbols/603 affected flows, riskCRITICAL, with no partial/truncated flag. This
broad graph result does not replace source review/tests. Rebuild completed;
FTS checkpoint failed/degraded; no extension download or repair attempted.

## Remaining scope and assumptions

M2-5 risk/preflight and M2-3 realtime scheduling/retry are separate follow-on PRs.
M2-7 supplies minute research evidence through existing ResearchResult; this PR
does not implement it or fabricate passing evidence. Missing TMF margin uses a
labelled50000TWD local conservative assumption. Stock entry amount includes the
existing FeeSchedule fees/slippage. One active account/instrument owner remains
for M3; multiple distinct instruments can be active within each account ceiling.
Legacy strategy forms remain readable/executable under their original contract;
new UI uses CREATE_TYPED_STRATEGY for M2 restrictions. Disable affects new
strategy decisions; existing lots keep their protection and history.

CI is pending at report creation. Consult the PR checks on the final head for
acceptance; local checks above are not a claim that full CI passed.


Independent review fixes before final CI: account allocation enforcement now
covers typed and legacy entry points after any typed version adopts the M2
contract for an account (the marker survives disabling/deletion). Pure legacy
ledgers retain their original margin-reuse fixture behavior. JSON revisions copy
rules while rebuilding the explicit form/interval/current cost/risk envelope,
and require new evidence. Margin provenance follows the resolved contract; a
blocked near-month reference is UNKNOWN. Six new regression tests pass and seven
additional individual mutants are killed. Existing double-futures margin test
and full coordinator module pass13/13 after this correction.
