# Synthetic local-import example

Every price, volume, session and margin value in this directory is invented demonstration data. These files are not TAIFEX observations, an official calendar, a licensed historical dataset, broker cost advice, or evidence of investment performance.

The 120 normalized one-minute bars cover 2026-01-05 00:45–02:45 UTC for the explicitly named TMF January 2026 contract. `synthetic_calendar.json` covers exactly that invented interval. `synthetic_config.json` uses explicitly assumed commission, tax rounding, slippage and margin; replace them with justified inputs for actual research.

From the repository root:

```sh
python -m quantlab import examples/synthetic_bars.csv --kind synthetic_bars --calendar examples/synthetic_calendar.json --output /tmp/quantlab-data.json
python -m quantlab backtest /tmp/quantlab-data.json --config examples/synthetic_config.json --output /tmp/quantlab-reports
python -m quantlab campaign /tmp/quantlab-data.json --output /tmp/quantlab-campaign
```

Campaign defaults use an offline deterministic fixture generator, illustrative locked thresholds, and no paid or real model calls. Reopening the same completed campaign returns its persisted attempts. Start a new directory only for a genuinely new experiment; reusing the same holdout across directories does not make it unseen.

For a larger invented demo: `python -m quantlab demo --bars 960 --output /tmp/quantlab-demo`.

The separate interface starts with `streamlit run research_app.py`. Choose a local workspace, load data, run and compare backtests, select an immutable strategy, initialize/reconcile a paper account, then start and advance a bounded historical replay. Replay has synthetic next-bar market fills and pinned risk policies, no streaming feed, no live broker, and no intrabar stop/target simulation. Stop blocks further steps without liquidating positions. After a true process restart, explicitly reconcile before resuming. Persisted client IDs and replay plans prevent duplicate simulated fills after an interrupted batch.

Paper replay rejects strategies with protective stop/target parameters rather than ignoring them. Paper overnight daily-loss baselines are not implemented; carried positions can block next-day new intents. This limitation is separate from the backtest engine's explicit settlement simulation.
