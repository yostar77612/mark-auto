---
name: "check-overfitting-risk"
description: "Assess overfitting warning signs from approved training evidence."
allowed_tools: ["get_backtest_summary", "get_strategy_params", "get_data_quality_summary"]
output_format: "Evidence, warning signs, uncertainty, questions."
---

Read the approved training summary, parameter snapshot and quality counts.
Discuss sample sufficiency, parameter complexity and sensitivity as hypotheses.
Identify which conclusions cannot be supported by the available training evidence.
Keep every assessment qualitative and explain its uncertainty.

AI interpretation may be wrong. Nothing is applied or ordered automatically.
