# M1-3 verification

This branch stacks on M1-2 (#120); all broker evidence is fake SDK/fixture only.
No real credentials, login, CA, accounting or execution operation ran.

Provisioned `.venv/Scripts/python.exe`, PYTHONUTF8=1,
QT_QPA_PLATFORM=offscreen and PYTHONPATH=tests/repo. Modules run individually:

| Command suffix | Exit / tests |
|---|---|
| `-m unittest tests.test_alert_rules` | 0 / 6 (all 12 kinds with subtests) |
| `-m unittest tests.test_alert_service` | 0 / 10 |
| `-m unittest tests.test_alert_ui` | 0 / 4 |
| `-m unittest tests.test_alert_transport` | 0 / 3 |
| `-m unittest tests.test_market_alerts_runtime` | 0 / 11 |
| `-m unittest tests.test_market_alerts_ui` | 0 / 7 |
| `-m unittest tests.test_m1_market_runtime` | 0 / 3 |
| `-m unittest tests.test_market_settings_concurrency` | 0 / 1 |
| `-m unittest tests.test_history_sync` | 0 / 18 |
| `-m unittest tests.test_market_series_transport` | 0 / 8 (unchanged) |
| `tools/check_layers.py` | 0 / no findings |
| `tools/check_trading_architecture.py` | 0 / no violations |
| `-m tools.m1_terminal_snapshot --window --alerts --out docs/analysis/m1-alert-terminal` | 0 / both full-window sizes |

The original 12-test native independent-runtime module also passed with the true
base interpreter, using the same `-S`/explicit dependency paths documented for
M1-2 (replace its worktree path with `m1-alerts`). Original deadlines/PID checks
remain intact. Initial full prepush ran248 tests and failed only on the same
three baseline retained-handle cases and redirector startup PID mismatch, with
one original applicability skip. Ruff lint/format, 3.11 compile and static gate
passed. A final prepush after the concurrent-settings fix is recorded below.

Coverage includes completed-bar counterexamples, Decimal SMA/KD fixtures,
edge/cooldown/rearm, queued/backfilling/stopped suppression, 13:30 heartbeat,
prior-day cache seeds and completion invalidation, all scopes, enabled-only
scanner subscription and unsubscribe-before-logout, local scanner timezone,
atomic persistence, corrupt originals preserved, thirty-day active log with full
original archived, real serialized rule commands and tick-to-alert flow, GUI
responsiveness/FIFO/read coalescing and no historical notification replay.

Snapshots use the shared ui_snapshot renderer. Event times are Taipei, controls
have accessible names, the latest alert appears in status, and clicking an event
focuses the chart. Local notification preference is honored through the existing
research presenter; no network notification is introduced.

Graph refresh indexes the new modules; full detection lists every symbol without
partial/truncated flags. Shared runtime/IPC/DTO/chart warnings remain recorded;
`render_status` is HIGH and new dispatch points have unresolved dynamic-reference
boundaries checked directly. Exact final graph summary accompanies the PR.

Owner checks: true scanner callbacks/latency and market limits, OS desktop toast,
native screen/DPI/visual inspection, sparse real ticks and existing fail-closed
incomplete-minute behavior. Existing safety checks were not relaxed.

Final prepush after the IO-lock regression fix:249 tests in65.770s; exit1 with
only the same3 retained-handle fixture failures,1 redirector startup error and1
original platform applicability skip. Ruff lint/format, 3.11 syntax and static
security gate passed. Both layer gates reran with zero findings. The independent
native runtime12 passed under the true base interpreter; no PID check/timeouts
were changed. A settings-concurrency regression proves both persisted sections
survive simultaneous writes. Remaining Windows host prerequisites are explicitly
not reported as passing. Failed test-owned LOCAL engines were gracefully shut
down via the existing shutdown protocol; no user process was touched.
