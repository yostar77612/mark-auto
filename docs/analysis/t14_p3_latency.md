# T14 P3-10 ? worker latency evidence

Measured 2026-10-19 with `.venv/Scripts/python.exe`, Windows 10 build 19045,
Python 3.13.11; code remains Python 3.11 compatible. Five repeats per phase.

```powershell
.\.venv\Scripts\python.exe tools/bench_worker_latency.py --importtime --json "$env:TEMP/t14_latency_after.json"
```

## Before / after (seconds)

| Measurement | median | min | max |
|---|---:|---:|---:|
| Fresh runtime import, before | 0.090944 | 0.087125 | 0.102267 |
| Fresh runtime import, after | 0.083140 | 0.082384 | 0.085936 |

The only runtime optimization defers `zipfile` into BackupManager._create and
BackupManager._restore. Backup checks, durability, isolation, timeouts and
registrar/operation behavior are unchanged. This 7.80 ms median difference is
an observed import-stage improvement, not proof of end-to-end latency gain.
The ranges and only five samples do not establish a stable performance guarantee.

## Real worker / Walk-forward (measured outside the Codex sandbox)

Controller run, same machine, `bench_worker_latency.py --repeats 5 --importtime`
after the optimisation, quiet machine (seconds):

| Stage | median | min | max |
|---|---:|---:|---:|
| runtime_import (worker child) | 0.0936 | 0.0892 | 0.0993 |
| executor_import | 0.4042 | 0.3978 | 0.4635 |
| compute (run_backtest) | 0.3232 | 0.3182 | 0.3776 |
| result_disk_write | 0.0317 | 0.0295 | 0.0330 |
| subprocess_start | 0.3433 | 0.3277 | 0.3735 |
| total (ui_backtest, incl. polling/cleanup) | 1.5394 | 1.4565 | 1.6528 |
| walk_forward_evaluation (isolated, 960 bars) | 0.4883 | 0.4793 | 0.6017 |

Interpretation: on a quiet machine one isolated Walk-forward evaluation costs
about 0.49 s and a whole operation about 1.5 s; the 3.5-8 s / 8 s figures in the
plan were observed under machine load. Subprocess start (~0.34 s) and importing
the executor (~0.40 s, dominated by Qt/shiboken via the existing registrar) are
the two largest fixed costs. Subprocess isolation is retained; removing the Qt
import from the executor path needs a registrar/UI extraction that affects
public names and goldens and is deferred (recorded in t14_p3_notes.md).
No "before" worker run was taken outside the sandbox; only the import-stage
before/after above is a controlled comparison.

`MEASURED_EVALUATION_SECONDS` in quantlab/wf_estimate.py is set to the
conservative 8.0 s (plan figure under load), not the 0.49 s quiet median, so the
Walk-forward preview label is an upper-bound estimate.

## Harness and interpretation

The opt-in stdlib harness calls the real JobManager.start, which retains the
app's spawn context, launch gate, Windows job tree and real `_job_worker`.
A benchmark-only picklable wrapper measures child entry and runtime import,
profiles executor import, run_backtest and write_json, and times IPC sends.
Disk writes and compute are inclusive function spans; they are not necessarily
disjoint. `total` includes parent polling/cleanup; `launch_call` is not total
child startup. Profiling and the benchmark module startup add overhead, so use
the same harness/interpreter/load for comparisons. It does not run desktop.main
or touch the real workspace. Each job uses the same 960-bar demo dataset and
trend config; each Walk-forward probe is one real isolated full-960-bar
evaluation, not a whole campaign or final holdout consumption.

The fresh-interpreter import samples (subprocess.run) succeeded in both runs,
with PySide6 absent in every runtime import. These are imports only and exclude
interpreter startup. `--importtime` reports the top 15 contributors by self time,
with cumulative time also recorded; a single instrumented import is diagnostic,
not an N=5 worker benchmark. Importing desktop_ui still loads Qt via its existing
registrar. A larger dispatcher/UI extraction is deferred because it affects
patch points/public names and golden compatibility; no behavioral shortcut
was introduced to hide that cost.

## Raw evidence

Reports contain only synthetic benchmark data, durations and fixed errors.
Paths are intentionally omitted; full samples and import contributors follow.

