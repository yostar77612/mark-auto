# T13 part A lint decisions

No source cleanup or bulk formatting was performed. `fix = false` and no fix command is used.
The eight G3 paths occupy `exclude` exactly; additional path exclusions are in
`extend-exclude`. The entire frozen archives/ tree (legacy_autotrading and legacy_create_env_app) remains under the existing security gate,
but is excluded from Ruff. Fixtures, user-local inputs and generated/build/runtime
output are excluded. `saved_candidate_pool.py` is excluded in full: measured formatter
output rewrites producer literals, so all its bytes and selection logic are preserved.

## Formatter measurement

Ruff 0.16.10 `format --diff --line-length N` on desktop_ui.py,
desktop_chatgpt_ui.py, desktop_market.py, quantlab/paper.py,
quantlab/market_history.py, tools/quality_gate.py, packaging/wait_for_gates.py,
tests/test_core_shards.py, tests/test_packaging.py, tests/test_quality_gate.py,
and quantlab/saved_candidate_pool.py (7,166 lines): median 63, p90 112, p95 132.
Added + removed diff lines (excluding headers): 100 = 12,894; 120 = 11,700;
160 = 10,464. All 11 files would change. Choose 160, the least churn of the
measured widths. The producer file was measurement-only and is now excluded.

## Rules

Select E402, E711/E712/E713/E714/E721/E722, E9 and F. This checks import placement,
comparison/type mistakes, bare except, syntax and Pyflakes errors without requiring
semantic cleanup. E401/E701/E702 are omitted as formatting debt for part B;
E731/E741 naming/lambda rewrites are outside pure formatting. No global ignores.
Per-file ignores below are exact observed file/code pairs, with no wildcard suppression.
F401 preserves public re-exports (including desktop_ui/desktop_pages), import-time
initialization/dependency probes and existing test fixtures. F841 preserves evaluation
and exception bindings. E402 preserves environment/bootstrap-before-import order.
F811 preserves the existing test class setup override; changing it is behavioral work.
The selected rules still reject new errors in other files and all unignored codes.

