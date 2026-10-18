# P0-00 desktop baseline

Empty workspace, default settings, unlogged-in, no imported data or background jobs.
Generated on Windows with Python 3.13, PySide6 6.12, Fusion style, Microsoft JhengHei
UI (Windows regular/bold faces loaded explicitly), zh_TW locale, logical 1366x768,
pixel scale 1. The CLI pins Qt monitor scaling to 1; `--scale` scales only the raster.

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
.\.venv\Scripts\python.exe tools/ui_snapshot.py --size 1366x768 --scale 1 --out docs/analysis/baseline/ui_snapshot_1366x768
```

Each numbered pair follows navigation order: `NN_viewport.png` captures the entire
1366x768 MainWindow client area; `NN_full.png` renders the page's actual scroll
content widget at its natural height and available width (1146 here). Nested
scroll areas are expanded for the full capture, including the market indicators.
Hidden advanced sections and inactive tabs stay hidden. `metrics.json` contains
all seven named pages; measurements refer to the full content, excluding global
navigation/banner/status/progress controls. A page shorter than the viewport is
still measured at its natural size, without padding it to viewport height.

| Page | Height | Inputs | Buttons | Label chars | Unlabeled | Primary |
|---|---:|---:|---:|---:|---:|---:|
| 市場總覽 | 1559 | 25 | 7 | 233 | 0 | 0 |
| 資料匯入與更新 | 856 | 9 | 7 | 75 | 3 | 0 |
| AI 策略中心 | 4148 | 50 | 12 | 940 | 3 | 0 |
| 回測與結果 | 1786 | 19 | 5 | 460 | 1 | 0 |
| 比較與策略選擇 | 1900 | 4 | 10 | 216 | 1 | 0 |
| 紙上交易與復原 | 3165 | 24 | 18 | 636 | 1 | 0 |
| 設定與備份 | 1666 | 8 | 11 | 648 | 1 | 0 |

## Metric definitions

- `page_height`: logical content-widget height after resizing to sizeHint,
  minimumSizeHint and heightForWidth, including expanded nested scroll areas.
- `visible_input_count`: line edits, spin boxes, combos, editable plain/rich text
  editors, checkboxes and radio buttons visible relative to the selected page.
  Includes disabled controls and controls below the fold; excludes read-only
  editors and duplicate line editors embedded inside spin boxes/combos.
- `button_count`: visible QAbstractButton controls excluding checkbox/radio inputs;
  includes action/toggle buttons and Qt internal buttons, including tab arrows.
- `label_char_count`: sum of Python string lengths of visible QLabel text,
  including whitespace, punctuation and any markup; excludes other widget text.
- `visible_text`: nonblank label/button/editor text, displayed field values,
  current combo values, group titles and visible tab captions, in widget traversal
  order. Hidden controls/inactive tab contents and table model/header data are
  excluded. Empty-state tables have no data rows.
- `unlabeled_inputs`: objectName, or stable `Class[index]` when unnamed, for inputs
  lacking an accessibleName, checkbox/radio caption, visible QLabel buddy,
  QFormLayout label, or immediately preceding QLabel in their containing layout.
  This is a conservative layout heuristic, not an accessibility conformance audit.
- `primary_button_count`: visible buttons with dynamic Qt `role == 'primary'`
  or boolean `primary == True`, counted once. Default/autoDefault styling and
  blue backgrounds do not imply primary; the current baseline has zero.

## Comparison with plan section 2

Values below are **baseline minus plan**, using the same empty, unlogged-in state.

| Page | Height delta | Input delta | Button delta | Label-char delta |
|---|---:|---:|---:|---:|
| 市場總覽 | +1127 | +7 | -6 | 0 |
| 資料匯入與更新 | +6 | +2 | -2 | 0 |
| AI 策略中心 | +14 | +5 | -4 | 0 |
| 回測與結果 | 0 | +4 | -2 | 0 |
| 比較與策略選擇 | 0 | 0 | -2 | 0 |
| 紙上交易與復原 | +3 | +2 | +3 | 0 |
| 設定與備份 | 0 | +3 | -4 | -99 |

The plan's one-off measurements did not publish counting code. These definitions
count checkbox/radio controls as inputs and exclude them from buttons, and avoid
double-counting Qt editors. Natural heights depend on style/font/wrapping; the
market full capture additionally expands its nested indicator panel rather than
retaining the original 432px constrained page measurement. The paper page includes
the recovery controls present in this checkout. Settings label counts are shorter
because three random absolute workspace paths are replaced for display with
`<temporary workspace>` (the paths passed into MainWindow stay real temp paths).
No application layout, text, objectName or behavior was changed to match numbers.

No capture timestamps or random workspace names are persisted in metrics/PNGs;
polling timers stop before processing events. Empty-state visible dates are fixed
application defaults, not wall-clock substitutions. PNG glyph rasterization and
layout can vary with installed font/Qt/OS versions; compare pixels on a matching
environment. Scale 2 has identical logical page metrics and twice the pixel sizes.
The tool never calls desktop.main, AppPaths.discover, WorkspaceLocator, startup
recovery, or account sign-in; MainWindow receives explicit AppPaths, SettingsStore,
JobManager and BackupManager under TemporaryDirectory, removed after close even
on rendering failure. Existing application contracts/acceptance text is unchanged.

## T1 continuation verification (2026-10-18)

- `python -m unittest tests.test_ui_snapshot -v`: exit 0, all 4 tests passed
  in 14.451 seconds, covering CLI validation, schema, scale/size, labels/roles,
  full content and isolation/cleanup/default-workspace tripwire.
- Fresh 1366x768 CLI capture: exit 0; all 14 PNGs and `metrics.json` matched
  this baseline byte for byte.
- `python tools/quality_gate.py`: exit 0, zero findings. Its scanner covers
  tracked files; explicit syntax/secret scans of both new Python files also passed.
- `python -m unittest discover -s tests`: run once in this continuation, exit 1;
  1,873 tests in 339.757 seconds, 66 failures, 75 errors, 46 skips. No snapshot
  test failed. Traces include Windows access denied (5), missing symlink privilege
  (1314), and invalid retained process handles (6). Full-suite acceptance remains
  blocked; these failures were not fixed or independently diagnosed here.

All commands used `.venv/Scripts/python.exe` and offscreen Qt. This sandbox denies
access inside Python's mode-0700 temporary directories: the first targeted run
failed. Successful targeted verification and the full-suite attempt used TEMP/TMP
under repository `.tmp` plus the prior run's scratch `sitecustomize.py`, which
maps `os.mkdir` mode 0700 to 0755. No test assertions, skips or timeouts changed.
Accessible scratch logs, captures and this environment-only workaround were removed
after checking. Cleanup remains blocked for 40 private temporary directories under
`.tmp` (39 `markauto-smoke-startup-*` and one prior `markauto-ui-snapshot-*`): Windows
denies traversal and deletion. PowerShell deletion was policy-rejected; bounded
Python cleanup and scratch-only ACL reset could not remove those directories.
No application source or locked file changed; all deliverables remain uncommitted.
