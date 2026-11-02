# M3-3 驗證報告

## 範圍與狀態

五個應用模組與五個測試模組完成；只依賴已合併 M3-1。全程使用合成 TRAINING fixture／fake ports，沒有券商登入、外部行情或真實證據讀取。
介面 commit：`183b114`。完整測試交給 CI；此處不宣稱 full-suite 或實際桌面驗收。

## 已完成的 focused 驗證

使用 `/workspace/scratch/0551d866db25/markauto-m3/tools-venv/bin/python`（Python 3.12.14），Qt 測試設 `QT_QPA_PLATFORM=offscreen`。

- `python -m unittest tests.test_m3_candidate_intake tests.test_m3_prefix_consistency tests.test_m3_signal_research tests.test_m3_promotion_service tests.test_m3_stage_matrix`：108 tests，exit 0。
- 前綴測試包含 4,320 次比較：五個家族、AST、兩組參數、日線／PER_SESSION、BOTH／LONG_ONLY。
- Ruff 0.16.10 `check` 與 `format --check`：本次十個 Python 檔，exit 0。
- `python -m compileall -q`：本次十個 Python 檔，exit 0。此環境沒有聲稱使用 Python 3.11 interpreter；另以 AST `feature_version=(3, 11)` 檢查語法。
- 變異之後重新跑 108 tests，確認來源已還原且全部通過。

## 守衛刪除變異

每次只改一個守衛，執行表列獨立測試，再於 finally 還原來源。只計真正執行測試後的失敗；語法／import failure 不算殺死變異。
本輪合計 **90／90 KILLED**：建成／執行 29、E2 28、晉級／重放 33。沒有 survivors。含額外複合條件的個別 predicate 刪除，以及具體行為安全分支的刪除。
# Intake/executor deletion mutations

Each run removes only one complete guard, executes its named test in a fresh interpreter, and restores source in finally. Syntax/import failures do not count.

| Guard | Killing test | Result |
|---|---|---|
| candidate_reference | tests.test_m3_candidate_intake.IntakeTests.test_candidate_reference | KILLED |
| candidate_verdict | tests.test_m3_candidate_intake.IntakeTests.test_candidate_verdict | KILLED |
| candidate_consumed | tests.test_m3_candidate_intake.IntakeTests.test_candidate_consumed | KILLED |
| candidate_samples | tests.test_m3_candidate_intake.IntakeTests.test_candidate_samples | KILLED |
| candidate_dataset | tests.test_m3_candidate_intake.IntakeTests.test_candidate_dataset | KILLED |
| candidate_shape | tests.test_m3_candidate_intake.IntakeTests.test_candidate_shape | KILLED |
| candidate_stop | tests.test_m3_candidate_intake.IntakeTests.test_candidate_stop | KILLED |
| candidate_target | tests.test_m3_candidate_intake.IntakeTests.test_candidate_target | KILLED |
| candidate_quantity | tests.test_m3_candidate_intake.IntakeTests.test_candidate_quantity | KILLED |
| build_kind | tests.test_m3_candidate_intake.IntakeTests.test_build_kind | KILLED |
| build_contract | tests.test_m3_candidate_intake.IntakeTests.test_build_contract | KILLED |
| build_instrument | tests.test_m3_candidate_intake.IntakeTests.test_build_instrument | KILLED |
| build_interval | tests.test_m3_candidate_intake.IntakeTests.test_build_interval | KILLED |
| build_sizing | tests.test_m3_candidate_intake.IntakeTests.test_build_sizing | KILLED |
| build_busy | tests.test_m3_candidate_intake.IntakeTests.test_build_busy | KILLED |
| build_window | tests.test_m3_candidate_intake.IntakeTests.test_build_window | KILLED |
| build_trades | tests.test_m3_candidate_intake.IntakeTests.test_build_trades | KILLED |
| build_consent_type | tests.test_m3_candidate_intake.IntakeTests.test_build_consent_type | KILLED |
| test_no_completed_bars | tests.test_m3_prefix_consistency.ExecutorTests.test_no_completed_bars | KILLED |
| test_history_anchor_empty_window | tests.test_m3_prefix_consistency.ExecutorTests.test_history_anchor_empty_window | KILLED |
| test_equal_target_no_duplicate_intent | tests.test_m3_prefix_consistency.ExecutorTests.test_equal_target_no_duplicate_intent | KILLED |

## Individual compound-predicate removal and alias mutation

