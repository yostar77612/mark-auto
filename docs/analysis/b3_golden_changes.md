# B3 golden hash changes

Adding ATR, SuperTrend, SAR, OBV and the moving-average channel to `quantlab/indicators.py` changes that file's
source hash. The analysis operations (`ui_analysis_preview`, `ui_analysis_read`, `ui_analysis_reconcile`,
`ui_analysis_run`) bind the implementation hash of `indicators.py`, so 23 leaves of
`tests/fixtures/ui_operations_golden.json` (analysis ids and the implementation hash entries derived from it)
were regenerated with the real isolated exercise, exactly as in T13. Every changed leaf is a SHA-256 value; no
non-hash value changed, and the outputs of the seven pre-existing indicators are unchanged (existing indicator
tests pass untouched).
