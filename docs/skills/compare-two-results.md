---
name: "compare-two-results"
description: "Compare two distinct approved training results using bounded evidence."
allowed_tools: ["compare_results", "get_backtest_summary", "get_strategy_params"]
output_format: "Comparability, observed differences, limitations, questions."
---

Read both approved training summaries and their immutable parameter snapshots.
Check whether assumptions are comparable before discussing the comparison.
Explain that returned deltas are the second result minus the first result.
Describe cost, drawdown and performance differences without prescribing changes.
Identify uncertainties that prevent a reliable ranking.

AI interpretation may be wrong. Nothing is applied or ordered automatically.