| Guard | Killing test | Result |
|---|---|---|
| candidate JSON failure conversion | tests.test_m3_candidate_intake.IntakeTests.test_candidate_json | KILLED |
| candidate dataset family | tests.test_m3_candidate_intake.IntakeTests.test_candidate_dataset | KILLED |
| candidate dataset interval | tests.test_m3_candidate_intake.IntakeTests.test_candidate_dataset | KILLED |
| candidate quantity type | tests.test_m3_candidate_intake.IntakeTests.test_candidate_quantity | KILLED |
| candidate quantity value | tests.test_m3_candidate_intake.IntakeTests.test_candidate_quantity | KILLED |
| window cap | tests.test_m3_candidate_intake.IntakeTests.test_build_window | KILLED |
| empty window | tests.test_m3_candidate_intake.IntakeTests.test_build_window | KILLED |
| canonical alias ownership | tests.test_m3_candidate_intake.IntakeTests.test_alias_contract_does_not_bypass_busy | KILLED |
# E2 deletion-mutation results

Each mutant removes exactly one complete boundary guard block.

| Deleted guard | Result | Independent test |
|---|---|---|
| training_partition | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_training_partition_guard` |
| cost_version | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_cost_version_guard` |
| contract | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_contract_guard` |
| minimum_bars | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_minimum_bars_guard` |
| available_before_now | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_available_before_now_guard` |
| ordered_bars | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_ordered_bars_guard` |
| expiry | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_expiry_guard` |
| window_limit | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_window_limit_guard` |
| daily_settings | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_daily_settings_guard` |
| daily_historical_contract | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_daily_historical_contract_guard` |
| daily_coverage | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_daily_coverage_guard` |
| minute_settings | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_minute_settings_guard` |
| minute_identity | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_minute_identity_guard` |
| frozen_cutoff | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_frozen_cutoff_guard` |
| minute_historical_contract | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_minute_historical_contract_guard` |
| minute_count | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_minute_count_guard` |
| minute_grid | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_minute_grid_guard` |
| anchor | KILLED | `tests.test_m3_signal_research.SignalResearchTests.test_anchor_guard` |

## training_partition
```text
F
======================================================================
FAIL: test_training_partition_guard (tests.test_m3_signal_research.SignalResearchTests.test_training_partition_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 249, in test_training_partition_guard
    self.reject('training partition required', partition='OTHER')
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.002s

FAILED (failures=1)

```
## cost_version
```text
F
======================================================================
FAIL: test_cost_version_guard (tests.test_m3_signal_research.SignalResearchTests.test_cost_version_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 252, in test_cost_version_guard
    self.reject('cost version mismatch', fees=FeeSchedule(version='other'))
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## contract
```text
F
======================================================================
FAIL: test_contract_guard (tests.test_m3_signal_research.SignalResearchTests.test_contract_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 256, in test_contract_guard
    self.reject('resolved TMF contract', auto=replace(args['auto'], instrument_rule='OTHER'))
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## minimum_bars
```text
F
======================================================================
FAIL: test_minimum_bars_guard (tests.test_m3_signal_research.SignalResearchTests.test_minimum_bars_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 262, in test_minimum_bars_guard
    with self.assertRaisesRegex(DomainError, 'at least two'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```
## available_before_now
```text
F
======================================================================
FAIL: test_available_before_now_guard (tests.test_m3_signal_research.SignalResearchTests.test_available_before_now_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 267, in test_available_before_now_guard
    self.reject('available before now', now=args['bars'][-1].ends_at)
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## ordered_bars
```text
F
======================================================================
FAIL: test_ordered_bars_guard (tests.test_m3_signal_research.SignalResearchTests.test_ordered_bars_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 275, in test_ordered_bars_guard
    with self.assertRaisesRegex(DomainError, 'ordered non-overlapping'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```
## expiry
```text
F
======================================================================
FAIL: test_expiry_guard (tests.test_m3_signal_research.SignalResearchTests.test_expiry_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 280, in test_expiry_guard
    self.reject('contract expired', spec=replace(args['spec'], expiry=date(2026, 11, 2)))
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## window_limit
```text
F
======================================================================
FAIL: test_window_limit_guard (tests.test_m3_signal_research.SignalResearchTests.test_window_limit_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 291, in test_window_limit_guard
    self.reject('exceeds bar limit')
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## daily_settings
```text
F
======================================================================
FAIL: test_daily_settings_guard (tests.test_m3_signal_research.SignalResearchTests.test_daily_settings_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 297, in test_daily_settings_guard
    with self.assertRaisesRegex(DomainError, 'minute settings do not describe daily'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.002s

FAILED (failures=1)

```
## daily_historical_contract
```text
F
======================================================================
FAIL: test_daily_historical_contract_guard (tests.test_m3_signal_research.SignalResearchTests.test_daily_historical_contract_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 303, in test_daily_historical_contract_guard
    with self.assertRaisesRegex(DomainError, 'historical contract applicability'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```
## daily_coverage
```text
F
======================================================================
FAIL: test_daily_coverage_guard (tests.test_m3_signal_research.SignalResearchTests.test_daily_coverage_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 309, in test_daily_coverage_guard
    with self.assertRaisesRegex(DomainError, 'daily coverage incomplete'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```
## minute_settings
```text
F
======================================================================
FAIL: test_minute_settings_guard (tests.test_m3_signal_research.SignalResearchTests.test_minute_settings_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 315, in test_minute_settings_guard
    self.reject('explicit minute training settings', settings=fixed)
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## minute_identity
```text
F
======================================================================
FAIL: test_minute_identity_guard (tests.test_m3_signal_research.SignalResearchTests.test_minute_identity_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 321, in test_minute_identity_guard
    with self.assertRaisesRegex(DomainError, 'minute settings mismatch'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```
## frozen_cutoff
```text
F
======================================================================
FAIL: test_frozen_cutoff_guard (tests.test_m3_signal_research.SignalResearchTests.test_frozen_cutoff_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 325, in test_frozen_cutoff_guard
    self.reject('cutoff is fixed', settings=replace(fixture()['settings'], cutoff_minute=13 * 60 + 30))
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## minute_historical_contract
```text
F
======================================================================
FAIL: test_minute_historical_contract_guard (tests.test_m3_signal_research.SignalResearchTests.test_minute_historical_contract_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 330, in test_minute_historical_contract_guard
    self.reject('historical contract applicability', spec=observed)
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## minute_count
```text
F
======================================================================
FAIL: test_minute_count_guard (tests.test_m3_signal_research.SignalResearchTests.test_minute_count_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 336, in test_minute_count_guard
    self.reject('complete minute sessions', bars=fixture()['bars'][:-1])
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## minute_grid
```text
F
======================================================================
FAIL: test_minute_grid_guard (tests.test_m3_signal_research.SignalResearchTests.test_minute_grid_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 341, in test_minute_grid_guard
    self.reject('minute completion grid', bars=bars)
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 116, in reject
    with self.assertRaisesRegex(DomainError, reason) as caught:
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```
## anchor
```text
F
======================================================================
FAIL: test_anchor_guard (tests.test_m3_signal_research.SignalResearchTests.test_anchor_guard)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 285, in test_anchor_guard
    with self.assertRaisesRegex(DomainError, 'frozen anchor'):
         ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
AssertionError: DomainError not raised

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```
# Execution safety/behavior mutations

| Removed safety behavior | Result | Test |
|---|---|---|
| protective_stop | KILLED | `test_stops_apply_on_entry_bar_and_use_adverse_gap_price` |
| short_stop | KILLED | `test_short_stop_and_gap_are_adverse` |
| time_stop | KILLED | `test_time_stop_and_terminal_liquidation` |
| cutoff_flatten | KILLED | `test_intraday_flat_cutoff_no_reentry_and_window_reset` |
| cutoff_no_reentry | KILLED | `test_intraday_flat_cutoff_no_reentry_and_window_reset` |
| terminal_liquidation | KILLED | `test_time_stop_and_terminal_liquidation` |
| same_day_entry | KILLED | `test_intraday_flat_cutoff_no_reentry_and_window_reset` |
| completed_prefix | KILLED | `test_reversal_closes_then_opens_with_each_leg_cost` |
| mark_peak | KILLED | `test_mark_to_market_drawdown_includes_unrealized_peak` |
| behavior_valuation | KILLED | `test_valuation_change_invalidates_behavior_even_with_identical_trades` |

## protective_stop
```text
F
======================================================================
FAIL: test_stops_apply_on_entry_bar_and_use_adverse_gap_price (tests.test_m3_signal_research.SignalResearchTests.test_stops_apply_on_entry_bar_and_use_adverse_gap_price)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 201, in test_stops_apply_on_entry_bar_and_use_adverse_gap_price
    self.assertEqual((result.trades[0].entry_index, result.trades[0].exit_index), (1, 1))
AssertionError: Tuples differ: (1, 15) != (1, 1)

First differing element 1:
15
1

- (1, 15)
?      -

+ (1, 1)

----------------------------------------------------------------------
Ran 1 test in 0.003s

FAILED (failures=1)

```

## short_stop
```text
F
======================================================================
FAIL: test_short_stop_and_gap_are_adverse (tests.test_m3_signal_research.SignalResearchTests.test_short_stop_and_gap_are_adverse)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 215, in test_short_stop_and_gap_are_adverse
    self.assertEqual(result.trades[0].exit, D(20201))
AssertionError: Decimal('20016') != Decimal('20201')

----------------------------------------------------------------------
Ran 1 test in 0.002s

FAILED (failures=1)

```

## time_stop
```text
F
======================================================================
FAIL: test_time_stop_and_terminal_liquidation (tests.test_m3_signal_research.SignalResearchTests.test_time_stop_and_terminal_liquidation)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 224, in test_time_stop_and_terminal_liquidation
    self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 3), (4, 5)])
AssertionError: Lists differ: [(1, 5)] != [(1, 3), (4, 5)]

First differing element 0:
(1, 5)
(1, 3)

Second list contains 1 additional elements.
First extra element 1:
(4, 5)

- [(1, 5)]
+ [(1, 3), (4, 5)]

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```

## cutoff_flatten
```text
F
======================================================================
FAIL: test_intraday_flat_cutoff_no_reentry_and_window_reset (tests.test_m3_signal_research.SignalResearchTests.test_intraday_flat_cutoff_no_reentry_and_window_reset)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 230, in test_intraday_flat_cutoff_no_reentry_and_window_reset
    self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 15), (21, 35)])
AssertionError: Lists differ: [(1, 39)] != [(1, 15), (21, 35)]

First differing element 0:
(1, 39)
(1, 15)

Second list contains 1 additional elements.
First extra element 1:
(21, 35)

- [(1, 39)]
+ [(1, 15), (21, 35)]

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)

```

## cutoff_no_reentry
```text
F
======================================================================
FAIL: test_intraday_flat_cutoff_no_reentry_and_window_reset (tests.test_m3_signal_research.SignalResearchTests.test_intraday_flat_cutoff_no_reentry_and_window_reset)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 230, in test_intraday_flat_cutoff_no_reentry_and_window_reset
    self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 15), (21, 35)])
AssertionError: Lists differ: [(1, 15), (15, 16), (16, 17), (17, 18), (18, 19), (1[42 chars] 39)] != [(1, 15), (21, 35)]

First differing element 1:
(15, 16)
(21, 35)

First list contains 8 additional elements.
First extra element 2:
(16, 17)

+ [(1, 15), (21, 35)]
- [(1, 15),
-  (15, 16),
-  (16, 17),
-  (17, 18),
-  (18, 19),
-  (19, 35),
-  (35, 36),
-  (36, 37),
-  (37, 38),
-  (38, 39)]

----------------------------------------------------------------------
Ran 1 test in 0.005s

FAILED (failures=1)

```

## terminal_liquidation
```text
F
======================================================================
FAIL: test_time_stop_and_terminal_liquidation (tests.test_m3_signal_research.SignalResearchTests.test_time_stop_and_terminal_liquidation)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 224, in test_time_stop_and_terminal_liquidation
    self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 3), (4, 5)])
AssertionError: Lists differ: [(1, 3)] != [(1, 3), (4, 5)]

Second list contains 1 additional elements.
First extra element 1:
(4, 5)

- [(1, 3)]
+ [(1, 3), (4, 5)]

----------------------------------------------------------------------
Ran 1 test in 0.002s

FAILED (failures=1)

```

## same_day_entry
```text
F
======================================================================
FAIL: test_intraday_flat_cutoff_no_reentry_and_window_reset (tests.test_m3_signal_research.SignalResearchTests.test_intraday_flat_cutoff_no_reentry_and_window_reset)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 230, in test_intraday_flat_cutoff_no_reentry_and_window_reset
    self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 15), (21, 35)])
AssertionError: Lists differ: [(1, 15), (20, 35)] != [(1, 15), (21, 35)]

First differing element 1:
(20, 35)
(21, 35)

- [(1, 15), (20, 35)]
?             ^

+ [(1, 15), (21, 35)]
?             ^


----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)

```

## completed_prefix
```text
F
======================================================================
FAIL: test_reversal_closes_then_opens_with_each_leg_cost (tests.test_m3_signal_research.SignalResearchTests.test_reversal_closes_then_opens_with_each_leg_cost)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 178, in test_reversal_closes_then_opens_with_each_leg_cost
    self.assertEqual([(t.entry_index, t.exit_index) for t in result.trades], [(1, 2), (2, 4)])
AssertionError: Lists differ: [(1, 3)] != [(1, 2), (2, 4)]

First differing element 0:
(1, 3)
(1, 2)

Second list contains 1 additional elements.
First extra element 1:
(2, 4)

- [(1, 3)]
+ [(1, 2), (2, 4)]

----------------------------------------------------------------------
Ran 1 test in 0.002s

FAILED (failures=1)

```

## mark_peak
```text
F
======================================================================
FAIL: test_mark_to_market_drawdown_includes_unrealized_peak (tests.test_m3_signal_research.SignalResearchTests.test_mark_to_market_drawdown_includes_unrealized_peak)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 149, in test_mark_to_market_drawdown_includes_unrealized_peak
    self.assertEqual(result.expectation.max_drawdown_pct, D('0.02015'))
AssertionError: Decimal('0.0007') != Decimal('0.02015')

----------------------------------------------------------------------
Ran 1 test in 0.001s

FAILED (failures=1)

```

## behavior_valuation
```text
F
======================================================================
FAIL: test_valuation_change_invalidates_behavior_even_with_identical_trades (tests.test_m3_signal_research.SignalResearchTests.test_valuation_change_invalidates_behavior_even_with_identical_trades)
----------------------------------------------------------------------
Traceback (most recent call last):
  File "/workspace/scratch/0551d866db25/markauto-m3/m3-3/tests/test_m3_signal_research.py", line 163, in test_valuation_change_invalidates_behavior_even_with_identical_trades
    self.assertNotEqual(original.behavior_hash, changed.behavior_hash)
AssertionError: 'a5d5a30e691c11beab5926ae049846515f41d37c4424d6b7969232ea64a97467' == 'a5d5a30e691c11beab5926ae049846515f41d37c4424d6b7969232ea64a97467'

----------------------------------------------------------------------
Ran 1 test in 0.004s

FAILED (failures=1)

```
# M3 promotion verification

`python -m unittest tests.test_m3_promotion_service`: 42 passed.

Each mutation ran separately against its named test, restoring source in finally. Guard predicates were deleted/disabled independently.

| Guard | Killing test | Result |
|---|---|---|
| replay schema | `test_replay_schema_guard` | KILLED |
| restart pause | `test_replay_cache_and_restart_guard` | KILLED |
| duplicate build | `test_duplicate_build_guard` | KILLED |
| build initial state | `test_build_stage_guard` | KILLED |
| build eligibility flag | `test_build_flags_guard` | KILLED |
| build observation flag | `test_build_flags_guard` | KILLED |
| broker simulation environment | `test_no_local_or_live_promotion_evidence` | KILLED |
| instrument uniqueness | `test_unique_resolved_instrument_guard` | KILLED |
| evaluation idempotence | `test_evaluation_idempotence_guard` | KILLED |
| running simulation evaluation | `test_evaluation_running_guard` | KILLED |
| observation epoch | `test_evaluation_epoch_guard` | KILLED |
| observation chronological date | `test_evaluation_date_guard` | KILLED |
| drift pause | `test_drift_floor_and_exact_boundary_pause_guard` | KILLED |
| drift no backtest transition | `test_drift_backtest_does_not_transition` | KILLED |
| drift paused idempotence | `test_drift_floor_and_exact_boundary_pause_guard` | KILLED |
| behavior changed | `test_changed_behavior_pause_guard` | KILLED |
| changed behavior pause action | `test_changed_behavior_pause_guard` | KILLED |
| changed behavior backtest rejection | `test_changed_behavior_backtest_denies_guard` | KILLED |
| refresh idempotence | `test_same_behavior_upgrade_and_idempotence_guard` | KILLED |
| journal first ordering | `test_journal_failure_does_not_publish_state` | KILLED |
| record schema | `test_replay_record_schema_guard` | KILLED |
| allocation positive | `test_allocation_positive_guard` | KILLED |
| allocation immutable | `test_replay_allocation_immutable_guard` | KILLED |
| evaluation shape | `test_replay_evaluation_shape_guard` | KILLED |
| evaluation type | `test_replay_evaluation_type_guard` | KILLED |
| evaluation key | `test_replay_evaluation_identity_guard` | KILLED |
| evaluation epoch identity | `test_replay_evaluation_identity_guard` | KILLED |
| replay immutable account_ref | `test_replay_evidence_identity_immutable_guards` | KILLED |
| replay immutable execution_instrument_id | `test_replay_evidence_identity_immutable_guards` | KILLED |
| replay immutable candidate | `test_replay_evidence_identity_immutable_guards` | KILLED |
| built evidence identity | `test_build_evidence_identity_guard` | KILLED |
| refresh evidence identity | `test_refresh_evidence_identity_guard` | KILLED |
| same behavior immutable evidence | `test_same_behavior_different_evidence_guard` | KILLED |

## 尚未接線／不宣稱完成

- 生產 CandidateCatalog 的安全 E1 摘要產生者尚缺；`TMF` 是明確 qualification 契約，不是虛構既有 metadata。
- 引擎／IPC／AppState／中央 registry／UI／K 棒排程／worker timeout 與取消／回補是後續 M3-4／6／7。沒有在此接通任何自動送單。
- PromotionService 的 preopen、reconciled、完整日與 SimObservation 由可信主機提供，未在此冒充查詢券商驗證。
- 日 K／股票領域值可測試純協定，但 D6 建成仍只放行 TMF 當沖；股票與正式交易未啟用。
- 沒有 approve_live 入口；LIVE_APPROVED 不授權新倉；未做真實桌面開窗（本 lane 無 UI／runtime 變更）。
- GitNexus 不存在，採 grep／import 圖／affected_tests 代替。完整 CI 與 PR 發布由主協調者處理，不合併。

## 既有回歸與靜態閘門

- `QT_QPA_PLATFORM=offscreen python -m unittest tests.test_m3_signal_strategy tests.test_m3_promotion tests.test_trading_research_worker tests.test_trading_research_concurrency tests.test_minute_research tests.test_minute_research_basis tests.test_trading_domain`：127 tests，exit 0。
- `python tools/quality_gate.py`、`python tools/check_layers.py --baseline-ref origin/main`、`python tools/check_trading_architecture.py`：皆 exit 0，零 finding／violation。
- 十個新增 Python 檔以 `ast.parse(..., feature_version=(3, 11))` 檢查：exit 0。
- `affected_tests.py --list` 選出的文件／import／page-service 相關測試先跑 75 tests：74 通過；唯一失敗是 page-services observer 釘選新增兩個 `self.bars` 測試觀察點。這是保守掃描器的預期基準差異，不是 UI 行為改動。
- 將以獨立基準 commit 登記五個 application 檔案與上述兩個 observer；只更新預期值，不修改斷言。最終基準與 affected-tests 結果由後續驗證追加。

新增／使用錯誤碼完整集合：`candidate_not_passed`、`candidate_unavailable`、`candidate_spec_unsupported`、`candidate_data_mismatch`、`auto_instrument_not_allowed`、`auto_instrument_busy`、`auto_execution_data_insufficient`、`auto_evidence_changed`、`auto_frozen`，並沿用 `validation_failed`、`stage_transition_denied` 及既有 calendar／instrument 邊界錯誤。中央 UI ErrorText 對照仍屬 M3-4。

## 最終基準與 affected-tests 驗證

- 功能 commit：`5204687`。獨立 `test(baseline)` commit：`7b0c827`，只含五個檔案盤點列與兩個測試 observer 預期值。
- `QT_QPA_PLATFORM=offscreen python tools/repin_baselines.py --only inventory --only observers --inventory-note 'M3-3 signal strategy application services; existing domain and M2 interfaces unchanged' --write`：exit 0，工具內建驗證完成。
- 寫入後 `python tools/repin_baselines.py --only inventory --only observers`：exit 0，兩組皆 up-to-date。
- `python tools/affected_tests.py --list` 選取 16 個模組；逐模組名交給 unittest（不是 discover 全套）：**263 tests，exit 0，36.531 秒**。
  模組：`test_affected_tests`、`test_docs_layering`、`test_download_auto_import_contracts`、`test_import_graph`、`test_layer_gate`、`test_lb_b3_indicators`、`test_m3_candidate_intake`、`test_m3_prefix_consistency`、`test_m3_promotion_service`、`test_m3_signal_research`、`test_m3_stage_matrix`、`test_page_services_r1`、`test_r7_characterization`、`test_repin_baselines`、`test_repo_layout`、`test_trade_statistics_b1`。
- 最終 `check_layers.py --baseline-ref origin/main`：exit 0。`git diff --check` 無 whitespace 問題；M3-1、G3、desktop_app、PROJECT_STATE 與 SDK 版本無修改。
- 本機不推送、不合併；主協調者負責更新正式 PR 與 CI。CI 尚未在此報告宣稱通過。
