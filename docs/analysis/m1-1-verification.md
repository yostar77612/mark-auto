# M1-1 verification

Offline evidence only. No real SDK login, credentials, CA or order operations.
Environment: provisioned `.venv/Scripts/python.exe` (patched SQLite),
`PYTHONUTF8=1`, `QT_QPA_PLATFORM=offscreen`, `PYTHONPATH=<repo>/tests;<repo>`.

| Command | Result |
|---|---|
| `powershell -File tools/prepush.ps1 -Tests` | Exit 1: known unchanged ADR formatting; 3 native retained-grandchild-handle fixture failures in 140 tests. Lint, all 1000 tracked Python files' 3.11 syntax, static gate passed. |
| `.venv/Scripts/python.exe tools/check_layers.py` | Exit 0, no findings |
| `.venv/Scripts/python.exe tools/check_trading_architecture.py` | Exit 0, no violations |
| `.venv/Scripts/python.exe -m unittest tests.test_kline_store` | Exit 0, 9 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_history_sync` | Exit 0, 17 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_market_terminal_service` | Exit 0, 10 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_m1_market_runtime` | Exit 0, 2 tests, actual codec/request dispatch with fake SDK |
| `.venv/Scripts/python.exe -m unittest tests.test_market_session` | Exit 0, 5 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_symbol_directory` | Exit 0, 2 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_market_connection` | Exit 0, 4 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_m1_architecture` | Exit 0, 3 tests |
| `.venv/Scripts/python.exe -m unittest tests.test_trading_architecture` | Exit 0, 8 unchanged tests |
| `.venv/Scripts/python.exe -m unittest tests.test_market_series_transport` | Exit 0, 8 unchanged tests |
| `.venv/Scripts/python.exe -m unittest tests.test_trading_broker_runtime` | Exit 0, 12 unchanged tests |
| `.venv/Scripts/python.exe -m unittest tests.test_trading_ui` | Exit 0, 32 unchanged tests |
| `.venv/Scripts/python.exe -m unittest tests.test_market_watch_ui` | Exit 0, 7 unchanged tests |
| `.venv/Scripts/python.exe -m tools.m1_connection_snapshot` | Exit 0, shared ui_snapshot renderer; form visually inspected at 1366×768 |
| `git diff --check` | Exit 0 |

The native fixture failure is also reproduced at unchanged `origin/main`
`ba597b5` by the independent M1-U worktree. Alternative documented base-interpreter
runs encountered an unrelated installed `tests` package shadowing fixture children.
No assertions, timeout or fixtures were weakened. The known ADR formatting case is
explicitly documented in CONTRIBUTING; that ADR is untouched.

`detect_changes(scope=all, repo=mark-auto)` reported 66 changed symbols from 33
files, one affected flow, MEDIUM aggregate; all 66 listed, neither partial nor
truncated. Pre-edit CRITICAL/HIGH warnings remain applicable independently of the
aggregate and are documented in contracts/decisions. Index refresh was requested
with `analyze --index-only`; no FTS/vector download or root instruction edits.

Required owner checks: real connection permissions/callbacks/reconnection and
quota behavior, measured full-market info latency, native human visual inspection.
