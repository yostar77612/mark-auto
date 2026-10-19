# T14 P3-11 ? backtest scale evidence

Measured 2026-10-19, Windows 10 build 19045, Python 3.13.11, `.venv` interpreter.
Five repeats, builtin trend-v1, demo costs/config, entirely invented data.

```powershell
.\.venv\Scripts\python.exe tools/bench_backtest_scale.py --json "$env:TEMP/t14_scale.json"
```

The existing public generator is reporting.synthetic_dataset (not data.py), with
its existing 10,000-bar cap retained. save_dataset writes the real dataset envelope.
Dataset generation and file serialization are outside the timed run_backtest span;
validation, engine calculation and result construction are included. No timing
assertions are added to the default test suite. This opt-in run exited 0.

| bars | JSON bytes | median seconds | min seconds | max seconds |
|---:|---:|---:|---:|---:|
| 1,000 | 242,030 | 0.068885 | 0.061975 | 0.074254 |
| 10,000 | 2,411,032 | 0.730551 | 0.701665 | 0.826203 |

A linear extrapolation from 10,000 bars to 340,000 bars gives approximately
24.84 seconds per backtest and 81.98 MB decimal JSON.
620 such full-size evaluations would imply 4.28 hours of
compute alone, excluding spawn, journal/fsync, load/hash and contention costs.
These are arithmetic scenarios, not measured engine capacity or a Walk-forward
prediction: folds differ in length, strategies differ, OOS can be skipped and
runtime/memory/max_bars limits still apply. In particular, current Walk-forward
max_bars is bounded at 100,000 and the synthetic generator at 10,000; neither was
raised to run the extrapolated scenario. Do not read it as a supported input size.
Two points cannot establish asymptotic complexity or memory use. Real historical
data, Linux and hosted-runner/fsync measurements remain unverified.

Storage recommendation and hash/migration risks: [storage design](t14_p3_storage_design.md).
Worker isolation overhead and missing evidence: [latency](t14_p3_latency.md).

```json
{
  "python": "3.13.11 (tags/v3.13.11:6278944, Dec  5 2025, 16:26:58) [MSC v.1944 64 bit (AMD64)]",
  "platform": "Windows-10-10.0.19045-SP0",
  "strategy": "trend-v1",
  "repeats": 5,
  "rows": [
    {
      "bars": 1000,
      "bytes": 242030,
      "median": 0.0688848000136204,
      "min": 0.061974800017196685,
      "max": 0.07425409997813404,
      "samples": [
        0.0688848000136204,
        0.07425409997813404,
        0.06518420000793412,
        0.0712391999841202,
        0.061974800017196685
      ]
    },
    {
      "bars": 10000,
      "bytes": 2411032,
      "median": 0.7305509000143502,
      "min": 0.7016648999997415,
      "max": 0.8262031000049319,
      "samples": [
        0.788893899996765,
        0.8262031000049319,
        0.7305509000143502,
        0.7284022999810986,
        0.7016648999997415
      ]
    }
  ]
}
```
