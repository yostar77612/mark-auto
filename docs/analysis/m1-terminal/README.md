# M1 terminal offline screenshots

Generated with `python -m tools.m1_terminal_snapshot --out docs/analysis/m1-terminal`.
The tool uses the same renderer and accessibility metrics as `tools/ui_snapshot.py`
with a recording fake facade. No desktop startup, network or credential access.
These images verify layout only and are not evidence of actual broker data.

- [1366 × 768](1366x768.png)
- [1920 × 1080](1920x1080.png)
- [Metrics](metrics.json): both sizes have zero unlabeled inputs and no outer
  scroll area; chart controls and six quote columns remain visible.

Complete shell captures use `python -m tools.m1_terminal_snapshot --window` and
the real TradingWindow with a fake facade and projected logical monitor geometry:

- [Full window 1366 × 768](window-1366x768.png)
- [Full window 1920 × 1080](window-1920x1080.png)
- [Window metrics](window-metrics.json)

Both full-window sizes have no outer scroll area. The shared chart's new
`show_volume=False` index mode removes its redundant internal title and OHLC
header so the mini chart remains readable inside the available panel height.

Real App visual inspection remains pending owner confirmation.
