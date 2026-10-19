---
name: "interpret-backtest"
description: "Explain a saved training backtest and the limitations of its assumptions."
allowed_tools: ["get_backtest_summary", "get_strategy_params"]
output_format: "Evidence, interpretation, limitations, questions."
---

Read the approved training summary and immutable strategy parameters.
Explain the observed performance, costs and drawdown using the returned evidence.
Separate observations from hypotheses and identify missing evidence.
Keep conclusions specific to the supplied training result.

AI interpretation may be wrong. Nothing is applied or ordered automatically.