```json
{
  "before": {
    "python": "3.13.11 (tags/v3.13.11:6278944, Dec  5 2025, 16:26:58) [MSC v.1944 64 bit (AMD64)]",
    "platform": "Windows-10-10.0.19045-SP0",
    "bars": 960,
    "repeats": 5,
    "method": "spawn; real JobManager and _job_worker, profiling enabled",
    "samples": [],
    "seconds": {},
    "walk_forward_evaluation_seconds": null,
    "walk_forward_samples": [],
    "runtime_import_seconds": {
      "median": 0.09094359999289736,
      "min": 0.0871247999893967,
      "max": 0.10226670000702143
    },
    "import_samples": [
      {
        "seconds": 0.09064340000622906,
        "qt_loaded": false
      },
      {
        "seconds": 0.09094359999289736,
        "qt_loaded": false
      },
      {
        "seconds": 0.10226670000702143,
        "qt_loaded": false
      },
      {
        "seconds": 0.09096259999205358,
        "qt_loaded": false
      },
      {
        "seconds": 0.0871247999893967,
        "qt_loaded": false
      }
    ],
    "errors": [
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      }
    ],
    "importtime": {
      "quantlab.desktop_runtime": [
        {
          "self_us": 13461,
          "cumulative_us": 112764,
          "module": "quantlab.desktop_runtime"
        },
        {
          "self_us": 4012,
          "cumulative_us": 4012,
          "module": "_ctypes"
        },
        {
          "self_us": 2749,
          "cumulative_us": 10585,
          "module": "inspect"
        },
        {
          "self_us": 2241,
          "cumulative_us": 2241,
          "module": "quantlab"
        },
        {
          "self_us": 2158,
          "cumulative_us": 2158,
          "module": "_socket"
        },
        {
          "self_us": 2123,
          "cumulative_us": 8391,
          "module": "enum"
        },
        {
          "self_us": 2082,
          "cumulative_us": 2082,
          "module": "_hashlib"
        },
        {
          "self_us": 2006,
          "cumulative_us": 2006,
          "module": "_distutils_hack"
        },
        {
          "self_us": 1968,
          "cumulative_us": 3692,
          "module": "encodings"
        },
        {
          "self_us": 1964,
          "cumulative_us": 6795,
          "module": "sysconfig"
        },
        {
          "self_us": 1920,
          "cumulative_us": 6951,
          "module": "site"
        },
        {
          "self_us": 1765,
          "cumulative_us": 5561,
          "module": "zipfile"
        },
        {
          "self_us": 1743,
          "cumulative_us": 5830,
          "module": "socket"
        },
        {
          "self_us": 1679,
          "cumulative_us": 2680,
          "module": "tokenize"
        },
        {
          "self_us": 1639,
          "cumulative_us": 14616,
          "module": "ctypes"
        }
      ],
      "desktop_ui": [
        {
          "self_us": 42239,
          "cumulative_us": 399689,
          "module": "desktop_ui"
        },
        {
          "self_us": 16611,
          "cumulative_us": 47585,
          "module": "quantlab.desktop_runtime"
        },
        {
          "self_us": 12206,
          "cumulative_us": 42680,
          "module": "desktop_market"
        },
        {
          "self_us": 11942,
          "cumulative_us": 18852,
          "module": "shibokensupport.signature.lib.pyi_generator"
        },
        {
          "self_us": 11150,
          "cumulative_us": 12168,
          "module": "desktop_forms"
        },
        {
          "self_us": 10830,
          "cumulative_us": 144342,
          "module": "PySide6.QtWidgets"
        },
        {
          "self_us": 10250,
          "cumulative_us": 10250,
          "module": "PySide6.QtCore"
        },
        {
          "self_us": 9977,
          "cumulative_us": 25594,
          "module": "quantlab.core"
        },
        {
          "self_us": 8845,
          "cumulative_us": 14036,
          "module": "desktop_charts"
        },
        {
          "self_us": 8821,
          "cumulative_us": 10575,
          "module": "shibokensupport.signature.parser"
        },
        {
          "self_us": 6226,
          "cumulative_us": 6226,
          "module": "desktop_strings"
        },
        {
          "self_us": 6193,
          "cumulative_us": 6193,
          "module": "quantlab.market"
        },
        {
          "self_us": 5761,
          "cumulative_us": 61447,
          "module": "shiboken6.Shiboken"
        },
        {
          "self_us": 5199,
          "cumulative_us": 18059,
          "module": "desktop_pages.strategy"
        },
        {
          "self_us": 4956,
          "cumulative_us": 6447,
          "module": "quantlab.reporting"
        }
      ]
    }
  },
  "after": {
    "python": "3.13.11 (tags/v3.13.11:6278944, Dec  5 2025, 16:26:58) [MSC v.1944 64 bit (AMD64)]",
    "platform": "Windows-10-10.0.19045-SP0",
    "bars": 960,
    "repeats": 5,
    "method": "spawn; real JobManager and _job_worker, profiling enabled",
    "samples": [],
    "seconds": {},
    "walk_forward_evaluation_seconds": null,
    "walk_forward_samples": [],
    "runtime_import_seconds": {
      "median": 0.08314009997411631,
      "min": 0.08238400000846013,
      "max": 0.0859364999923855
    },
    "import_samples": [
      {
        "seconds": 0.08263029999216087,
        "qt_loaded": false
      },
      {
        "seconds": 0.08314009997411631,
        "qt_loaded": false
      },
      {
        "seconds": 0.08238400000846013,
        "qt_loaded": false
      },
      {
        "seconds": 0.0859364999923855,
        "qt_loaded": false
      },
      {
        "seconds": 0.08403040000121109,
        "qt_loaded": false
      }
    ],
    "errors": [
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "job_worker",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      },
      {
        "phase": "walk_forward_evaluation",
        "error": "[WinError 5] 存取被拒。",
        "type": "PermissionError"
      }
    ],
    "importtime": {
      "quantlab.desktop_runtime": [
        {
          "self_us": 14167,
          "cumulative_us": 115682,
          "module": "quantlab.desktop_runtime"
        },
        {
          "self_us": 4593,
          "cumulative_us": 4593,
          "module": "_ctypes"
        },
        {
          "self_us": 2818,
          "cumulative_us": 12282,
          "module": "inspect"
        },
        {
          "self_us": 2709,
          "cumulative_us": 2709,
          "module": "_socket"
        },
        {
          "self_us": 2481,
          "cumulative_us": 8862,
          "module": "enum"
        },
        {
          "self_us": 2228,
          "cumulative_us": 2228,
          "module": "_hashlib"
        },
        {
          "self_us": 1950,
          "cumulative_us": 6679,
          "module": "site"
        },
        {
          "self_us": 1931,
          "cumulative_us": 3713,
          "module": "encodings"
        },
        {
          "self_us": 1927,
          "cumulative_us": 3249,
          "module": "pickle"
        },
        {
          "self_us": 1919,
          "cumulative_us": 4467,
          "module": "dis"
        },
        {
          "self_us": 1905,
          "cumulative_us": 6698,
          "module": "socket"
        },
        {
          "self_us": 1857,
          "cumulative_us": 1857,
          "module": "_distutils_hack"
        },
        {
          "self_us": 1854,
          "cumulative_us": 6965,
          "module": "sysconfig"
        },
        {
          "self_us": 1837,
          "cumulative_us": 1906,
          "module": "ast"
        },
        {
          "self_us": 1751,
          "cumulative_us": 3037,
          "module": "tokenize"
        }
      ],
      "desktop_ui": [
        {
          "self_us": 47761,
          "cumulative_us": 427788,
          "module": "desktop_ui"
        },
        {
          "self_us": 16283,
          "cumulative_us": 46196,
          "module": "quantlab.desktop_runtime"
        },
        {
          "self_us": 14251,
          "cumulative_us": 49941,
          "module": "desktop_market"
        },
        {
          "self_us": 13785,
          "cumulative_us": 13785,
          "module": "PySide6.QtCore"
        },
        {
          "self_us": 11463,
          "cumulative_us": 17870,
          "module": "shibokensupport.signature.lib.pyi_generator"
        },
        {
          "self_us": 10998,
          "cumulative_us": 153717,
          "module": "PySide6.QtWidgets"
        },
        {
          "self_us": 10668,
          "cumulative_us": 11554,
          "module": "desktop_forms"
        },
        {
          "self_us": 10383,
          "cumulative_us": 12415,
          "module": "shibokensupport.signature.parser"
        },
        {
          "self_us": 10111,
          "cumulative_us": 16118,
          "module": "desktop_charts"
        },
        {
          "self_us": 9763,
          "cumulative_us": 9763,
          "module": "quantlab.market"
        },
        {
          "self_us": 9182,
          "cumulative_us": 25135,
          "module": "quantlab.core"
        },
        {
          "self_us": 6331,
          "cumulative_us": 6331,
          "module": "desktop_strings"
        },
        {
          "self_us": 5872,
          "cumulative_us": 5872,
          "module": "shibokensupport.signature.mapping"
        },
        {
          "self_us": 5734,
          "cumulative_us": 18041,
          "module": "desktop_pages.strategy"
        },
        {
          "self_us": 5363,
          "cumulative_us": 10543,
          "module": "desktop_pages.compare"
        }
      ]
    }
  }
}
```
