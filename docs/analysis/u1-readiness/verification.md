# U1 account readiness guidance

The account list now pairs its accepted three-state signature fact with one short
next step and a keyboard-operated inline `?`. The explanation names the SinoPac
website and signing page, official stock 2890 / near-month TXF simulation test,
approximately one-minute wait and explicit disconnect/reconnect. It contains no
URL or external navigation. Simulation does not require CA. The app's TMF
diagnostic is explained separately from the official test.

CA, market freshness, account reconciliation, simulation readiness and the LIVE
prohibition each retain their existing facts and gain next-step disclosures.
Disclosing instructions emits no command and cannot promote readiness. CA help
remains accessible while its optional fields are collapsed. Polls preserve the
expanded state; removed accounts remove their guidance.

## Validation

- `C:/Users/Mark/Desktop/Mark auto/.venv/Scripts/python.exe -m unittest
  tests.test_u1_readiness_ui tests.test_sinopac_panel_ui
  tests.test_sinopac_window_ui tests.test_m2_guidelines
  tests.test_m2_trading_page tests.test_m2_manual_ui`: 75 passed, 8.006s.
- Focused strings/layers: `tests.test_u1_readiness_ui tests.test_layer_gate
  tests.test_desktop_strings tests.test_catalog_placeholders
  tests.test_glossary_terms`: 41 passed, 4.260s. This includes the final CA-help
  accessibility assertion.
- `tools/affected_tests.py --discover` selected the broad catalog-dependent set;
  only the related modules above ran locally. Full discovery belongs to CI.
- `tools/repin_baselines.py --write`: generated ten additive strings, the exact
  catalog count and two production-file registrations. Verification passed;
  stylesheet and observer baselines were current. An earlier run rolled back
  catalog edits because the new catalog update lacked its required Lane comment;
  the source comment was fixed without changing an assertion.
- Ruff check, changed-file format check, Python 3.11 compilation,
  `tools/check_layers.py` and `tools/quality_gate.py`: passed.
- `powershell -File tools/prepush.ps1`: exit 1 only for an existing CRLF code
  fence in `docs/design/m3-ai-strategy-to-auto-trading.md` (lines 155–157).
  That file matches origin/main; Ruff's diff only changes those fence line
  endings. All 1144 tracked Python files compiled, lint and quality passed.
  The unrelated design document was left intact; CI uses its normal checkout.
- An initial test command included a nonexistent `test_m2_live_gates` module;
  rerunning the actual existing LIVE guards in the 75-test command passed.

## Native startup and captures

The original `_run_window` and real authenticated IPC ran with the Windows Qt
platform. LOCAL and BROKER_SIMULATION both displayed a native TradingWindow,
attached/released the real research session and returned zero. Only the SIM SDK
boundary was fake: one fake login/logout, no real SDK import, no credentials or
orders. All owned processes exited normally and endpoints were removed.
Machine-readable results: [LOCAL](LOCAL.json), [SIM](BROKER_SIMULATION.json).

| Environment | Small | Large |
| --- | --- | --- |
| LOCAL | [1366×768](LOCAL-1366x768.png) | [1920×1061](LOCAL-1920x1080.png) |
| fake SIM | [1366×768](BROKER_SIMULATION-1366x768.png) | [1920×1061](BROKER_SIMULATION-1920x1080.png) |

[Expanded official steps](BROKER_SIMULATION-expanded.png) were activated with
Space in the real window. Captures were visually inspected. The 1920×1080 target
was constrained to 1920×1061 client pixels by the existing screen-fit behavior;
the actual dimensions are recorded in JSON. The settings page scrolls vertically
at both sizes; no horizontal overflow or shortened guidance was introduced.
Exact 1920×1080 client-size acceptance remains for a larger display/owner check.

## Decisions and impact

- Reuse the accepted connection facts, without new DTOs, backend decisions or
  automatic website navigation. Keep official vendor tests and app diagnostics
  distinct. No contract request is needed.
- New copy: `desktop_app/strings/account_readiness.py`, phase 64, orders
  **2952–2961**. New widget module:
  `desktop_app/features/trading/readiness_guidance.py`; new test module:
  `tests/test_u1_readiness_ui.py`.
- GitNexus was rebuilt for this worktree. The first impact used the identical
  e5a5941 snapshot in the engine worktree (broker_panel blob verified equal),
  followed by the local-index check. BrokerPanel MEDIUM: five direct imports,
  including connection composition and UI tests. `_update_accounts` LOW:
  three direct callers, one recorded process family. Constructor UNKNOWN was
  resolved by explicit construction-site search; its zero was not treated as
  evidence of no callers. No HIGH/CRITICAL pre-edit result.
- Final `detect_changes(scope=all)`: 14 indexed symbols, 18 changed files,
  three affected recorded flows, MEDIUM risk, no partial/truncated flag.
  Added widget/test modules are also covered by direct source and focused tests;
  absence from the existing graph does not imply that they are unused.
- This is a read-only UI change: quantlab, G3, LIVE_ORDER_ACTIONS, historical
  assertion logic, SDK versions and acceptance scores remain unchanged.
- Remote CI and merge status are recorded on the PR; local results do not imply
  full CI success or real broker verification.