| File | Ignored rules | Reason |
| --- | --- | --- |
| `desktop.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_chatgpt_ui.py` | E402 | preserve bootstrap/environment import order |
| `desktop_forms.py` | E402 | preserve bootstrap/environment import order |
| `desktop_market.py` | F401, F841 | preserve imports/re-exports and initialization; preserve evaluated unused/exception bindings |
| `desktop_pages/backtest.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_pages/compare.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_pages/data.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_pages/paper.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_pages/strategy.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_pages/views.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_pages/wf_wizard.py` | F841 | preserve evaluated unused/exception bindings |
| `desktop_pages/widgets.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_presentation.py` | E402 | preserve bootstrap/environment import order |
| `desktop_recovery_smoke.py` | F401 | preserve imports/re-exports and initialization |
| `desktop_ui.py` | E402, F401, F841 | preserve bootstrap/environment import order; preserve imports/re-exports and initialization; preserve evaluated unused/exception bindings |
| `packaging/validate_tls.py` | E402 | preserve bootstrap/environment import order |
| `quantlab/__main__.py` | F401 | preserve imports/re-exports and initialization |
| `quantlab/analysis_contracts.py` | E402 | preserve bootstrap/environment import order |
| `quantlab/analysis_recovery.py` | E402 | preserve bootstrap/environment import order |
| `quantlab/chart_data.py` | E402 | preserve bootstrap/environment import order |
| `quantlab/desktop_errors.py` | F401 | preserve imports/re-exports and initialization |
| `quantlab/desktop_runtime.py` | F401 | preserve imports/re-exports and initialization |
| `quantlab/market_history.py` | E402, F401 | preserve bootstrap/environment import order; preserve imports/re-exports and initialization |
| `quantlab/paper.py` | F401 | preserve imports/re-exports and initialization |
| `quantlab/research_analysis.py` | F401 | preserve imports/re-exports and initialization |
| `quantlab/walk_forward.py` | F401 | preserve imports/re-exports and initialization |
| `research_app.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_analysis_recovery_integration.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_analysis_recovery_ui.py` | E402 | preserve bootstrap/environment import order |
| `tests/test_application_icon.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_backtest_presentation.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_baseline_download.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_candidate_presentation.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_chatgpt_auth.py` | E402, F841 | preserve bootstrap/environment import order; preserve evaluated unused/exception bindings |
| `tests/test_chatgpt_plan.py` | F841 | preserve evaluated unused/exception bindings |
| `tests/test_chatgpt_research.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_chatgpt_windows.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_compare_table.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_data.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_desktop_analysis.py` | F401, F841 | preserve imports/re-exports and initialization; preserve evaluated unused/exception bindings |
| `tests/test_desktop_chatgpt_integration.py` | F401, F841 | preserve imports/re-exports and initialization; preserve evaluated unused/exception bindings |
| `tests/test_desktop_chatgpt_ui.py` | F841 | preserve evaluated unused/exception bindings |
| `tests/test_desktop_market.py` | E402 | preserve bootstrap/environment import order |
| `tests/test_desktop_market_integration.py` | E402, F401 | preserve bootstrap/environment import order; preserve imports/re-exports and initialization |
| `tests/test_desktop_saved_candidate_pool.py` | E402 | preserve bootstrap/environment import order |
| `tests/test_desktop_smoke_terminal.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_desktop_tls_smoke.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_desktop_ui_polish_a.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_desktop_ui_polish_b.py` | F401, F841 | preserve imports/re-exports and initialization; preserve evaluated unused/exception bindings |
| `tests/test_desktop_walk_forward.py` | E402, F401 | preserve bootstrap/environment import order; preserve imports/re-exports and initialization |
| `tests/test_desktop_walk_forward_terminal.py` | E402 | preserve bootstrap/environment import order |
| `tests/test_help_reachability.py` | F841 | preserve evaluated unused/exception bindings |
| `tests/test_indicators.py` | E402 | preserve bootstrap/environment import order |
| `tests/test_market.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_market_history.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_market_history_ui.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_notice_collector.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_paper_replay_policy.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_paper_replay_wal.py` | F811 | preserve existing setup override |
| `tests/test_performance_metrics.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_qt_licenses.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_real_ai_validation.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_recovery_frozen_smoke.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_restart_availability_contract.py` | E402 | preserve bootstrap/environment import order |
| `tests/test_saved_candidate_pool.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_settings_sections.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_strategy_tabs.py` | F401, F841 | preserve imports/re-exports and initialization; preserve evaluated unused/exception bindings |
| `tests/test_t9_onboarding.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_test_group.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_token_format_producer_profile.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_walk_forward.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_walk_forward_initialization.py` | F401 | preserve imports/re-exports and initialization |
| `tests/test_windows_recovery_feasibility.py` | E402 | preserve bootstrap/environment import order |
| `tools/diagnose_paper_replay.py` | E402 | preserve bootstrap/environment import order |
| `tools/diagnose_research_phases.py` | E402 | preserve bootstrap/environment import order |
| `tools/install_desktop_auth.py` | E402 | preserve bootstrap/environment import order |
| `tools/validate_core_shards.py` | E402 | preserve bootstrap/environment import order |
| `tools/validate_real_ai.py` | F401 | preserve imports/re-exports and initialization |

## CI and verification boundaries

The dedicated three-minute Ubuntu Ruff job uses the unchanged hash lock; a separate
audit matrix row audits its resolved runtime with the existing strict pip-audit step.
The Windows coverage aggregate requires both offline and Ruff success; release
publication requires named Ruff and Ruff audit jobs and every returned job success.
No offline matrix, test group, assertion, suite timeout or publication criterion is removed.
Part A deliberately leaves `ruff format --check .` failing on existing formatting debt;
part B must format eligible sources before this new CI enforcement can pass.
GitNexus file impact was UNKNOWN; direct workflow/test and release-caller inspection
confirmed these paths. Graph refresh attempted; no graph result waives validation.

Ruff 0.16.10 full format-check diagnostics panic while rendering existing CRLF/Unicode
format debt on Windows (exit 101, annotation range beyond buffer). Set concise
output to preserve usable checks without changing the pinned binary or source bytes.

