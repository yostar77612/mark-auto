# T16 part A decisions

- P3-03 is a pure presentation mapping in desktop_chatgpt_states.py. Fixed codes
  map to four outcomes; unknown values are generic_failure without inspecting
  exception prose. Quota/rate-limit codes offer no retry-now action; credential
  expiry offers the existing sign-in flow with explicit reauthorization intent.
- Refresh results/errors, local panel failures and subscription campaign notices
  use catalog copy. Campaign receipt status is examined because provider failure
  can be returned in a successful worker packet. No failed receipt is called a
  successful inference. The worker only adds sanitized error_code metadata.
- P3-07 uses one shell-level JobProgress for all four job views. It preserves
  cancel_job and progress/cancel aliases, uses allowlisted stage labels, and
  shows numeric finite progress only (clamped, bool excluded). Unknown progress
  is indeterminate. The existing freeze/recover/cancel path is unchanged.
- JobFeedback owns duplicate-terminal suppression per submitted ID. A click is
  not a terminal result: cancellation/finish races use the manager's first
  authoritative terminal packet. Consumed quota is explicitly not refunded.
- MainWindow: 393 lines (limit 400); ChatGPTConnectionPanel: 421 (limit 500).
  Seven-page metrics are byte-identical and all 14 baseline PNGs pixel-identical
  under tools/ui_snapshot.py with the existing test-only sandbox ACL/vault shim.
  ObjectName inventory is identical; no baseline or name-fixture edits needed.
- G3 and optimization-plan diffs must remain empty. No timeout constants,
  cancellation engine, fail-closed validation, quotas, OOS or trading changes.
- Real-account inference is environment-blocked: this is the user's own
  operation. No real credentials, network requests or quota were used here.
- GitNexus pre-edit: shared ui_text catalog CRITICAL (269 direct users, 54
  processes); start_job/_busy HIGH (startup, polling and close flows). Only
  additive catalog/presentation wiring changed. UNKNOWN dynamic Qt callers were
  confirmed by direct source/test searches. Refresh attempt failed with sandbox
  spawn EPERM. Stale-index detect_changes reports 28 symbols/3 affected flows,
  medium risk, no partial/truncated flag; it cannot establish new-module coverage
  and is not claimed as a fresh whole-graph check.
- Verification details are recorded below after final focused checks. The full
  existing suite is controller-owned outside sandbox, as explicitly instructed.


## Final verification

- Focused offscreen unittest run: 55 tests, 8.918 seconds, zero skips, exit 0.
  Includes test_t16_presentation (15 new tests), test_job_stages, test_import_graph,
  test_no_hardcoded_ui_text, test_no_inline_stylesheet,
  test_desktop_ui_p0_correctness, test_primary_sign_in_host, the existing five
  saved-login/refresh/join/cancel tests, PageBoundaryTests and PageSnapshotTests.
  Existing sandbox_ui confines empty fixture ACL/vault setup; no real profile is
  touched. Slowest new test: 0.418 seconds; no sleeps or network.
- All 64 P0-05 error codes resolve to one of the four states; injected refresh
  errors, fake provider failures and receipt-based worker results are covered.
  All eight stage codes plus unknown values, four job kinds, both progress modes,
  clamp/invalid numeric values, stale packets, repeated cancellation, authoritative
  finish after cancel and cancel-after-complete are covered.
- Cancellation still abandons a queued sign-in in the joined-worker gap. Fixed
  import context notices remain in the status line alongside the shared stage.
  Existing P0 panel expectations now assert the exact outcome text and absence
  of diagnostic codes; existing fixed-code redacted-log assertions remain intact.
- `.venv/Scripts/ruff.exe check`: exit 0. `ruff format --check`: exit 0,
  326 files already formatted. `tools/quality_gate.py`: exit 0, zero findings.
- `py -3.11` compiles all 335 tracked/new Python files read as utf-8-sig: exit 0.
  No generated compile files or debug print calls were added. `git diff --check`:
  exit 0. G3 files and optimization plan have empty diffs.
- Runtime AST is identical to HEAD after removing only the added fixed error-code
  import/packet field, confirming no timeout or cancellation-engine changes.
- Default snapshot metrics JSON is byte-identical; all seven full-page and seven
  viewport PNGs are pixel-identical. Existing exact snapshot assertions pass.
  Widget objectName set is exactly the existing fixture; no additive entries.
- All changes remain uncommitted. Full-suite execution remains assigned to the
  outside-sandbox controller; real-account inference remains user-operated and
  environment-blocked. No acceptance score increase is claimed.
