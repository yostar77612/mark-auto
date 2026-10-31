# M1-2 verification

Stacked on M1-1 (#118), retaining its safety and history contracts. Offline fake
facade/SDK only; no real account or credential access.

`powershell -File tools/prepush.ps1 -Tests` ran 205 tests. Ruff lint/format,
Python 3.11 syntax of 1010 files and static gate passed. Three retained-handle
fixture failures match main's documented Windows redirector limitation. The
independent engine startup also hit that same PID boundary: launcher 361768,
actual engine 237016. The test-owned LOCAL engine was gracefully shut down through
the existing API; no user process was stopped. No deadline was changed.

The original 12-test `tests.test_trading_runtime` module then passed with the
actual base interpreter, using the same code and assertions:

```powershell
$env:PYTHONPATH="$PWD;$PWD/tests;C:/Users/Mark/Desktop/Mark auto/.venv/Lib/site-packages"
& 'C:/Users/Mark/Desktop/Mark auto/.runtime-sqlite/python.exe' -S -c "import sys,unittest; sys.path[:0]=[r'C:/Users/Mark/Desktop/Mark auto/.worktrees/m1-terminal',r'C:/Users/Mark/Desktop/Mark auto/.worktrees/m1-terminal/tests',r'C:/Users/Mark/Desktop/Mark auto/.venv/Lib/site-packages']; result=unittest.TextTestRunner(verbosity=1).run(unittest.defaultTestLoader.loadTestsFromName('tests.test_trading_runtime')); sys.exit(not result.wasSuccessful())"
```

Provisioned venv, PYTHONPATH=tests/repo, QT_QPA_PLATFORM=offscreen, PYTHONUTF8=1:

| Individual module / command | Exit / count |
|---|---|
| `python -m unittest tests.test_market_terminal_ui` | 0 / 12 |
| `python -m unittest tests.test_symbol_search` | 0 / 2 |
| `python -m unittest tests.test_market_workspace_c5` | 0 / 11 |
| `python -m unittest tests.test_market_watch_ui` | 0 / 7 |
| `python -m unittest tests.test_trading_ui_market_watch` | 0 / 5 |
| `python -m unittest tests.test_desktop_charts` | 0 / 12 |
| `python -m unittest tests.test_lb_b8_drawings` | 0 / 12 |
| `python -m unittest tests.test_lb_b10_paper_orders` | 0 / 22 |
| `python tools/check_layers.py` | 0 / no findings |
| `python tools/check_trading_architecture.py` | 0 / no violations |
| `python -m tools.m1_terminal_snapshot --window --out docs/analysis/m1-terminal` | 0 / 1366×768 and 1920×1080 |

The snapshots use the shared `tools/ui_snapshot.py` renderer. Both whole-window
geometry and accessibility are tested; six columns remain visible and the chart
grows. C5 defaults/file names/tests are unchanged. Compact index mode changes only
the new no-volume chart branch. Default chart, drawings and paper lines retain
their behavior. Graph CRITICAL warnings and component evidence are recorded in
`docs/design/m1-terminal-notes.md`; final merge detection must be complete.

Manual native screen/DPI inspection and broker callbacks/quota remain owner checks.