## Part A validation

- `python -m unittest tests.test_ruff_config -v`: 7 passed in 0.025 s, exit 0;
  no network, subprocess, or Ruff execution in these tests.
- Focused changed/static workflow classes plus tests.test_quality_gate: 57 tests,
  one pre-existing platform skip, exit 0 (6.815 s). The initial direct run hit
  known sandbox tempfile ACL errors; the passing run used an execution-only
  os.mkdir shim for mode 0700 under the OS temp directory, preserving inherited
  ACLs. No test file, assertion or skip condition was changed for this shim.
- Additional 11 workflow-inspecting tests: passed, exit 0 (0.037 s).
- `python tools/quality_gate.py`: zero findings, exit 0.
- `ruff check .`: all checks passed, exit 0.
- `ruff format --check tests/test_ruff_config.py`: exit 0.
- `ruff format --check .`: exit 1, 269 files need formatting and 30 already
  formatted. Expected part B debt; no source formatting was applied.
- `py -3.11` UTF-8-sig compile: 316 tracked/new Python files passed.
- `git diff --check`: exit 0. G3 eight sources, saved_candidate_pool.py and the
  immutable optimization plan have empty diffs. `git ls-files --eol` shows LF
  Python attributes; unchanged existing CRLF working bytes stay intact until
  part B/fresh checkout. The untracked Ruff lock also has text/eol=lf attributes.
- Full suite, remote CI and live dependency audit remain controller-owned;
  no network installation/audit was attempted. Graph refresh failed with EPERM.


## T13 part B verification

Bulk formatting uses Ruff 0.16.10 and retains identical Python ASTs against
HEAD. The new stdlib verifier checks tracked and project-untracked changes,
rejects locked paths, deletions and changes outside Python or the explicit
manifest allowlist. New verifier/test modules have no base blob and are parsed;
they are reported separately from the existing-file AST comparison count.
The manifest lists its own bookkeeping files as well as regenerated goldens.

`MainWindow` expanded from 394 to 471 lines; `_reduce` expanded to 81 lines.
Their original source blocks are retained inside `fmt: off/on` boundaries to
preserve both the exact AST and the existing 400/80 limits. Extraction would
change the AST, so no extraction or budget relaxation was made. All other page
classes remain under 500 lines; before/after counts are in the golden manifest.
The full `saved_candidate_pool.py` remains excluded and byte-identical, as do
the eight G3 files. Two pre-existing lint findings missed in Part A receive
specific inline annotations: F401 in test_repo_layout.py and F841 in
test_docs_layering.py. These change comments only, preserving all assertions.

The UI registry golden was regenerated from the real isolated offline exercise;
current and archived dispatcher outputs are equal. Its 31 changed keys derive
from indicators.py, research_analysis.py, manual_exchange.py and walk_forward.py.
Every key, old/new value, source and verification is recorded in the manifest.
No locked input or pinned producer-profile hash changes. Walk-forward source
hashes and analysis implementation hashes are otherwise computed dynamically;
no additional fixed source expectations were found by the source-hash audit.

GitNexus impact covered all formatter targets. desktop_strings.py was CRITICAL
(32 direct dependents); quantlab/desktop_runtime.py was HIGH (17). MainWindow
was MEDIUM (six direct dependents). Unresolved callers were supplemented by
tracked-source text checks. The existing index is stale; refresh was attempted
but initial sandbox child-process creation returned EPERM. A retry with heap
respawning disabled rebuilt the local graph, then registry registration failed
because another checkout already owns the mark-auto alias. No graph result is treated
as evidence of semantic equivalence; the independent AST check is required.

The pre-existing index has one mixed-EOL blob, tests/test_desktop_paper_exports.py;
its working file is now LF. The index is left unstaged for the controller.
Existing working-copy CRLF remains only in
excluded frozen archive/G3/producer files: normalizing these would violate the
byte-preservation requirement. All reformatted sources have LF.
The full suite is reserved for the controller outside the sandbox, per the
explicit task instruction; focused tests and the static gate run here.
